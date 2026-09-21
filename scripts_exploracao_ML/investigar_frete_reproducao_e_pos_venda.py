# scripts_exploracao_ML/investigar_frete_reproducao_e_pos_venda.py
#
# Objetivo ÚNICO: dar continuidade à investigação de frete real (ver
# investigar_frete_real_anuncio.py), testando 3 pontos que ficaram em
# aberto depois de cruzar os resultados anteriores com a doc oficial:
#
#   (C1) Refazer o teste "fallback" (sem item_id) corrigindo o bug de
#        unidade encontrado: peso em dimensions deve ser em GRAMAS
#        inteiro, não em kg (doc "Mercado Envios — Custos e cotações").
#
#   (C2) Tentar reproduzir o desconto "mandatory" (50%) do anúncio real
#        SEM usar item_id — buscando primeiro os atributos reais do
#        próprio anúncio (GET /items/$ITEM_ID: category_id,
#        listing_type_id, price, condition, shipping.mode/logistic_type)
#        e usando esses valores reais na chamada de simulação, em vez
#        de inventar parâmetros.
#
#   (C3) Consultar o custo PÓS-VENDA real de um envio já realizado,
#        via GET /shipments/$SHIPPING_ID/costs (campo senders[].cost)
#        — endpoint diferente do shipping_options/free, confirmado na
#        doc "Gerenciamento de Envios". Precisa de um SHIPPING_ID real
#        de uma venda já feita (preencher abaixo).
#
# Cada cenário roda isolado (try/except próprio) pra um cenário não
# derrubar os outros — principalmente o C3, que depende de você
# preencher um SHIPPING_ID real antes de rodar.
#
# Só leitura. Não toca no banco, não grava nada além do arquivo de saída.

import json
import sys
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                       # "MB" (Magazine) ou "SV" (Samvale)
ITEM_ID = "MLB5838465508"          # mesmo anúncio já validado no teste anterior

# Cenário C3 precisa de um SHIPPING_ID de uma venda JÁ REALIZADA (não
# precisa ser desse mesmo MLB — só pra entender o formato da resposta).
# Pegue o "shipping.id" de qualquer pedido recente (aparece em
# /orders/$ORDER_ID, campo shipping.id — igual foi feito antes em
# investigar_dados_da_venda.py / investigar_shipment.py). Deixe None
# pra pular esse cenário.
SHIPPING_ID_VENDA_REAL = None       # <-- TROQUE por um shipping_id real, ex: 47959728530
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_frete_reproducao_{ITEM_ID}.json"

resultado = {}


def redigir(valor_json, user_id):
    texto = json.dumps(valor_json, ensure_ascii=False, indent=2)
    return texto.replace(str(user_id), "SEU_USER_ID_OCULTO")


try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_frete_reproducao",
    )
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao autenticar / obter user_id: {erro}")
    sys.exit(1)

endpoint_simulacao = f"/users/{user_id}/shipping_options/free"

# --- Cenário C1: fallback simulado com peso em GRAMAS (bug corrigido) ---
try:
    resposta_c1 = chamar_api(
        "GET", endpoint_simulacao,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={
            "dimensions": "30x40x20,5000",   # 30x40x20cm, 5000g (5kg) — corrigido
            "item_price": 150,
            "verbose": "true",
            "free_shipping": "true",
        },
        nome_log="investigar_frete_reproducao",
    )
    resultado["cenario_C1_fallback_peso_em_gramas"] = resposta_c1.json()
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    resultado["cenario_C1_fallback_peso_em_gramas"] = {"erro": str(erro)}

# --- Cenário C2: buscar atributos reais do anúncio e tentar reproduzir
# o desconto "mandatory" simulando SEM item_id ---
try:
    resposta_item = chamar_api(
        "GET", f"/items/{ITEM_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_frete_reproducao",
    )
    item = resposta_item.json()
    shipping_info = item.get("shipping") or {}

    resultado["cenario_C2_atributos_reais_do_item"] = {
        "price": item.get("price"),
        "category_id": item.get("category_id"),
        "listing_type_id": item.get("listing_type_id"),
        "condition": item.get("condition"),
        "shipping": shipping_info,
    }

    # Dimensões: se o item não trouxer shipping.dimensions (comum em Full,
    # onde a embalagem é controlada pelo centro de distribuição), usa as
    # dimensões reais vistas no print do painel (56x41x23cm, ~6.84kg).
    dimensoes_para_simular = shipping_info.get("dimensions") or "56x41x23,6840"

    params_c2 = {
        "dimensions": dimensoes_para_simular,
        "item_price": item.get("price"),
        "verbose": "true",
        "condition": item.get("condition", "new"),
        "category_id": item.get("category_id"),
        "listing_type_id": item.get("listing_type_id"),
        "mode": shipping_info.get("mode", "me2"),
        "logistic_type": shipping_info.get("logistic_type"),
        "free_shipping": "true",
    }
    resposta_c2 = chamar_api(
        "GET", endpoint_simulacao,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params_c2,
        nome_log="investigar_frete_reproducao",
    )
    resultado["cenario_C2_fallback_com_atributos_reais"] = {
        "parametros_usados": params_c2,
        "resposta": resposta_c2.json(),
    }
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    resultado["cenario_C2_fallback_com_atributos_reais"] = {"erro": str(erro)}

# --- Cenário C3: custo PÓS-VENDA real de um envio já realizado ---
if SHIPPING_ID_VENDA_REAL:
    try:
        resposta_c3 = chamar_api(
            "GET", f"/shipments/{SHIPPING_ID_VENDA_REAL}/costs",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            headers_extra={"x-format-new": "true"},
            nome_log="investigar_frete_reproducao",
        )
        resultado["cenario_C3_custo_pos_venda"] = resposta_c3.json()
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultado["cenario_C3_custo_pos_venda"] = {"erro": str(erro)}
else:
    resultado["cenario_C3_custo_pos_venda"] = {
        "pulado": "SHIPPING_ID_VENDA_REAL não foi preenchido — preencha com um shipping_id real e rode de novo."
    }

texto_json_oculto = redigir(resultado, user_id)

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    f.write(texto_json_oculto)

print(f"Retorno (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
print("Suba esse arquivo na conversa pra eu analisar.")