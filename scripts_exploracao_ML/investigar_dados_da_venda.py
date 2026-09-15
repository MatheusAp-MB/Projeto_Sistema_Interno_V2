# scripts_exploracao_ML/investigar_dados_da_venda.py
#
# Objetivo ÚNICO: pegar os dados da venda em si, via GET /orders/$ORDER_ID,
# pro pedido já confirmado como devolução real (achado com
# investigar_detalhe_devolucao.py). Aqui que deve estar o que interessa
# pro autocomplete: produto, data da venda, se é FULL, etc.
#
# Não chama /orders/$ID/shipments, /post-purchase/... nem nada além disso
# — isso fica pra depois, com esse resultado em mãos.
#
# Só leitura. Não toca no banco, não grava nada além do arquivo de saída.

import json
import sys
from pathlib import Path

# Permite rodar este script direto (python scripts_exploracao_ML/investigar_dados_da_venda.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                     # "MB" (Magazine) ou "SV" (Samvale)
ORDER_ID = 2000018341680948      # achado no investigar_claims_recentes.py / confirmado no investigar_detalhe_devolucao.py
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_venda_{ORDER_ID}.json"


try:
    # Só pra poder ocultar seu próprio user_id no arquivo final (o campo
    # "seller.id" do order vai ser exatamente esse número) — mesma lógica
    # do investigar_claims_recentes.py, não é exploração de outro endpoint.
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_dados_da_venda",
    )
    user_id = resposta_me.json()["id"]

    # O único que interessa de verdade:
    resposta_order = chamar_api(
        "GET", f"/orders/{ORDER_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_dados_da_venda",
    )
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resultado_cru = resposta_order.json()  # sem tocar em nada — cru, do jeito que a API mandou

    texto_json = json.dumps(resultado_cru, ensure_ascii=False, indent=2)
    texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        f.write(texto_json_oculto)

    print(f"Retorno (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
    print("Suba esse arquivo na conversa pra eu analisar.")