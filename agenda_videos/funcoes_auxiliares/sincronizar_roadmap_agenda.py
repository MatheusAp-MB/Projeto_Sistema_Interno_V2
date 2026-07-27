# agenda_videos/funcoes_auxiliares/sincronizar_roadmap_agenda.py

# ⚠️ ATENÇÃO — LEIA ANTES DE ESCREVER NO BANCO POR FORA DESTE MÓDULO (automação
# futura, ou você daqui a 3 meses): RoadmapAgenda.estagio_atual e
# .tem_video_reprovado são CÓPIAS calculadas, nunca a fonte real do dado.
# Qualquer escrita direta em Postagem, PreparacaoVideoFase,
# ProgressoProducaoVideo ou AndamentoAgenda — inclusive fora do sistema, tipo
# uma automação que poste no ML e grave direto — PRECISA terminar chamando
# sincronizar_roadmap_agenda_produto(produto), senão esses 2 campos ficam
# desatualizados silenciosamente. Sem exceção.

from agenda_videos.models import RoadmapAgenda, EstagioAgenda
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_chave_atual, montar_preparacoes_por_fase

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


# Função Objetivo: "Qualquer variação do produto reprovada em UP_HAS_SHORTS?"
# Explicação em detalhe: 1 query só (não é ao vivo dentro de listagem/ordenação —
# só roda aqui, nos pontos de sincronização, nunca a cada carregamento de tela).
def _verificar_video_reprovado(produto):
    from mercado_livre.models import QualidadeAnuncioCriterio
    return QualidadeAnuncioCriterio.objects.filter(
        qualidade__variacao__produto=produto,
        criterio__rule_key='UP_HAS_SHORTS',
        status='nao_aprovado',
    ).exists()


def sincronizar_roadmap_agenda_produto(produto):
    progresso = getattr(produto, 'progresso_producao_video', None)
    andamento = getattr(produto, 'andamento_agenda', None)
    preparacoes_por_fase = montar_preparacoes_por_fase(produto)

    chave_atual = calcular_chave_atual(progresso, preparacoes_por_fase, andamento)
    estagio = colapsar_chave_em_estagio(chave_atual)
    tem_video_reprovado = _verificar_video_reprovado(produto)

    roadmap_agenda, _ = RoadmapAgenda.objects.update_or_create(
        produto=produto,
        defaults={'estagio_atual': estagio, 'tem_video_reprovado': tem_video_reprovado},
    )
    return roadmap_agenda