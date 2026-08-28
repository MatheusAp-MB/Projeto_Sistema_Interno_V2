# scripts_exploracao_ML/investigar_retorno_bruto_item.py
#
# Busca o retorno BRUTO da API do Mercado Livre pra 1 MLB (GET /items?ids=,
# o MESMO endpoint que integracao_mercado_livre/servicos/buscar_detalhes.py
# chama de verdade), sem nenhum filtro, extração ou achatamento de campo.
# Objetivo: ver 100% do que a API devolve — em especial a estrutura real
# do array "pictures" — antes de decidir o que a tela nova vai aproveitar.
#
# Só leitura. Não toca no banco, não grava nada além do arquivo de saída.

import json
import sys
from pathlib import Path

# Permite rodar este script direto (python scripts_exploracao_ML/investigar_retorno_bruto_item.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MLB = "MLB5838465508"  # troque pelo MLB real que você quer investigar
CONTA = "MB"           # "MB" (Magazine) ou "SV" (Samvale)
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_bruta_{MLB}.json"


try:
    resposta = chamar_api(
        "GET", "/items",
        pasta_logs=PASTA_LOGS, conta=CONTA, params={"ids": MLB},
        nome_log="investigar_retorno_bruto_item",
    )
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resultado_cru = resposta.json()  # sem tocar em nada — cru, do jeito que a API mandou

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(resultado_cru, f, ensure_ascii=False, indent=2)

    print(f"Retorno bruto salvo em: {CAMINHO_SAIDA}")
    print("Suba esse arquivo na conversa pra eu analisar — nenhum campo foi filtrado.")