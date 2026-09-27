# api_mercado_livre/categorias_ml.py

# Função Objetivo: Contexto "Dump de categorias" — sabe tudo que o
# ClienteApiMercadoLivre (transporte puro) não deve saber: o endpoint
# (GET /sites/MLB/categories/all) e os 2 headers de controle de versão
# que a API devolve (X-Content-Created / X-Content-MD5). Compõe um
# ClienteApiMercadoLivre (nunca herda dele) e devolve o dump cru + os 2
# headers — a comparação de MD5 e a gravação em banco (schema nosso,
# não da API) continuam no Orquestrador. Ver "Padrao de Robustez para
# Clientes de API Externa" no vault. Peça 4 da reforma estrutural
# (27/09/2026) — extraído de
# integracao_mercado_livre/servicos/sincronizar_categorias_ml.py, mesma
# lógica, byte a byte.


class CategoriasML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: Baixa o dump completo de categorias. Devolve o
    # corpo já decodificado (dict category_id -> detalhe) junto com os 2
    # headers de versão, pra quem chama decidir se vale a pena reprocessar.
    def baixar_dump(self, pasta_logs) -> dict:
        resposta = self._cliente.chamar(
            "GET", "/sites/MLB/categories/all",
            pasta_logs=pasta_logs, nome_log="sincronizar_categorias_ml",
        )
        return {
            "dados": resposta.json(),
            "md5": resposta.headers.get("X-Content-MD5"),
            "gerado_em": resposta.headers.get("X-Content-Created"),
        }