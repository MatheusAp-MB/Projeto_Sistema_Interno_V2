# api_mercado_livre/dados_sku_completo_ml.py

# Função Objetivo: Contexto "Performance e Price to Win por MLB" — sabe
# tudo que o ClienteApiMercadoLivre (transporte puro) não deve saber:
# os 2 endpoints (GET /user-product/{mlbu}/performance e
# GET /items/{mlb}/price_to_win) e o formato de "pacote" da resposta
# (chamado/http/erro/dados). Compõe um ClienteApiMercadoLivre (nunca
# herda dele). O cache por execução continua no Orquestrador (é
# controle de "evitar chamada repetida nesse run", não conhecimento de
# API). Ver "Padrao de Robustez para Clientes de API Externa" no vault.
# Peça 4 da reforma estrutural (27/09/2026) — extraído de
# integracao_mercado_livre/servicos/buscar_dados_sku_completo.py, mesma
# lógica, byte a byte.

from .core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI


class DadosSkuCompletoML:
    def __init__(self, cliente):
        self._cliente = cliente

    def buscar_performance(self, mlbu, pasta_logs) -> dict:
        try:
            r = self._cliente.chamar(
                "GET", f"/user-product/{mlbu}/performance",
                pasta_logs=pasta_logs, nome_log="buscar_dados_sku_completo",
            )
            return {"chamado": True, "http": r.status_code, "erro": None, "dados": r.json()}
        except (ErroAPI, ErroAutenticacaoAPI) as e:
            return {"chamado": True, "http": None, "erro": str(e), "dados": None}

    def buscar_price_to_win(self, mlb, pasta_logs) -> dict:
        try:
            r = self._cliente.chamar(
                "GET", f"/items/{mlb}/price_to_win",
                pasta_logs=pasta_logs, params={"version": "v2"},
                nome_log="buscar_dados_sku_completo",
            )
            return {"chamado": True, "http": r.status_code, "erro": None, "dados": r.json()}
        except (ErroAPI, ErroAutenticacaoAPI) as e:
            return {"chamado": True, "http": None, "erro": str(e), "dados": None}