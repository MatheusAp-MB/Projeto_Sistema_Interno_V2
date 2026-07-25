# agenda_videos/models/postagem.py

# Função Objetivo: Histórico de cada postagem de vídeo — 1 registro NOVO por ocorrência,
# nunca sobrescreve o anterior.
# Explicação em detalhe: é essa natureza de histórico que permite responder "esse produto
# já teve alguma postagem aprovada/replicada alguma vez?" — base do critério "Sem vídeo
# nenhum" (prioridade 3 da tela "A Fazer"). "fase" aqui é um SNAPSHOT (TextChoices, não FK)
# de propósito — mesmo que ConfiguracaoFase mude no futuro, o registro histórico preserva
# qual era a fase no momento exato desta postagem.

from django.db import models
from produtos.models import Produto
from .configuracao_fase import Fase


class StatusPostagem(models.TextChoices):
    AGUARDANDO_APROVACAO = 'aguardando_aprovacao', 'Aguardando aprovação'
    APROVADO = 'aprovado', 'Aprovado'
    RECUSADO = 'recusado', 'Recusado'
    REPLICADO = 'replicado', 'Replicado'


class Postagem(models.Model):
    produto = models.ForeignKey(
        Produto, on_delete=models.CASCADE, related_name='postagens_agenda')

    fase = models.CharField(max_length=10, choices=Fase.choices)
    numero_ocorrencia = models.PositiveIntegerField()

    inicio_ocorrencia = models.DateField()
    fim_ocorrencia = models.DateField()

    status = models.CharField(
        max_length=25, choices=StatusPostagem.choices,
        default=StatusPostagem.AGUARDANDO_APROVACAO)

    # * [EXPLICAÇÃO] → Texto livre, não FK — os arquivos de vídeo ainda vivem só na pasta
    #                  local do usuário (Videos ML/...), não existe model de vídeo no
    #                  banco ainda. Suficiente pra auditoria por enquanto (ex: "Roteiro 03").
    identificador_video = models.CharField(max_length=100, blank=True, null=True)

    # Função Objetivo: Datas de transição, pra auditoria — preenchidas conforme o status avança.
    aguardando_aprovacao_em = models.DateTimeField(blank=True, null=True)
    aprovado_ou_recusado_em = models.DateTimeField(blank=True, null=True)
    replicado_em = models.DateTimeField(blank=True, null=True)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Postagem'
        verbose_name_plural = 'Postagens'
        ordering = ['-criado_em']

    def __str__(self):
        return f'{self.produto.sku} — {self.get_fase_display()} #{self.numero_ocorrencia} ({self.get_status_display()})'