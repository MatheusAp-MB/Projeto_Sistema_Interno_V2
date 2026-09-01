# agenda_videos/models/item_execucao_replicacao.py

# Função Objetivo: Representa 1 produto dentro de 1 ExecucaoReplicacaoAutomatica.
# Fluxo mais curto que o de Postagem — sem baixar/arquivar arquivo, só a
# ação no navegador — por isso os estágios intermediários são só 1
# ("Replicando"), não vários.

from django.db import models
from produtos.models import Produto
from .execucao_replicacao_automatica import ExecucaoReplicacaoAutomatica


class StatusItemExecucaoReplicacao(models.TextChoices):
    AGUARDANDO = 'aguardando', 'Aguardando'
    REPLICANDO = 'replicando', 'Replicando'
    CONCLUIDO = 'concluido', 'Concluído'
    # * [SEGURANÇA, 01/09] → Status exclusivo do modo teste
    #                  (CONFIRMAR_REPLICACAO_DE_VERDADE=False em
    #                  servidor_agente.py) — item passou pela automação e os
    #                  MLBs foram marcados na tela, mas o clique final NUNCA
    #                  aconteceu, e o CicloVideo NUNCA foi tocado. Diferente
    #                  de CONCLUIDO (replicação real, grava no ciclo) e de
    #                  FALHOU (deu erro de verdade) — evita mostrar ✗
    #                  vermelho de "erro" pra algo que só não foi confirmado
    #                  de propósito.
    TESTADO_SEM_CONFIRMAR = 'testado_sem_click', 'Testado — não confirmado (modo teste)'
    FALHOU = 'falhou', 'Falhou'
    CANCELADO = 'cancelado', 'Cancelado'


class ItemExecucaoReplicacao(models.Model):
    execucao = models.ForeignKey(
        ExecucaoReplicacaoAutomatica, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    ordem = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=StatusItemExecucaoReplicacao.choices,
        default=StatusItemExecucaoReplicacao.AGUARDANDO,
    )
    mensagem_erro = models.CharField(max_length=255, blank=True, null=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Item de Execução de Replicação'
        verbose_name_plural = 'Itens de Execução de Replicação'
        ordering = ['ordem']

    def __str__(self):
        return f'{self.produto.sku or self.produto.ean} — {self.get_status_display()}'