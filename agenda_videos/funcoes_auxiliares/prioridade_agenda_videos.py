# agenda_videos/funcoes_auxiliares/prioridade_agenda_videos.py

# Função Objetivo: Regra ÚNICA de prioridade/ordenação de fase — usada por
# toda listagem da Agenda de Vídeos (paginada e "A Fazer Hoje"), sempre via
# annotation SQL. Fonte única, nunca reimplementada em Python.
#
# Regra de prioridade (6 níveis, cruza Urgente/Atrasado com "Sem vídeo"):
#   1. Urgente + Sem vídeo    2. Urgente
#   3. Atrasado + Sem vídeo   4. Atrasado
#   5. Sem vídeo              6. Resto
# Regra de ordenação de fase: Simples → Vídeo Mensal → Vídeo Trimestral.
#
# Reestruturação completa (30/07) — a versão Python (calcular_prioridade_produto/
# calcular_ordem_fase_produto) saiu: só existia porque "A Fazer Hoje" usava um
# loop manual, não porque a regra fosse diferente.

from django.db.models import Case, When, Value, IntegerField, Expression
from agenda_videos.models import Fase


def construir_annotation_prioridade() -> Expression:
    return Case(
        When(participacao_agenda__urgente=True, indicadores_agenda__tem_video_reprovado=True, then=Value(1)),
        When(participacao_agenda__urgente=True, then=Value(2)),
        When(indicadores_agenda__ciclo_atual_atrasado=True, indicadores_agenda__tem_video_reprovado=True, then=Value(3)),
        When(indicadores_agenda__ciclo_atual_atrasado=True, then=Value(4)),
        When(indicadores_agenda__tem_video_reprovado=True, then=Value(5)),
        default=Value(6),
        output_field=IntegerField(),
    )


def construir_annotation_ordenacao_fase() -> Expression:
    return Case(
        When(indicadores_agenda__fase_atual=Fase.SIMPLES, then=Value(1)),
        When(indicadores_agenda__fase_atual=Fase.VIDEO_MENSAL, then=Value(2)),
        When(indicadores_agenda__fase_atual=Fase.VIDEO_TRIMESTRAL, then=Value(3)),
        default=Value(4),
        output_field=IntegerField(),
    )