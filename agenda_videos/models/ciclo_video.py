# agenda_videos/models/ciclo_video.py

# Função Objetivo: 1 registro por ocorrência (produto, fase, número) — histórico
# completo e imutável de tudo que aconteceu nesse ciclo de produção/postagem.
# Reestruturação completa (30/07) — antes "Postagem" só cobria Postar/Replicar,
# com Roteiro/Completo vivendo separados por FASE (pool reaproveitado). Agora
# cada ocorrência produz do zero, e tudo mora numa linha só.
# fase/numero_ocorrencia/data_devida são SNAPSHOT (nunca reescritos depois de
# criados) — preservam o que era verdade no momento exato desta ocorrência,
# mesmo que ConfiguracaoFase mude depois.

from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone

from produtos.models import Produto
from .configuracao_fase import Fase, ConfiguracaoFase


class StatusPostagem(models.TextChoices):
    AGUARDANDO_APROVACAO = 'aguardando_aprovacao', 'Aguardando Aprovação'
    APROVADO = 'aprovado', 'Aprovado'
    RECUSADO = 'recusado', 'Recusado'
    REPLICADO = 'replicado', 'Replicado'


class CicloVideo(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='ciclos_video')

    fase = models.CharField(max_length=20, choices=Fase.choices)
    numero_ocorrencia = models.PositiveIntegerField()
    data_devida = models.DateField()

    base_concluido_em = models.DateTimeField(null=True, blank=True)
    roteiro_concluido_em = models.DateTimeField(null=True, blank=True)
    completo_concluido_em = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=25, choices=StatusPostagem.choices, null=True, blank=True)
    aguardando_aprovacao_em = models.DateTimeField(null=True, blank=True)
    aprovado_ou_recusado_em = models.DateTimeField(null=True, blank=True)
    replicado_em = models.DateTimeField(null=True, blank=True)

    mlbs_replicados = models.JSONField(default=list)
    mlbs_nao_encontrados = models.JSONField(default=list)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Ciclo de Vídeo'
        verbose_name_plural = 'Ciclos de Vídeo'
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(fields=['produto', 'fase', 'numero_ocorrencia'], name='unico_ciclo_por_ocorrencia'),
        ]

    def __str__(self):
        return f'{self.produto.sku} — {self.get_fase_display()} #{self.numero_ocorrencia} ({self.etapa_atual()})'

    # * [EXPLICAÇÃO] → Único lugar do sistema que decide "em que pé está esse
    #                  ciclo" — ninguém, em nenhuma view/template, deve checar
    #                  os campos de data crus por fora daqui.
    def etapa_atual(self):
        if self.base_concluido_em is None:
            return 'base'
        if self.roteiro_concluido_em is None:
            return 'roteiro'
        if self.completo_concluido_em is None:
            return 'completo'
        if self.status is None:
            return 'postar'
        if self.status == StatusPostagem.AGUARDANDO_APROVACAO:
            return 'aguardando_aprovacao'
        if self.status == StatusPostagem.RECUSADO:
            return 'completo'  # precisa refazer o Completo e postar de novo
        if self.status == StatusPostagem.APROVADO:
            return 'replicar'
        return 'concluido'

    # * [EXPLICAÇÃO] → "Atrasado" só existe em relação a POSTAR (é a única etapa
    #                  com data-trava — confirmado com o usuário). Depois de
    #                  postado, o prazo já foi cumprido, mesmo que Replicar
    #                  ainda esteja pendente (Replicar não tem trava de data).
    def esta_atrasado(self):
        if self.aguardando_aprovacao_em is not None:
            return False
        return timezone.localdate() > self.data_devida

    # * [EXPLICAÇÃO] → Encapsula a ÚNICA regra de "o que vem depois" — nunca deve
    #                  ser reimplementada em nenhum outro lugar do código.
    #                  Import local (não no topo do arquivo) só pra não criar
    #                  import circular com funcoes_auxiliares — mesmo padrão já
    #                  usado em api/replicacao_automatica/views.py.
    def criar_proximo(self):
        from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje

        config_atual = ConfiguracaoFase.objects.get(fase=self.fase)

        if config_atual.dentro_do_periodo(self.numero_ocorrencia + 1):
            fase_config = config_atual
            numero_ocorrencia = self.numero_ocorrencia + 1
            distancia = config_atual.distancia_dias_corridos
        else:
            fase_config = config_atual.proxima_fase
            numero_ocorrencia = 1
            distancia = fase_config.distancia_dias_ao_entrar_na_fase

        data_calculada = self.replicado_em.date() + timedelta(days=distancia)
        data_devida = ultimo_dia_util_ou_hoje(data_calculada)

        return CicloVideo.objects.create(
            produto=self.produto, fase=fase_config.fase,
            numero_ocorrencia=numero_ocorrencia, data_devida=data_devida,
        )

    def marcar_aguardando_aprovacao(self):
        self.status = StatusPostagem.AGUARDANDO_APROVACAO
        self.aguardando_aprovacao_em = timezone.now()
        self.save(update_fields=['status', 'aguardando_aprovacao_em'])

    # * [EXPLICAÇÃO] → Envolve as 2 escritas (marcar replicado + criar o próximo
    #                  ciclo) numa transação só — se cair no meio, as 2 acontecem
    #                  juntas ou nenhuma acontece. Nunca fazer essas 2 escritas
    #                  separadas em outro lugar do código.
    def marcar_replicado(self, mlbs_replicados, mlbs_nao_encontrados):
        with transaction.atomic():
            self.status = StatusPostagem.REPLICADO
            self.replicado_em = timezone.now()
            self.mlbs_replicados = mlbs_replicados
            self.mlbs_nao_encontrados = mlbs_nao_encontrados
            self.save(update_fields=['status', 'replicado_em', 'mlbs_replicados', 'mlbs_nao_encontrados'])
            return self.criar_proximo()

    # * [EXPLICAÇÃO] → Único ponto de entrada do produto na Agenda — Simples #1
    #                  sempre libera imediatamente (sem trava de data).
    @classmethod
    def iniciar_agenda(cls, produto):
        from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje

        hoje = ultimo_dia_util_ou_hoje(timezone.localdate())
        return cls.objects.create(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, data_devida=hoje)