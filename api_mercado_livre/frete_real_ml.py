# api_mercado_livre/frete_real_ml.py

# Função Objetivo: Contexto "Frete Real de um anúncio" — sabe tudo que o
# ClienteApiMercadoLivre (transporte puro) não deve saber: qual endpoint
# chamar (GET /users/{user_id}/shipping_options/free, validado em
# 21/09/2026) e como interpretar a resposta. Compõe um
# ClienteApiMercadoLivre (nunca herda dele) e devolve o dado já extraído
# — quem chama decide o que fazer com ele (persistir, exibir, etc.),
# esta classe não sabe de Django nem de disco. Ver "Padrao de Robustez
# para Clientes de API Externa" no vault. Peça 3 da reforma estrutural
# (27/09/2026) — extraído de integracao_mercado_livre/servicos/
# buscar_frete_real_ml.py, mesma lógica, byte a byte.

from decimal import Decimal, InvalidOperation


class FreteRealML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: Extrai (valor, detalhamento) da resposta de shipping_options/free.
    # Explicação em detalhe: coverage.all_country.list_cost é o campo validado na investigação —
    # bate exatamente com o Resumo de Custos real do anúncio. detalhamento (22/09) junta o resto
    # do que a API devolve nesse mesmo nível — billable_weight e o bloco discount inteiro
    # (type/rate/promoted_amount) — pra gravar como apoio/auditoria, sem virar campo oficial.
    # ATENÇÃO: billable_weight/rate/promoted_amount ainda não foram conferidos byte-a-byte
    # contra uma resposta real (só list_cost e discount.type foram validados na investigação
    # original) — a suposição aqui é que ficam no mesmo nível dentro de coverage.all_country.
    # Vale conferir contra 1 log real (integracao_mercado_livre/logs/.../buscar_frete_real_ml*)
    # antes de rodar em massa de novo.
    def _extrair(self, resposta_json: dict):
        coverage = resposta_json.get('coverage', {}) or {}
        all_country = coverage.get('all_country', {}) or {}
        list_cost = all_country.get('list_cost')
        billable_weight = all_country.get('billable_weight')
        discount = all_country.get('discount', {}) or {}

        detalhamento = {
            "billable_weight": billable_weight,
            "discount_type": discount.get('type'),
            "discount_rate": discount.get('rate'),
            "discount_promoted_amount": discount.get('promoted_amount'),
        }

        if list_cost is None:
            return None, detalhamento

        try:
            return Decimal(str(list_cost)), detalhamento
        except InvalidOperation:
            return None, detalhamento

    def buscar(self, mlb, user_id, pasta_logs):
        resposta = self._cliente.chamar(
            "GET", f"/users/{user_id}/shipping_options/free",
            pasta_logs=pasta_logs,
            params={"item_id": mlb, "verbose": "true"},
            nome_log="buscar_frete_real_ml",
        )
        return self._extrair(resposta.json())