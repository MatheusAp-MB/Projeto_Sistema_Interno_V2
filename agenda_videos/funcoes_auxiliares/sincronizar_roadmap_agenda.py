# agenda_videos/funcoes_auxiliares/sincronizar_roadmap_agenda.py

from agenda_videos.models import RoadmapAgenda, EstagioAgenda
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_chave_atual

# * [EXPLICAÇÃO] → Colapsa os 13 pontos do roadmap visual nos 6 estágios do filtro.
#                  roteiros/completos por fase colapsam na fase CORRESPONDENTE (o
#                  produto já tem AndamentoAgenda apontando pra ela, não é mais
#                  "não agendado") — só simples/base/roteiros_diaria/completos_diaria
#                  (antes de ter AndamentoAgenda) colapsam em nao_agendado.
MAPA_COLAPSO = {
    'simples': EstagioAgenda.NAO_AGENDADO,
    'base': EstagioAgenda.NAO_AGENDADO,
    'roteiros_diaria': EstagioAgenda.NAO_AGENDADO,
    'completos_diaria': EstagioAgenda.NAO_AGENDADO,
    'pronto_agendamento': EstagioAgenda.PRONTO_AGENDAMENTO,
    'diaria': EstagioAgenda.DIARIA,
    'roteiros_semanal': EstagioAgenda.SEMANAL,
    'completos_semanal': EstagioAgenda.SEMANAL,
    'semanal': EstagioAgenda.SEMANAL,
    'roteiros_mensal': EstagioAgenda.MENSAL,
    'completos_mensal': EstagioAgenda.MENSAL,
    'mensal': EstagioAgenda.MENSAL,
    'otimizado': EstagioAgenda.OTIMIZADO,
}


def colapsar_chave_em_estagio(chave):
    return MAPA_COLAPSO[chave]


def _montar_preparacoes_por_fase(produto):
    return {p.fase: p for p in produto.preparacoes_video.all()}


def sincronizar_roadmap_agenda_produto(produto):
    progresso = getattr(produto, 'progresso_producao_video', None)
    andamento = getattr(produto, 'andamento_agenda', None)
    preparacoes_por_fase = _montar_preparacoes_por_fase(produto)

    chave_atual = calcular_chave_atual(progresso, preparacoes_por_fase, andamento)
    estagio = colapsar_chave_em_estagio(chave_atual)

    roadmap_agenda, _ = RoadmapAgenda.objects.update_or_create(
        produto=produto, defaults={'estagio_atual': estagio},
    )
    return roadmap_agenda