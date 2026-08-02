# agenda_videos/funcoes_auxiliares/sincronizar_roadmap_agenda.py

# ⚠️ ATENÇÃO — LEIA ANTES DE ESCREVER NO BANCO POR FORA DESTE MÓDULO: 
# IndicadoresAgendaProduto é CÓPIA calculada, nunca a fonte real do dado.
# Qualquer escrita direta em CicloVideo, ConfiguracaoFase ou ParticipacaoAgenda
# — inclusive fora do sistema, tipo uma automação que poste no ML e grave direto
# — PRECISA terminar chamando sincronizar_indicadores_agenda_produto(produto),
# senão esse cache fica desatualizado silenciosamente. Sem exceção.

from dataclasses import asdict, dataclass

from produtos.models import Produto
from agenda_videos.models import CicloVideo, IndicadoresAgendaProduto, StatusManualAgenda


@dataclass(frozen=True)
class IndicadoresCalculados:
    etapa_atual: str
    fase_atual: str
    ciclo_atual_atrasado: bool
    tem_video_reprovado: bool
    status_manual: str


# Função Objetivo: "Qualquer variação do produto reprovada em UP_HAS_SHORTS?"
# Explicação em detalhe: 1 query só (não é ao vivo dentro de listagem/ordenação —
# só roda aqui, nos pontos de sincronização, nunca a cada carregamento de tela).
def _verificar_video_reprovado(produto: Produto) -> bool:
    from mercado_livre.models import QualidadeAnuncioCriterio
    return QualidadeAnuncioCriterio.objects.filter(
        qualidade__variacao__produto=produto,
        criterio__rule_key='UP_HAS_SHORTS',
        status='nao_aprovado',
    ).exists()


# Função Objetivo: Calcula os 4 indicadores de 1 produto a partir das fontes
# reais. Não toca banco — só devolve valores, pra quem chama decidir
# criar/atualizar (permite reaproveitar isso tanto 1 produto por vez quanto
# em lote, sem duplicar a regra em 2 lugares).
def calcular_indicadores(produto: Produto, ciclo_mais_recente: CicloVideo | None) -> IndicadoresCalculados:
    if ciclo_mais_recente is None:
        etapa, atrasado = 'nao_agendado', False
    else:
        etapa = ciclo_mais_recente.etapa_atual()
        atrasado = ciclo_mais_recente.esta_atrasado()

    participacao = getattr(produto, 'participacao_agenda', None)
    status_manual = participacao.status_manual_atual() if participacao else StatusManualAgenda.ATIVO

    return IndicadoresCalculados(
        etapa_atual=etapa,
        fase_atual=ciclo_mais_recente.fase if ciclo_mais_recente else '',
        ciclo_atual_atrasado=atrasado,
        tem_video_reprovado=_verificar_video_reprovado(produto),
        status_manual=status_manual,
    )


def sincronizar_indicadores_agenda_produto(produto: Produto) -> IndicadoresAgendaProduto:
    ciclo_mais_recente = produto.ciclos_video.first()  # já ordenado por -criado_em (Meta.ordering)
    valores = calcular_indicadores(produto, ciclo_mais_recente)
    indicadores, _ = IndicadoresAgendaProduto.objects.update_or_create(produto=produto, defaults=asdict(valores))
    return indicadores