# agenda_videos/models/participacao_agenda.py

# Função Objetivo: Estado PRIMÁRIO (nunca calculado) da participação de 1 produto
# na Agenda — decisões humanas (pausar/descontinuar, urgência) e o timestamp de
# quando entrou de verdade. Nunca escrito por sincronização automática — sempre
# escrito direto, por ação humana.

from django.db import models
from produtos.models import Produto


class StatusManualAgenda(models.TextChoices):
    ATIVO = 'ativo', 'Ativo'
    PAUSADO = 'pausado', 'Pausado'
    DESCONTINUADO = 'descontinuado', 'Descontinuado'


# Função Objetivo: Fonte única do "status manual atual" — nunca depende de
# ParticipacaoAgenda existir, porque HistoricoStatusManualAgenda tem FK
# direta pro Produto, sem relação nenhuma com ParticipacaoAgenda. Um produto
# pode ter sido Pausado sem NUNCA ter tido Urgente marcado ou sido Agendado
# (as 2 únicas ações que criam ParticipacaoAgenda) — o código antigo usava
# getattr(produto, 'participacao_agenda', None) como guarda em 3 lugares e
# jogava fora o histórico real nesse caso, sempre respondendo Ativo (bug
# real, achado em 04/08 via teste automatizado de view_alternar_pausado_
# agenda — o próprio botão de pausar ficava travado, nunca voltava a Ativo).
def status_manual_atual_do_produto(produto) -> str:
    ultimo = produto.historico_status_manual.first()
    return ultimo.status if ultimo else StatusManualAgenda.ATIVO


class HistoricoStatusManualAgenda(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='historico_status_manual')
    status = models.CharField(max_length=15, choices=StatusManualAgenda.choices)
    alterado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Histórico de Status Manual'
        verbose_name_plural = 'Históricos de Status Manual'
        # * [CORREÇÃO] → "-alterado_em" sozinho não é confiável: 2 registros
        #                criados muito próximos no tempo podem empatar (resolução
        #                do relógio do sistema), e sem desempate a ordem fica
        #                indefinida. "-id" garante que o criado por último sempre
        #                vence, mesmo empatando no timestamp.
        ordering = ['-alterado_em', '-id']

    def __str__(self):
        return f'{self.produto.sku} — {self.get_status_display()} em {self.alterado_em:%d/%m/%Y}'


class ParticipacaoAgenda(models.Model):
    produto = models.OneToOneField(Produto, on_delete=models.CASCADE, related_name='participacao_agenda')
    urgente = models.BooleanField(default=False)
    agendado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Participação na Agenda'
        verbose_name_plural = 'Participações na Agenda'

    def status_manual_atual(self):
        # Atalho de conveniência pra quem já tem a instância em mãos — nunca
        # duplica a regra, delega 100% pra status_manual_atual_do_produto().
        return status_manual_atual_do_produto(self.produto)

    def __str__(self):
        return f'{self.produto.sku} — {self.status_manual_atual()}'