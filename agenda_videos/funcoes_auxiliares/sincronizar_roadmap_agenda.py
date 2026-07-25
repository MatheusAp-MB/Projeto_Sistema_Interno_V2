# agenda_videos/funcoes_auxiliares/sincronizar_roadmap_agenda.py

# Função Objetivo: Calcula e persiste o estágio agrupado (RoadmapAgenda) de 1 produto.
# Explicação em detalhe: reaproveita calcular_chave_atual (mesma função que decide o
# ponto ativo do roadmap visual) — nunca duplica essa decisão em 2 lugares.

from agenda_videos.models import RoadmapAgenda, EstagioAgenda
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_chave_atual

CHAVES_PREPARACAO = {'simples', 'base', 'roteiros', 'completos'}


# Função Objetivo: Colapsa a chave de 9 posições do roadmap visual no estágio de 6 do filtro.
def colapsar_chave_em_estagio(chave):
    if chave in CHAVES_PREPARACAO:
        return EstagioAgenda.NAO_AGENDADO
    return chave  # pronto_agendamento/diaria/semanal/mensal/otimizado já batem 1-pra-1


# Função Objetivo: Sincroniza o RoadmapAgenda de 1 produto — chamado sempre que o
# roadmap desse produto muda (ex: confirmar um ponto no modal). "Recálculo direto",
# 1 dos 2 mecanismos de sincronização (o outro é a etapa de pipeline, em lote).
def sincronizar_roadmap_agenda_produto(produto):
    progresso = getattr(produto, 'progresso_producao_video', None)
    andamento = getattr(produto, 'andamento_agenda', None)
    chave_atual = calcular_chave_atual(progresso, andamento)
    estagio = colapsar_chave_em_estagio(chave_atual)

    roadmap_agenda, _ = RoadmapAgenda.objects.update_or_create(
        produto=produto, defaults={'estagio_atual': estagio},
    )
    return roadmap_agenda