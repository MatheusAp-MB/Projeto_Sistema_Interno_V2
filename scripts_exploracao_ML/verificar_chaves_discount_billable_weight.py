# scripts_exploracao_ML/verificar_chaves_discount_billable_weight.py
#
# Objetivo ÚNICO: confirmar os nomes exatos das chaves dentro de
# coverage.all_country.discount (especificamente "rate" e "promoted_amount")
# antes de rodar buscar_frete_real_ml em massa de novo. list_cost,
# billable_weight e discount.type já estão confirmados (o 1º e o 3º já
# rodaram certo em produção; o 2º foi confirmado nos scripts de
# investigação anteriores) — só rate/promoted_amount são suposição ainda
# não verificada em nenhum código real, só citados em prosa na nota do
# vault da investigação original.
#
# Usa o MESMO endpoint e os MESMOS parâmetros que buscar_frete_real_ml.py
# usa de verdade (item_id + verbose=true, sem free_shipping) — pra
# garantir que a resposta é idêntica à que o comando de coleta recebe.
#
# Só leitura. Não toca no banco (não usa Django ORM), não grava nada além
# do arquivo de saída com o JSON cru (user_id oculto).

import json
import sys
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                       # "MB" (Magazine) ou "SV" (Samvale)
ITEM_ID = "MLB6723265420"          # MLB real, confirmado com sucesso na coleta de ontem
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"verificacao_discount_{ITEM_ID}.json"

try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="verificar_chaves_discount",
    )
    user_id = resposta_me.json()["id"]

    resposta = chamar_api(
        "GET", f"/users/{user_id}/shipping_options/free",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={"item_id": ITEM_ID, "verbose": "true"},
        nome_log="verificar_chaves_discount",
    )

except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resposta_json = resposta.json()
    all_country = resposta_json.get("coverage", {}).get("all_country", {})
    discount = all_country.get("discount", {}) or {}

    print("=== coverage.all_country (bloco relevante inteiro) ===")
    print(json.dumps(all_country, ensure_ascii=False, indent=2))

    print("\n=== O que o código de buscar_frete_real_ml.py extrairia hoje ===")
    print(f"list_cost              = {all_country.get('list_cost')!r}  (já confirmado)")
    print(f"billable_weight         = {all_country.get('billable_weight')!r}  (já confirmado)")
    print(f"discount.type           = {discount.get('type')!r}  (já confirmado)")
    print(f"discount.rate           = {discount.get('rate')!r}  <- CONFERIR")
    print(f"discount.promoted_amount = {discount.get('promoted_amount')!r}  <- CONFERIR")

    print(f"\nSe 'rate'/'promoted_amount' vieram None mas existe alguma outra chave "
          f"no dict 'discount' acima com valor parecido, é só me avisar o nome certo "
          f"que eu ajusto o _extrair_frete_real() antes de você rodar a coleta completa.")

    texto_json = json.dumps(resposta_json, ensure_ascii=False, indent=2)
    texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")
    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        f.write(texto_json_oculto)

    print(f"\nResposta completa (com seu user_id oculto) salva em: {CAMINHO_SAIDA}")