# api_mercado_livre/detalhes_ml.py

# Função Objetivo: Contexto "Detalhe completo de anúncios" — sabe tudo
# que o ClienteApiMercadoLivre (transporte puro) não deve saber: qual
# endpoint chamar (GET /items?ids=..., multiget) e como interpretar/
# achatar a resposta (campos do anúncio pai + 1 registro por variação).
# Compõe um ClienteApiMercadoLivre (nunca herda dele) e devolve
# (registros, erros_itens) já prontos — quem chama decide progresso/
# persistência, esta classe não sabe de arquivo nem de disco. Ver
# "Padrao de Robustez para Clientes de API Externa" no vault. Peça 4 da
# reforma estrutural (27/09/2026) — extraído de
# integracao_mercado_livre/servicos/buscar_detalhes.py, mesma lógica,
# byte a byte (inclusive lógica de extração idêntica ao original).

import json


class DetalhesML:
    def __init__(self, cliente):
        self._cliente = cliente

    # ─── EXTRAÇÃO DE CAMPOS (idêntico ao script original — lógica não mudou) ───

    def _extrair_sku(self, body: dict) -> str | None:
        for attr in body.get("attributes", []):
            if attr.get("id") == "SELLER_SKU":
                return attr.get("value_name")
        return body.get("seller_custom_field")

    def _extrair_atributo(self, body: dict, attr_id: str) -> str | None:
        for attr in body.get("attributes", []):
            if attr.get("id") == attr_id:
                return attr.get("value_name")
        return None

    def _extrair_sku_variacao(self, var: dict) -> str | None:
        for attr in var.get("attributes", []):
            if attr.get("id") == "SELLER_SKU":
                return attr.get("value_name")
        return var.get("seller_custom_field")

    def _extrair_dimensoes(self, shipping: dict) -> dict:
        dims = shipping.get("dimensions") or {}
        if not isinstance(dims, dict):
            return {"shipping_dim_width": None, "shipping_dim_height": None,
                    "shipping_dim_length": None, "shipping_dim_weight": None}
        return {
            "shipping_dim_width":  dims.get("width"),
            "shipping_dim_height": dims.get("height"),
            "shipping_dim_length": dims.get("length"),
            "shipping_dim_weight": dims.get("weight"),
        }

    def _extrair_campos_pai(self, body: dict, meta: dict) -> dict:
        shipping = body.get("shipping", {})
        shipping_tags = shipping.get("tags", [])

        def extrair_imagem_principal(body: dict) -> str | None:
            pictures = body.get("pictures", [])
            if not pictures:
                return None
            url = pictures[0].get("secure_url") or pictures[0].get("url")
            if not url:
                return None
            try:
                base, ext = url.rsplit(".", 1)
                base_sem_sufixo = base.rsplit("-", 1)[0]
                return f"{base_sem_sufixo}-F.{ext}"
            except Exception:
                return url

        return {
            "mlb":                  body.get("id"),
            "title":                body.get("title"),
            "thumbnail":            body.get("thumbnail"),
            "imagem_principal":     extrair_imagem_principal(body),
            "pictures":             body.get("pictures", []),
            "status":               body.get("status"),
            "sub_status":           json.dumps(body.get("sub_status", []), ensure_ascii=False),
            "condition":            body.get("condition"),

            "price":                body.get("price"),
            "base_price":           body.get("base_price"),
            "original_price":       body.get("original_price"),

            "available_quantity":   body.get("available_quantity"),
            "sold_quantity":        body.get("sold_quantity"),
            "initial_quantity":     body.get("initial_quantity"),

            "listing_type_id":      body.get("listing_type_id"),
            "catalog_listing":      body.get("catalog_listing"),
            "catalog_product_id":   body.get("catalog_product_id"),

            "logistic_type":        shipping.get("logistic_type"),
            "free_shipping":        shipping.get("free_shipping"),
            "flex":                 "self_service_in" in shipping_tags,
            "shipping_tags":        json.dumps(shipping_tags, ensure_ascii=False),
            **self._extrair_dimensoes(shipping),

            "sku":                  self._extrair_sku(body),
            "inventory_id":         body.get("inventory_id"),
            "user_product_id":      body.get("user_product_id"),

            "attr_seller_package_height": self._extrair_atributo(body, "SELLER_PACKAGE_HEIGHT"),
            "attr_seller_package_width":  self._extrair_atributo(body, "SELLER_PACKAGE_WIDTH"),
            "attr_seller_package_length": self._extrair_atributo(body, "SELLER_PACKAGE_LENGTH"),
            "attr_seller_package_weight": self._extrair_atributo(body, "SELLER_PACKAGE_WEIGHT"),
            "attr_dimensions":            self._extrair_atributo(body, "DIMENSIONS"),
            "attr_weight":                self._extrair_atributo(body, "WEIGHT"),

            "family_name":          body.get("family_name"),
            "family_id":            body.get("family_id"),

            "item_relations":       json.dumps(body.get("item_relations", []), ensure_ascii=False),
            "parent_item_id":       body.get("parent_item_id"),
            "differential_pricing": body.get("differential_pricing"),
            "deal_ids":             json.dumps(body.get("deal_ids", []), ensure_ascii=False),

            "category_id":          body.get("category_id"),
            "domain_id":            body.get("domain_id"),

            "tags":                 json.dumps(body.get("tags", []), ensure_ascii=False),

            "warranty":             body.get("warranty"),

            "date_created":         body.get("date_created"),
            "last_updated":         body.get("last_updated"),
            "start_time":           body.get("start_time"),
            "stop_time":            body.get("stop_time"),
            "end_time":             body.get("end_time"),
            "expiration_time":      body.get("expiration_time"),

            "permalink":            body.get("permalink"),

            "tem_variacoes":        len(body.get("variations", [])) > 0,
            "variacao_id":          None,
            "variacao_atributos":   None,
            "variacao_num_fotos":   None,

            "ga_status":            meta.get("status"),
            "ga_logistica":         meta.get("logistica"),
            "ga_tipo":              meta.get("tipo"),
            "ga_catalogo":          meta.get("catalogo"),
        }

    def _processar_item(self, body: dict, meta: dict) -> list[dict]:
        variacoes = body.get("variations", [])

        if not variacoes:
            return [self._extrair_campos_pai(body, meta)]

        registros = []
        campos_pai = self._extrair_campos_pai(body, meta)

        for var in variacoes:
            reg = campos_pai.copy()

            reg["available_quantity"] = var.get("available_quantity")
            reg["sold_quantity"]      = var.get("sold_quantity")
            reg["inventory_id"]       = var.get("inventory_id")
            reg["user_product_id"]    = var.get("user_product_id")
            reg["catalog_product_id"] = var.get("catalog_product_id") or campos_pai["catalog_product_id"]
            reg["item_relations"]     = json.dumps(var.get("item_relations", []), ensure_ascii=False)

            sku_var = self._extrair_sku_variacao(var)
            if sku_var:
                reg["sku"] = sku_var

            if var.get("price") is not None:
                reg["price"] = var.get("price")

            reg["variacao_id"] = var.get("id")
            reg["variacao_num_fotos"] = len(var.get("picture_ids", []))

            combinacoes = var.get("attribute_combinations", [])
            reg["variacao_atributos"] = " / ".join(
                c.get("value_name", "") for c in combinacoes if c.get("value_name")
            ) or None

            registros.append(reg)

        return registros

    # ─── CHAMADA À API ────────────────────────────────────────────────

    # Função Objetivo: Busca 1 lote (até 20 MLBs) via multiget e devolve
    # (registros, erros_itens) já achatados — quem chama decide progresso
    # e persistência.
    def buscar_lote(self, ids_str: str, meta_map: dict, pasta_logs) -> tuple[list[dict], list[dict]]:
        resposta = self._cliente.chamar(
            "GET", "/items",
            pasta_logs=pasta_logs, params={"ids": ids_str}, nome_log="buscar_detalhes",
        )
        resultados = resposta.json()

        registros = []
        erros_itens = []

        for item in resultados:
            code = item.get("code", 0)
            body = item.get("body", {})
            mlb  = body.get("id") or ""

            if code != 200:
                erros_itens.append({"mlb": mlb, "code": code})
                continue

            meta = meta_map.get(mlb, {})
            registros.extend(self._processar_item(body, meta))

        return registros, erros_itens