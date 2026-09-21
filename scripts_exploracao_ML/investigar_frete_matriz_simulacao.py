# scripts_exploracao_ML/investigar_frete_matriz_simulacao.py
#
# Objetivo ÚNICO: rodar de uma vez toda a matriz de variações da
# simulação de frete sem item_id (shipping_options/free), pra isolar
# por que o Cenário C2 anterior reproduziu o discount.type "mandatory"
# (rate 0.5) mas com billable_weight e list_cost bem maiores que o
# valor real do anúncio (via item_id).
#
# Dimensões reais confirmadas por Matheus direto no painel do vendedor
# do MLB5838465508 (Full):
#   Embalagem de fábrica: 56 x 42 x 25 cm, 6.82 kg
#   Embalagem de envio:   56 x 41 x 23 cm, 6.84 kg  (a que já tínhamos usado)
#
# Varia 4 parâmetros que ainda são hipótese (2^4 = 16 combinações):
#   - item_price: 447.00 (tabela) x 378.90 (preço de venda/promoção)
#   - dimensions: embalagem de fábrica x embalagem de envio
#   - logistic_type: "fulfillment" x omitido (não envia o parâmetro)
#   - free_shipping: true x false
#
# Mantém fixos (já confirmados reais via GET /items/$ITEM_ID):
#   category_id, listing_type_id, condition, mode=me2, verbose=true
#
# Também roda, pra referência/comparação lado a lado no mesmo arquivo:
#   - Baseline real com item_id (free_shipping true e false)
#   - Cenário pós-venda /shipments/$SHIPPING_ID/costs (se preenchido)
#
# Cada chamada roda isolada — uma falhar não derruba as outras.
# Só leitura. Não toca no banco, não grava nada além do arquivo de saída.

import json
import sys
from itertools import product
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"
ITEM_ID = "MLB5838465508"

# Dimensões reais confirmadas no painel (altura x largura x comprimento,peso_em_gramas)
DIMENSOES_EMBALAGEM_FABRICA = "56x42x25,6820"
DIMENSOES_EMBALAGEM_ENVIO = "56x41x23,6840"

# Preços reais confirmados no painel
PRECO_TABELA = 447.00
PRECO_VENDA_PROMOCAO = 378.90

# Cenário pós-venda (opcional) — preencha com um shipping_id real de uma
# venda já feita pra também testar /shipments/$SHIPPING_ID/costs.
SHIPPING_ID_VENDA_REAL = None       # <-- TROQUE por um shipping_id real, ex: 47959728530
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_frete_matriz_{ITEM_ID}.json"

resultado = {"baseline_com_item_id": {}, "matriz_fallback_sem_item_id": {}, "pos_venda": {}}


def chamar_simulacao(user_id, params, nome_log):
    endpoint = f"/users/{user_id}/shipping_options/free"
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log=nome_log,
    )
    return resposta.json()


try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_frete_matriz",
    )
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao autenticar / obter user_id: {erro}")
    sys.exit(1)

# --- Baseline real, com item_id (referência pra comparar a matriz) ---
for free_shipping_valor in ("true", "false"):
    chave = f"item_id_free_shipping_{free_shipping_valor}"
    try:
        resultado["baseline_com_item_id"][chave] = chamar_simulacao(
            user_id,
            {"item_id": ITEM_ID, "verbose": "true", "free_shipping": free_shipping_valor},
            "investigar_frete_matriz",
        )
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultado["baseline_com_item_id"][chave] = {"erro": str(erro)}

# --- Atributos reais do item, pra manter fixos na matriz ---
try:
    resposta_item = chamar_api(
        "GET", f"/items/{ITEM_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_frete_matriz",
    )
    item = resposta_item.json()
    category_id = item.get("category_id")
    listing_type_id = item.get("listing_type_id")
    condition = item.get("condition", "new")
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao buscar atributos do item (categoria/listing_type): {erro}")
    print("A matriz vai rodar sem category_id/listing_type_id — resultado pode variar.")
    category_id = None
    listing_type_id = None
    condition = "new"

# --- Matriz de variações (2 x 2 x 2 x 2 = 16 combinações) ---
opcoes_preco = {"tabela": PRECO_TABELA, "promocao": PRECO_VENDA_PROMOCAO}
opcoes_dimensao = {"fabrica": DIMENSOES_EMBALAGEM_FABRICA, "envio": DIMENSOES_EMBALAGEM_ENVIO}
opcoes_logistic_type = {"fulfillment": "fulfillment", "omitido": None}
opcoes_free_shipping = {"true": "true", "false": "false"}

for (nome_preco, preco), (nome_dim, dimensao), (nome_logistic, logistic_type), (nome_fs, free_shipping_valor) in product(
    opcoes_preco.items(), opcoes_dimensao.items(), opcoes_logistic_type.items(), opcoes_free_shipping.items()
):
    chave = f"preco={nome_preco}|dimensao={nome_dim}|logistic_type={nome_logistic}|free_shipping={nome_fs}"

    params = {
        "dimensions": dimensao,
        "item_price": preco,
        "verbose": "true",
        "condition": condition,
        "category_id": category_id,
        "listing_type_id": listing_type_id,
        "mode": "me2",
        "free_shipping": free_shipping_valor,
    }
    if logistic_type:
        params["logistic_type"] = logistic_type

    try:
        resultado["matriz_fallback_sem_item_id"][chave] = {
            "parametros": params,
            "resposta": chamar_simulacao(user_id, params, "investigar_frete_matriz"),
        }
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultado["matriz_fallback_sem_item_id"][chave] = {
            "parametros": params,
            "erro": str(erro),
        }

# --- Pós-venda (opcional) ---
if SHIPPING_ID_VENDA_REAL:
    try:
        resposta_c3 = chamar_api(
            "GET", f"/shipments/{SHIPPING_ID_VENDA_REAL}/costs",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            headers_extra={"x-format-new": "true"},
            nome_log="investigar_frete_matriz",
        )
        resultado["pos_venda"] = resposta_c3.json()
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultado["pos_venda"] = {"erro": str(erro)}
else:
    resultado["pos_venda"] = {
        "pulado": "SHIPPING_ID_VENDA_REAL não foi preenchido."
    }

texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    f.write(texto_json_oculto)

print(f"Retorno (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
print(f"Total de combinações testadas na matriz: {len(resultado['matriz_fallback_sem_item_id'])}")
print("Suba esse arquivo na conversa pra eu analisar.")