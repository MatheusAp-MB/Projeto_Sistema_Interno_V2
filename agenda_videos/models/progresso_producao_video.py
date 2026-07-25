# agenda_videos/models/progresso_producao_video.py

# Função Objetivo: Rastreia o progresso de produção dos ativos de vídeo de 1 produto.
# Explicação em detalhe: 1 registro por Produto, nunca reinicia — diferente de Postagem
# (histórico por ocorrência). Vídeo Simples (Objetivo 01, anúncio mínimo) e Vídeo Base
# (usado pros roteiros/Completos da Agenda) são conceitos DIFERENTES e propositalmente
# separados — confirmado com o usuário: nem sempre o Simples vira a Base; às vezes a
# equipe grava um Base novo e mais detalhado.

from django.db import models
from produtos.models import Produto


class StatusVideo(models.TextChoices):
    NAO_GERADO = 'nao_gerado', 'Não gerado'
    GERADO = 'gerado', 'Gerado'


class ProgressoProducaoVideo(models.Model):
    produto = models.OneToOneField(
        Produto, on_delete=models.CASCADE, related_name='progresso_producao_video')

    video_simples_status = models.CharField(
        max_length=15, choices=StatusVideo.choices, default=StatusVideo.NAO_GERADO)
    video_base_status = models.CharField(
        max_length=15, choices=StatusVideo.choices, default=StatusVideo.NAO_GERADO)

    roteiros_gerados = models.BooleanField(default=False)
    completos_produzidos = models.BooleanField(default=False)

    # * [EXPLICAÇÃO] → Tamanho do "pool" de vídeos Completos disponíveis (ex: 10, 1 por
    #                  dia da Fase Diária).
    quantidade_roteiros = models.PositiveIntegerField(default=0)

    # * [EXPLICAÇÃO] → Persistido (24/07) — precisa ser filtrável/paginável na tela
    #                  "Diários", então não pode ser calculado só na hora da exibição.
    #                  Recalculado automaticamente em save() (ver abaixo) sempre que
    #                  este registro é salvo — não precisa de comando separado nem de
    #                  recálculo manual. Limitação conhecida: se ConfiguracaoFase(Diária)
    #                  .periodo mudar, registros já existentes só atualizam quando forem
    #                  salvos de novo por algum outro motivo.
    roteiros_insuficientes = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Progresso de Produção de Vídeo'
        verbose_name_plural = 'Progressos de Produção de Vídeo'

    # Função Objetivo: Recalcula 'roteiros_insuficientes' sempre que o registro é salvo.
    def save(self, *args, **kwargs):
        self.roteiros_insuficientes = self._calcular_roteiros_insuficientes()
        super().save(*args, **kwargs)

    # Função Objetivo: Compara o pool disponível contra o período da Fase Diária.
    def _calcular_roteiros_insuficientes(self):
        from .configuracao_fase import ConfiguracaoFase, Fase
        try:
            periodo_diaria = ConfiguracaoFase.objects.get(fase=Fase.DIARIA).periodo
        except ConfiguracaoFase.DoesNotExist:
            return False

        return self.quantidade_roteiros < periodo_diaria

    def __str__(self):
        return f'{self.produto.sku} — vídeo simples: {self.get_video_simples_status_display()}'