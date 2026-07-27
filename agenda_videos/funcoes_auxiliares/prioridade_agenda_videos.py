# agenda_videos/funcoes_auxiliares/prioridade_agenda_videos.py

# Função Objetivo: Regra ÚNICA de prioridade/ordenação de fase, documentada num
# lugar só — usada em 2 contextos que, por motivo de performance, precisam de
# 2 implementações diferentes:
#   - SQL (Case/When) pra listar_produtos_agenda_filtrados (filtros_agenda_videos.py)
#     — pagina ~2000 produtos, não dá pra calcular em Python antes de paginar.
#   - Python puro pra listar_a_fazer_hoje (a_fazer_hoje.py) — já calcula em
#     Python por causa da janela de ocorrência, escala continua pequena
#     (dezenas de candidatos).
# NÃO dá pra virar 1 função só rodando nos 2 lugares (paradigmas diferentes),
# mas as 2 versões ficam aqui, lado a lado — qualquer mudança na regra
# precisa necessariamente mexer nas 2 juntas, sem risco de uma ficar escondida
# em outro arquivo (26/07, achado do pente fino).
#
# Regra de prioridade (6 níveis, cruza Urgente/Atrasado com "Sem vídeo"):
#   1. Urgente + Sem vídeo    2. Urgente
#   3. Atrasado + Sem vídeo   4. Atrasado
#   5. Sem vídeo              6. Resto
#
# Regra de ordenação de fase (grupo intermediário, não critério):
#   Diária → Semanal → Mensal → (sem fase real: Não Agendado/Pronto p/ Agendar)

from django.db.models import Case, When, Value, IntegerField
from agenda_videos.models import Fase

MAPA_ORDEM_FASE = {Fase.DIARIA: 1, Fase.SEMANAL: 2, Fase.MENSAL: 3}


# Função Objetivo: Annotation SQL de prioridade — usada por
# listar_produtos_agenda_filtrados. "hoje" decide o corte de Atrasado.
def construir_annotation_prioridade(hoje):
    return Case(
        When(roadmap_agenda__urgente=True, roadmap_agenda__tem_video_reprovado=True, then=Value(1)),
        When(roadmap_agenda__urgente=True, then=Value(2)),
        When(
            andamento_agenda__isnull=False,
            andamento_agenda__concluido=False,
            andamento_agenda__fim_ocorrencia_atual__lt=hoje,
            roadmap_agenda__tem_video_reprovado=True,
            then=Value(3),
        ),
        When(
            andamento_agenda__isnull=False,
            andamento_agenda__concluido=False,
            andamento_agenda__fim_ocorrencia_atual__lt=hoje,
            then=Value(4),
        ),
        When(roadmap_agenda__tem_video_reprovado=True, then=Value(5)),
        default=Value(6),
        output_field=IntegerField(),
    )


# Função Objetivo: Annotation SQL de ordenação de fase — usada por
# listar_produtos_agenda_filtrados.
def construir_annotation_ordenacao_fase():
    return Case(
        When(andamento_agenda__fase_atual__fase=Fase.DIARIA, then=Value(1)),
        When(andamento_agenda__fase_atual__fase=Fase.SEMANAL, then=Value(2)),
        When(andamento_agenda__fase_atual__fase=Fase.MENSAL, then=Value(3)),
        default=Value(4),
        output_field=IntegerField(),
    )


# Função Objetivo: Versão Python da MESMA regra de prioridade acima — usada
# por listar_a_fazer_hoje. MUDOU ALGO ALI EM CIMA? Muda aqui também.
def calcular_prioridade_produto(produto):
    roadmap_agenda = getattr(produto, 'roadmap_agenda', None)
    urgente = roadmap_agenda is not None and roadmap_agenda.urgente
    sem_video = roadmap_agenda is not None and roadmap_agenda.tem_video_reprovado
    atrasado = produto.a_fazer_hoje_atrasado

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


# Função Objetivo: Versão Python da MESMA regra de ordenação de fase acima —
# usada por listar_a_fazer_hoje.
def calcular_ordem_fase_produto(produto):
    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento is None:
        return 4
    return MAPA_ORDEM_FASE.get(andamento.fase_atual.fase, 4)