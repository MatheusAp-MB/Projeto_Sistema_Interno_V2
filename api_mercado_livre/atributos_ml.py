# api_mercado_livre/atributos_ml.py

# Função Objetivo: Contexto "Características (atributos)" — sabe tudo que o
# ClienteApiMercadoLivre (transporte puro) não deve saber sobre este
# domínio: quais endpoints chamar e como montar a resposta.
#   1) O que a CATEGORIA pede no card "Características principais":
#      grupo MAIN de GET /categories/{id}/technical_specs/input, menos os
#      atributos com a etiqueta allow_variations; mais a definição de cada
#      um (tipo, limite, opções, unidades) em GET /categories/{id}/attributes.
#   2) Os valores que o ANÚNCIO tem hoje: GET /items/{mlb} com
#      include_internal_attributes=true (o multiget /items?ids= NÃO foi
#      testado com esse parâmetro — por isso a leitura é 1 chamada por MLB).
# Compõe um ClienteApiMercadoLivre (nunca herda dele) e devolve o dado como
# a API mandou — quem chama decide como e quando gravar; esta classe não
# sabe de banco nem de disco. IMPORTANTE: nada aqui roda sozinho — só quem
# é disparado por um botão da tela de Características dos anúncios chama
# estes métodos (regra do Matheus: nunca requisição automática à API).
# Lógica de leitura portada de scripts_exploracao_ML/
# gerar_planilha_llm_inventario.py (buscar_categoria / buscar_item), já
# validada com dado real.

NOME_LOG = "sincronizar_caracteristicas_ml"


class AtributosML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: Tags da API (dict {tag: true} em /attributes, lista
    # em technical_specs) -> lista ordenada só com as ativas.
    @staticmethod
    def _tags_ativas(attr: dict) -> list[str]:
        tags = attr.get("tags")
        if isinstance(tags, dict):
            return sorted(str(k) for k, v in tags.items() if v)
        if isinstance(tags, list):
            return sorted(str(t) for t in tags)
        return []

    # Função Objetivo: Lê o que a categoria pede no card "Características
    # principais" (2 chamadas: technical_specs/input + attributes). Devolve
    # {"card": {atributo_id: {...}}, "defs": {atributo_id: {...}}} na ordem
    # em que o ML mostra os campos. "card" vem do componente de tela
    # (nome, tags, allow_custom_value, tipo de componente); "defs" vem da
    # definição do atributo (value_type, tamanho máximo, opções, unidades,
    # tags) — só dos atributos que estão no card.
    def buscar_card_categoria(self, category_id: str, pasta_logs) -> dict:
        resposta_specs = self._cliente.chamar(
            "GET", f"/categories/{category_id}/technical_specs/input",
            pasta_logs=pasta_logs, nome_log=NOME_LOG,
        )
        card = {}
        for grupo in resposta_specs.json().get("groups", []):
            if grupo.get("id") != "MAIN":
                continue
            for componente in grupo.get("components", []):
                ui_config = componente.get("ui_config") or {}
                for attr in componente.get("attributes", []):
                    atributo_id = attr.get("id")
                    tags = self._tags_ativas(attr)
                    if not atributo_id or "allow_variations" in tags:
                        continue
                    card[atributo_id] = {
                        "label": attr.get("label") or attr.get("name") or atributo_id,
                        "tags": tags,
                        "allow_custom_value": ui_config.get("allow_custom_value"),  # True / False / None (não informado)
                        "componente": componente.get("component"),
                    }

        resposta_attrs = self._cliente.chamar(
            "GET", f"/categories/{category_id}/attributes",
            pasta_logs=pasta_logs, nome_log=NOME_LOG,
        )
        defs = {}
        for attr in resposta_attrs.json():
            atributo_id = attr.get("id")
            if not atributo_id or atributo_id not in card:
                continue
            defs[atributo_id] = {
                "value_type": attr.get("value_type"),
                "value_max_length": attr.get("value_max_length"),
                "values": [{"id": o.get("id"), "name": o.get("name")} for o in attr.get("values") or []],
                "allowed_units": [{"id": u.get("id"), "name": u.get("name")} for u in attr.get("allowed_units") or []],
                "tags": self._tags_ativas(attr),
            }

        return {"card": card, "defs": defs}

    # Função Objetivo: Lê os valores que o anúncio tem HOJE no ML. Devolve a
    # categoria e o status que o ML informou agora e o array "attributes"
    # CRU (inclusive os "N/A", que chegam com value_id "-1" e value_name
    # nulo) — sem nenhuma normalização, é o espelho que a tela mostra em
    # "Hoje no Mercado Livre".
    def buscar_atributos_item(self, mlb: str, pasta_logs) -> dict:
        resposta = self._cliente.chamar(
            "GET", f"/items/{mlb}",
            pasta_logs=pasta_logs, nome_log=NOME_LOG,
            params={"include_internal_attributes": "true"},
        )
        corpo = resposta.json()
        return {
            "category_id": corpo.get("category_id"),
            "status": corpo.get("status"),
            "attributes": corpo.get("attributes") or [],
        }
