# api_mercado_livre/full_ml.py

# Função Objetivo: Contexto "Full (Fulfillment) de 1 código" — sabe tudo que o
# ClienteApiMercadoLivre (transporte puro) não deve saber: os 2 endpoints
#   GET /marketplace/fbm/user-products/{user_product_id}/replenishment?country=BR
#       (doc "Planejamento de reposição": os dados da tela "Planejamento de
#       envios" — vendas, urgência, mínimo, sugestão, Estrela, estoque antigo)
#   GET /inventories/{inventory_id}/stock/fulfillment
#       (doc "Envios Fulfillment": estoque apto e não apto, com o motivo)
# e o formato de "pacote" da resposta (endpoint/http/erro/dados). Compõe um
# ClienteApiMercadoLivre (nunca herda dele). Só leitura (GET).
#
# REGRA DO MATHEUS: NUNCA chamar a API sozinho. Estes métodos só podem ser
# chamados pelo botão "Consultar no Mercado Livre" da tela do Full — nunca por
# tela aberta, rotina agendada ou importação.

from dataclasses import dataclass

from api_mercado_livre.core.estrutura_api.excecoes import ErroAPI, ErroAutenticacaoAPI

NOME_LOG = "full_ml"


@dataclass
class PacoteFull:
    """Pacote de retorno de 1 chamada — o formato de resposta que o Contexto conhece.
    O 206 (resposta parcial) chega aqui como http=206 e o header X-Content-Missing diz
    quais blocos ficaram faltando. Erro de resposta do ML (404, 403...) NÃO levanta
    exceção: vira erro="texto" e dados=None, para a tela mostrar o que aconteceu."""
    endpoint: str
    params: dict | None
    http: int | None
    x_content_missing: str | None
    erro: str | None
    dados: dict | None


class FullML:
    def __init__(self, cliente):
        self._cliente = cliente

    def buscar_reposicao(self, user_product_id, pasta_logs) -> PacoteFull:
        return self._buscar(
            f"/marketplace/fbm/user-products/{user_product_id}/replenishment",
            {"country": "BR"}, pasta_logs,
        )

    def buscar_estoque(self, inventory_id, pasta_logs) -> PacoteFull:
        return self._buscar(f"/inventories/{inventory_id}/stock/fulfillment", None, pasta_logs)

    # Função Objetivo: 1 GET. Só a autenticação recusada (401) é repassada (levanta
    # ErroAutenticacaoAPI): nenhuma chamada seguinte funcionaria, quem chama decide.
    def _buscar(self, endpoint, params, pasta_logs) -> PacoteFull:
        try:
            resposta = self._cliente.chamar(
                "GET", endpoint, pasta_logs=pasta_logs, params=params, nome_log=NOME_LOG,
            )
        except ErroAutenticacaoAPI:
            raise
        except ErroAPI as erro:
            return PacoteFull(endpoint=endpoint, params=params, http=None,
                              x_content_missing=None, erro=str(erro), dados=None)

        try:
            dados = resposta.json()
            erro = None
        except ValueError:
            dados = None
            erro = f"A resposta não veio em JSON: {resposta.text[:300]}"

        return PacoteFull(
            endpoint=endpoint, params=params, http=resposta.status_code,
            x_content_missing=resposta.headers.get("X-Content-Missing"),
            erro=erro, dados=dados,
        )
