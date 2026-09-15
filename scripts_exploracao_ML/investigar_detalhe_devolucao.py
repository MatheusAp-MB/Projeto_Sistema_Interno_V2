# scripts_exploracao_ML/investigar_detalhe_devolucao.py
#
# Objetivo ÚNICO: pegar o detalhe de UMA devolução específica, via
# GET /post-purchase/v2/claims/$CLAIM_ID/returns, pra confirmar que o
# claim escolhido (achado com investigar_claims_recentes.py) é mesmo uma
# devolução de produto completa, e ver a estrutura real dos campos antes
# de decidir o que aproveitar no autocomplete. NENHUM outro endpoint é
# chamado além deste.
#
# Não chama /orders, /shipments, /post-purchase/v1/claims/$ID (detalhe da
# reclamação em si) nem nada além disso — isso fica pra depois.
#
# Só leitura. Não toca no banco, não grava nada além do arquivo de saída.

import json
import sys
from pathlib import Path

# Permite rodar este script direto (python scripts_exploracao_ML/investigar_detalhe_devolucao.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"              # "MB" (Magazine) ou "SV" (Samvale)
CLAIM_ID = 5576772421     # achado no investigar_claims_recentes.py (resolution.reason == item_returned)
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_devolucao_{CLAIM_ID}.json"


try:
    resposta = chamar_api(
        "GET", f"/post-purchase/v2/claims/{CLAIM_ID}/returns",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_detalhe_devolucao",
    )
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resultado_cru = resposta.json()  # sem tocar em nada — cru, do jeito que a API mandou

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(resultado_cru, f, ensure_ascii=False, indent=2)

    print(f"Retorno bruto salvo em: {CAMINHO_SAIDA}")
    print("Suba esse arquivo na conversa pra eu analisar — nenhum campo foi filtrado.")