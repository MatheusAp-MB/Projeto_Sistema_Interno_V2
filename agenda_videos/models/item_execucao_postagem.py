# agenda_videos/models/item_execucao_postagem.py

# Função Objetivo: Representa 1 produto dentro de 1 ExecucaoPostagemAutomatica
# — status granular (Baixando/Postando/Atualizando Agenda/Arquivando/
# Concluído/Falhou/Cancelado), pra a tela de progresso mostrar item por item,
# não só "está rodando" genérico.

from django.db import models
from produtos.models import Produto
from .execucao_postagem_automatica import ExecucaoPostagemAutomatica


class StatusItemExecucao(models.TextChoices):
    AGUARDANDO = 'aguardando', 'Aguardando'
    BAIXANDO = 'baixando', 'Baixando'
    POSTANDO = 'postando', 'Postando'
    ATUALIZANDO_AGENDA = 'atualizando_agenda', 'Atualizando Agenda'
    ARQUIVANDO = 'arquivando', 'Arquivando'
    CONCLUIDO = 'concluido', 'Concluído'
    FALHOU = 'falhou', 'Falhou'
    CANCELADO = 'cancelado', 'Cancelado'
    JA_POSTADO_HOJE = 'ja_postado_hoje', 'Já postado hoje — pulado'


class ItemExecucaoPostagem(models.Model):
    execucao = models.ForeignKey(
        ExecucaoPostagemAutomatica, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    ordem = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=StatusItemExecucao.choices, default=StatusItemExecucao.AGUARDANDO,
    )
    mensagem_erro = models.CharField(max_length=255, blank=True, null=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    # * [EXPLICAÇÃO] → Timestamp de CADA etapa — permite a tela mostrar a
    #                  linha do tempo completa de 1 item (quando baixou,
    #                  quando postou, etc.), não só o status final. None =
    #                  esse item nunca chegou nessa etapa (ex: falhou antes).
    baixando_em = models.DateTimeField(null=True, blank=True)
    postando_em = models.DateTimeField(null=True, blank=True)
    atualizando_agenda_em = models.DateTimeField(null=True, blank=True)
    arquivando_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Item de Execução de Postagem'
        verbose_name_plural = 'Itens de Execução de Postagem'
        ordering = ['ordem']

    def __str__(self):
        return f'{self.produto.sku or self.produto.ean} — {self.get_status_display()}'