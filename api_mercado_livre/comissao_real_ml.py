# api_mercado_livre/comissao_real_ml.py

# Função Objetivo: Contexto "Comissão Real de venda" — sabe tudo que o
# ClienteApiMercadoLivre (transporte puro) não deve saber: os 2
# endpoints (GET /items/{mlb} e GET /sites/{SITE_ID}/listing_prices,
# validados dígito a dígito em 24/09/2026 contra o Simulador de Custos
# real do ML) e o formato de cada resposta. Compõe um
# ClienteApiMercadoLivre (nunca herda dele). O cache por execução
# (cache_item_info) continua no Orquestrador. Ver "Padrao de Robustez
# para Clientes de API Externa" no vault. Peça 4 da reforma estrutural
# (27/09/2026) — extraído de
# integracao_mercado_livre/servicos/buscar_comissao_real_ml.py, mesma
# lógica, byte a byte.

from decimal import Decimal, InvalidOperation

from .core.estrutura_api.cliente_api import ErroAPI

SITE_ID = 'MLB'  # as 2 empresas (MB/SV) operam só no site Brasil


class ComissaoRealML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: Busca category_id, listing_type_id e price ATUAIS direto de /items/{mlb}.
    def buscar_item_info(self, mlb: str, pasta_logs) -> dict:
        resposta = self._cliente.chamar(
            "GET", f"/items/{mlb}",
            pasta_logs=pasta_logs, nome_log="buscar_comissao_real_ml",
        )
        corpo = resposta.json()
        return {
            "category_id": corpo["category_id"],
            "listing_type_id": corpo["listing_type_id"],
            "price": Decimal(str(corpo["price"])),
        }

    # Função Objetivo: GET /sites/MLB/listing_prices — comissão estimada pré-venda.
    def buscar_listing_prices(self, price: Decimal, category_id: str, listing_type_id: str, pasta_logs) -> dict:
        resposta = self._cliente.chamar(
            "GET", f"/sites/{SITE_ID}/listing_prices",
            pasta_logs=pasta_logs,
            params={"price": str(price), "category_id": category_id, "listing_type_id": listing_type_id},
            nome_log="buscar_comissao_real_ml",
        )
        corpo = resposta.json()
        if isinstance(corpo, list):
            if not corpo:
                raise ErroAPI(f"listing_prices não retornou nenhum resultado pra price={price}, "
                               f"category_id={category_id}, listing_type_id={listing_type_id}")
            corpo = corpo[0]
        if "sale_fee_amount" not in corpo:
            raise ErroAPI(f"listing_prices sem sale_fee_amount — resposta: {corpo}")

        detalhes = corpo.get("sale_fee_details") or {}
        try:
            sale_fee_amount = Decimal(str(corpo["sale_fee_amount"]))
        except InvalidOperation:
            raise ErroAPI(f"sale_fee_amount inválido — resposta: {corpo}")

        percentage_fee = detalhes.get("percentage_fee")
        return {
            "sale_fee_amount": sale_fee_amount,
            "percentage_fee": Decimal(str(percentage_fee)) if percentage_fee is not None else None,
        }