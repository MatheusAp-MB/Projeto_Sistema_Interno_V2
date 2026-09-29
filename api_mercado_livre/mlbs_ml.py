# api_mercado_livre/mlbs_ml.py

# Função Objetivo: Contexto "Varredura de MLBs por combinação" — sabe
# tudo que o ClienteApiMercadoLivre (transporte puro) não deve saber:
# qual endpoint chamar (GET /users/{user_id}/items/search,
# search_type=scan) e como paginar via scroll_id. Compõe um
# ClienteApiMercadoLivre (nunca herda dele) e devolve a lista de MLBs já
# achatada — quem chama decide o que fazer com ela (salvar em JSON,
# etc.), esta classe não sabe de arquivo nem de disco. Ver "Padrao de
# Robustez para Clientes de API Externa" no vault. Peça 4 da reforma
# estrutural (27/09/2026) — extraído de
# integracao_mercado_livre/servicos/buscar_mlbs.py::buscar_mlbs_varrida,
# mesma lógica, byte a byte.
#
# Otimização e POO (29/09/2026, Etapa 2 de "otimizar e paralelizar todas
# as etapas que envolvem integração com o ML"): os 4 conjuntos de string
# solta (STATUS_LIST/LOGISTICA_LIST/TIPO_LIST/CATALOGO_LIST, antes só em
# buscar_mlbs.py) viraram Enum aqui — Contexto é quem sabe "os valores
# que este endpoint aceita", igual já registrado em "Modelagem de Objeto
# e Encapsulamento" no vault (Enum pra valor fixo repetido, nunca string
# solta). varrer() passou a receber/devolver Varrida/MlbEncontrado
# (dataclass) em vez de dict cru — mesmo padrão de
# ResultadoComissaoVariacao em buscar_comissao_real_ml.py. Varrida e
# MlbEncontrado moram aqui (Contexto), não no Orquestrador
# (buscar_mlbs.py) — decisão de camada: são "o que este endpoint aceita
# como entrada" e "o formato da resposta", responsabilidade do Contexto
# (ver "Camadas do Cliente Mercado Livre" no vault); ResultadoVarrida/
# RelatorioBuscaMlbs (contagem/tempo de 1 rodada) ficam no Orquestrador,
# que é quem sabe de execução, não de endpoint.

from dataclasses import dataclass
from enum import Enum


class StatusAnuncio(str, Enum):
    """Valores aceitos pelo parâmetro status de GET /users/{user_id}/items/search —
    mesma ordem antes usada em STATUS_LIST (buscar_mlbs.py), preservada porque define
    o agrupamento visual por status no console."""
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    UNDER_REVIEW = "under_review"
    PAYMENT_REQUIRED = "payment_required"
    NOT_YET_ACTIVE = "not_yet_active"


class TipoLogistica(str, Enum):
    """Valores aceitos pelo parâmetro logistic_type — mesma ordem antes usada em
    LOGISTICA_LIST (buscar_mlbs.py)."""
    FULFILLMENT = "fulfillment"
    CROSS_DOCKING = "cross_docking"
    XD_DROP_OFF = "xd_drop_off"
    SELF_SERVICE = "self_service"
    NOT_SPECIFIED = "not_specified"
    DROP_OFF = "drop_off"
    CUSTOM = "custom"


class TipoAnuncioML(str, Enum):
    """Valores aceitos pelo parâmetro listing_type_id — mesma ordem antes usada em
    TIPO_LIST (buscar_mlbs.py)."""
    GOLD_PRO = "gold_pro"
    GOLD_SPECIAL = "gold_special"


class CatalogoListing(str, Enum):
    """Valores aceitos pelo parâmetro catalog_listing — mesma ordem antes usada em
    CATALOGO_LIST (buscar_mlbs.py). Continua string "true"/"false" (não bool) porque é
    literalmente o que a API espera no query param — comportamento original preservado."""
    SIM = "true"
    NAO = "false"


@dataclass(frozen=True)
class Varrida:
    """1 combinação de filtros pra varrer via GET /users/{user_id}/items/search
    (search_type=scan) — "objeto de processo/domínio" (ver "Modelagem de Objeto e
    Encapsulamento" no vault), frozen porque representa uma consulta já definida que não
    muda depois de criada (mesmo espírito de uma janela de data já calculada)."""
    status: StatusAnuncio
    logistic_type: TipoLogistica
    listing_type_id: TipoAnuncioML
    catalog_listing: CatalogoListing

    @property
    def label(self) -> str:
        """Rótulo de exibição — única responsável por montar esse texto, quem consome
        (o Orquestrador) nunca remonta por fora."""
        return f"{self.logistic_type.value} | {self.listing_type_id.value} | cat:{self.catalog_listing.value}"


@dataclass
class MlbEncontrado:
    """1 MLB devolvido por 1 varrida — objeto de processo/domínio, nunca salvo no banco
    (só serializado pro lista_mlbs.json de saída)."""
    mlb: str
    status: StatusAnuncio
    logistica: TipoLogistica
    tipo: TipoAnuncioML
    catalogo: CatalogoListing


class MlbsML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: Varre 1 combinação (status/logistic_type/
    # listing_type_id/catalog_listing) até o fim, seguindo scroll_id —
    # não assume tamanho de página fixo, só para quando a página vier
    # vazia ou sem scroll_id novo.
    def varrer(self, varrida: Varrida, user_id: str, pasta_logs) -> list[MlbEncontrado]:
        mlbs_encontrados = []
        scroll_id = None

        while True:
            params = {
                "search_type": "scan",
                "status": varrida.status.value,
                "logistic_type": varrida.logistic_type.value,
                "listing_type_id": varrida.listing_type_id.value,
                "catalog_listing": varrida.catalog_listing.value,
            }
            if scroll_id:
                params["scroll_id"] = scroll_id

            resposta = self._cliente.chamar(
                "GET", f"/users/{user_id}/items/search",
                pasta_logs=pasta_logs, params=params, nome_log="buscar_mlbs",
            )
            dados = resposta.json()
            resultados = dados.get("results", [])

            if not resultados:
                break

            for mlb in resultados:
                mlbs_encontrados.append(MlbEncontrado(
                    mlb=mlb,
                    status=varrida.status,
                    logistica=varrida.logistic_type,
                    tipo=varrida.listing_type_id,
                    catalogo=varrida.catalog_listing,
                ))

            scroll_id = dados.get("scroll_id")
            if not scroll_id:
                break

        return mlbs_encontrados