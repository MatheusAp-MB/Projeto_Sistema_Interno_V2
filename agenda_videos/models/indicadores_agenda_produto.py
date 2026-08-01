# agenda_videos/models/indicadores_agenda_produto.py

# Função Objetivo: Resumo DERIVADO e recalculável — só existe pra listar/ordenar/
# filtrar milhares de produtos rápido, sem reexecutar a lógica de negócio linha
# por linha. NUNCA é fonte de dado real — sempre cópia. Sincronização (Frente 3)
# ainda não escrita neste passo.
#
# ⚠️ ATENÇÃO — qualquer escrita em CicloVideo, ConfiguracaoFase ou
# ParticipacaoAgenda precisa terminar re-sincronizando esta tabela, senão fica
# desatualizada silenciosamente. Nenhuma AÇÃO (clique, decisão) deve confiar só
# nela — sempre reconferir a fonte real antes de agir.

from django.db import models
from produtos.models import Produto
from .participacao_agenda import StatusManualAgenda


class IndicadoresAgendaProduto(models.Model):
    produto = models.OneToOneField(Produto, on_delete=models.CASCADE, related_name='indicadores_agenda')

    etapa_atual = models.CharField(max_length=25, blank=True, default='')
    fase_atual = models.CharField(max_length=20, blank=True, default='')
    ciclo_atual_atrasado = models.BooleanField(default=False)
    tem_video_reprovado = models.BooleanField(default=False)
    status_manual = models.CharField(
        max_length=15, choices=StatusManualAgenda.choices, default=StatusManualAgenda.ATIVO)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Indicadores da Agenda'
        verbose_name_plural = 'Indicadores da Agenda'

    def __str__(self):
        return f'{self.produto.sku} — {self.etapa_atual or "sem indicador ainda"}'