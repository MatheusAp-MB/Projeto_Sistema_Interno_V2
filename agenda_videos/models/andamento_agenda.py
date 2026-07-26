# agenda_videos/models/andamento_agenda.py

# Função Objetivo: Representa o estado ATUAL de 1 produto na Agenda de Vídeos.
# Explicação em detalhe: 1 registro por Produto, que evolui com o tempo — quem guarda
# histórico é Postagem, não este model. fase_atual é sempre FK pra ConfiguracaoFase
# (nunca choices duplicado), confirmado com o usuário.

from django.db import models
from produtos.models import Produto
from .configuracao_fase import ConfiguracaoFase


class StatusManualAgenda(models.TextChoices):
    ATIVO = 'ativo', 'Ativo'
    PAUSADO = 'pausado', 'Pausado'
    DESCONTINUADO = 'descontinuado', 'Descontinuado'


class AndamentoAgenda(models.Model):
    produto = models.OneToOneField(
        Produto, on_delete=models.CASCADE, related_name='andamento_agenda')

    fase_atual = models.ForeignKey(
        ConfiguracaoFase, on_delete=models.PROTECT, related_name='produtos_na_fase')

    ocorrencia_atual = models.PositiveIntegerField(default=1)

    inicio_fase = models.DateField()
    fim_fase = models.DateField()

    status_manual = models.CharField(
        max_length=15, choices=StatusManualAgenda.choices, default=StatusManualAgenda.ATIVO)

    # * [EXPLICAÇÃO] → Estado terminal (24/07): quando a Fase Mensal termina, o produto sai
    #                  de vez das telas Diários/Semanal-Mensal/A Fazer e passa a aparecer só
    #                  na tela "Produtos Já Otimizados" (filtro simples, sem model novo).
    #                  fase_atual continua guardando a ÚLTIMA fase real (Mensal, na prática),
    #                  útil pra auditoria — nunca vira um valor artificial tipo "concluído".
    #                  Por decisão do usuário, é terminal por enquanto — reativação (voltar
    #                  o produto pra Agenda depois de concluído) fica pra pensar depois,
    #                  não existe ação nenhuma pra isso ainda.
    concluido = models.BooleanField(default=False)
    concluido_em = models.DateField(blank=True, null=True)

    # * [EXPLICAÇÃO] → "urgente" MUDOU DE LUGAR (25/07) — saiu daqui e foi pra
    #                  RoadmapAgenda. Motivo: qualquer produto pode ser marcado
    #                  como urgente (mesmo "Não Agendado"), e AndamentoAgenda só
    #                  existe pra quem já tem Agenda — não servia mais como dono
    #                  desse campo.

    # * [EXPLICAÇÃO] → Vencimento da ocorrência ATUAL (não da fase inteira) —
    #                  persistido de propósito, pra dar pro banco comparar/ordenar
    #                  por "atrasado" direto em SQL (Case/When), sem precisar rodar
    #                  nossa função de dia útil durante a query. Recalculado sempre
    #                  que ocorrencia_atual ou fase_atual mudam (view_agendar_produto,
    #                  view_executar_acao_ciclica).
    fim_ocorrencia_atual = models.DateField(blank=True, null=True)

    class Meta:
        verbose_name = 'Andamento na Agenda'
        verbose_name_plural = 'Andamentos na Agenda'

    def __str__(self):
        return f'{self.produto.sku} — {self.fase_atual.get_fase_display()}, ocorrência {self.ocorrencia_atual}'