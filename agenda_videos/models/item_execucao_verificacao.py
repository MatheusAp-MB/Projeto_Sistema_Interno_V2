# agenda_videos/models/item_execucao_verificacao.py

# Função Objetivo: Representa 1 produto dentro de 1 ExecucaoVerificacaoAprovacao.
# Fluxo mais curto que o de Postagem/Replicação — sem baixar/arquivar arquivo
# nem interagir com outros anúncios, só LER o Estado na tela — por isso os
# campos extras (mlb, estado_lido, resultado_aplicado) guardam o que foi lido
# e o que foi feito com aquilo, pra aparecer na tela de progresso.

from django.db import models
from produtos.models import Produto
from .execucao_verificacao_aprovacao import ExecucaoVerificacaoAprovacao


class StatusItemExecucaoVerificacao(models.TextChoices):
    AGUARDANDO = 'aguardando', 'Aguardando'
    LENDO = 'lendo', 'Lendo'
    CONCLUIDO = 'concluido', 'Concluído'
    FALHOU = 'falhou', 'Falhou'
    CANCELADO = 'cancelado', 'Cancelado'


class ItemExecucaoVerificacao(models.Model):
    execucao = models.ForeignKey(
        ExecucaoVerificacaoAprovacao, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    # * [EXPLICAÇÃO] → Gravado direto aqui (mesmo max_length de
    #                  CicloVideo.mlb_postado) — a Verificação já sabe o MLB
    #                  desde a criação do item (vem de
    #                  listar_ciclos_aguardando_aprovacao_com_mlb), não
    #                  precisa rebuscar depois.
    mlb = models.CharField(max_length=20)
    ordem = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=StatusItemExecucaoVerificacao.choices,
        default=StatusItemExecucaoVerificacao.AGUARDANDO,
    )
    # * [EXPLICAÇÃO] → O que foi lido de verdade na tela (PUBLICADO, RECUSADO,
    #                  EM REVISÃO, PAUSADO — ou None, sem valor gravado) e o
    #                  que aplicar_estado_lido() decidiu fazer com isso
    #                  (atualizado / sem_mudanca / ciclo_nao_encontrado).
    estado_lido = models.CharField(max_length=20, blank=True, null=True)
    resultado_aplicado = models.CharField(max_length=30, blank=True, null=True)
    mensagem_erro = models.CharField(max_length=255, blank=True, null=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Item de Execução de Verificação'
        verbose_name_plural = 'Itens de Execução de Verificação'
        ordering = ['ordem']

    def __str__(self):
        return f'{self.mlb} — {self.get_status_display()}'