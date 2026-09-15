# scripts_exploracao_ML/investigar_shipment.py
#
# Objetivo ÚNICO: pegar o envio de ida (forward) da venda já confirmada
# como devolução real, via GET /shipments/$SHIPPING_ID, pra confirmar
# comum×FULL (campo logistic.mode/logistic.type) e ver a estrutura de
# status/entrega. NENHUM outro endpoint é chamado além deste.
#
# Exige o header "x-format-new: true" — por isso a mudança no
# chamar_api() pra aceitar headers_extra, aplicada antes deste script.
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
CONTA = "MB"
SHIPPING_ID = 47959728530   # "shipping.id" achado no investigar_dados_da_venda.py
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_shipment_{SHIPPING_ID}.json"


try:
    # Só pra poder ocultar seu próprio user_id no arquivo final, mesma
    # lógica dos scripts anteriores (o shipment pode trazer esse ID em
    # "origin.sender_id" ou parecido).
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_shipment",
    )
    user_id = resposta_me.json()["id"]

    resposta_shipment = chamar_api(
        "GET", f"/shipments/{SHIPPING_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        headers_extra={"x-format-new": "true"},
        nome_log="investigar_shipment",
    )
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resultado_cru = resposta_shipment.json()

    texto_json = json.dumps(resultado_cru, ensure_ascii=False, indent=2)
    texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        f.write(texto_json_oculto)

    print(f"Retorno (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
    print("Suba esse arquivo na conversa pra eu analisar.")