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


class MlbsML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: Varre 1 combinação (status/logistic_type/
    # listing_type_id/catalog_listing) até o fim, seguindo scroll_id —
    # não assume tamanho de página fixo, só para quando a página vier
    # vazia ou sem scroll_id novo.
    def varrer(self, varrida: dict, user_id: str, pasta_logs) -> list[dict]:
        mlbs_encontrados = []
        scroll_id = None

        while True:
            params = {
                "search_type": "scan",
                "status": varrida["status"],
                "logistic_type": varrida["logistic_type"],
                "listing_type_id": varrida["listing_type_id"],
                "catalog_listing": varrida["catalog_listing"],
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
                mlbs_encontrados.append({
                    "mlb": mlb,
                    "status": varrida["status"],
                    "logistica": varrida["logistic_type"],
                    "tipo": varrida["listing_type_id"],
                    "catalogo": varrida["catalog_listing"],
                })

            scroll_id = dados.get("scroll_id")
            if not scroll_id:
                break

        return mlbs_encontrados