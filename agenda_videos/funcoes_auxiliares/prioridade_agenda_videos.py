# agenda_videos/funcoes_auxiliares/prioridade_agenda_videos.py

# Função Objetivo: Regra ÚNICA de prioridade/ordenação de fase — 2 versões
# lado a lado (SQL pra listagem paginada, Python pra "A Fazer Hoje"). Qualquer
# mudança de regra mexe nas 2 juntas, sem exceção.
#
# Regra de prioridade (6 níveis, cruza Urgente/Atrasado com "Sem vídeo"):
#   1. Urgente + Sem vídeo    2. Urgente
#   3. Atrasado + Sem vídeo   4. Atrasado
#   5. Sem vídeo              6. Resto
#
# Regra de ordenação de fase: Simples → Vídeo Mensal → Vídeo Trimestral.
#
# Reestruturação completa (30/07) — "atrasado" agora vem direto do cache
# (IndicadoresAgendaProduto.ciclo_atual_atrasado), não precisa mais de data
# de referência pra calcular na hora — simplifica a versão SQL.

from django.db.models import Case, When, Value, IntegerField
from agenda_videos.models import Fase

MAPA_ORDEM_FASE = {Fase.SIMPLES: 1, Fase.VIDEO_MENSAL: 2, Fase.VIDEO_TRIMESTRAL: 3}


def construir_annotation_prioridade():
    return Case(
        When(participacao_agenda__urgente=True, indicadores_agenda__tem_video_reprovado=True, then=Value(1)),
        When(participacao_agenda__urgente=True, then=Value(2)),
        When(indicadores_agenda__ciclo_atual_atrasado=True, indicadores_agenda__tem_video_reprovado=True, then=Value(3)),
        When(indicadores_agenda__ciclo_atual_atrasado=True, then=Value(4)),
        When(indicadores_agenda__tem_video_reprovado=True, then=Value(5)),
        default=Value(6),
        output_field=IntegerField(),
    )


def construir_annotation_ordenacao_fase():
    return Case(
        When(indicadores_agenda__fase_atual=Fase.SIMPLES, then=Value(1)),
        When(indicadores_agenda__fase_atual=Fase.VIDEO_MENSAL, then=Value(2)),
        When(indicadores_agenda__fase_atual=Fase.VIDEO_TRIMESTRAL, then=Value(3)),
        default=Value(4),
        output_field=IntegerField(),
    )


def calcular_prioridade_produto(produto):
    urgente = getattr(produto, 'urgente', False)
    sem_video = getattr(produto, 'sem_video', False)
    atrasado = getattr(produto, 'a_fazer_hoje_atrasado', False)

    if urgente and sem_video:
        return 1
    if urgente:
        return 2
    if atrasado and sem_video:
        return 3
    if atrasado:
        return 4
    if sem_video:
        return 5
    return 6


def calcular_ordem_fase_produto(produto):
    fase = getattr(produto, 'a_fazer_hoje_fase', None)
    return MAPA_ORDEM_FASE.get(fase, 4)