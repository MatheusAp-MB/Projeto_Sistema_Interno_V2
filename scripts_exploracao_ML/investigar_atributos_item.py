# scripts_exploracao_ML/investigar_atributos_item.py
#
# Busca o retorno BRUTO da API do Mercado Livre pra 1 MLB (GET /items/$ITEM_ID,
# endpoint confirmado na doc oficial de Atributos — devolve o item inteiro,
# incluindo o array "attributes" com as Características principais já
# preenchidas), sem nenhum filtro, extração ou achatamento de campo.
#
# Inclui include_internal_attributes=true: confirmado na doc como necessário
# pra também trazer atributos marcados como N/A (não aplica), que senão ficam
# escondidos na resposta padrão.
#
# Objetivo: ver 100% do que a API devolve pro campo attributes de um anúncio
# real, antes de desenhar o domínio novo (futuro atributos_ml.py, mesmo
# padrão de Contexto dos outros 6 domínios já existentes).
#
# Primeiro teste do novo objetivo "Características/Atributos ML" — ver
# Checkpoint - Investigação da API de Atributos do Mercado Livre, no vault.
#
# Produto de teste: SKU F7908050719121.001 / MLB2616936722.
#
# Só leitura. Não toca no banco, não grava nada além do arquivo de saída.

import json
import sys
from pathlib import Path

# Permite rodar este script direto (python scripts_exploracao_ML/investigar_atributos_item.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MLB = "MLB2616936722"  # Bota Ortopédica Imobilizadora Curta Bilateral Takecare — SKU F7908050719121.001
CONTA = "MB"  # "MB" (Magazine) ou "SV" (Samvale) — CONFIRME de qual empresa é esse MLB antes de rodar
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_atributos_{MLB}.json"


try:
    resposta = chamar_api(
        "GET", f"/items/{MLB}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={"include_internal_attributes": "true"},
        nome_log="investigar_atributos_item",
    )
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resultado_cru = resposta.json()  # sem tocar em nada — cru, do jeito que a API mandou

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(resultado_cru, f, ensure_ascii=False, indent=2)

    print(f"Retorno bruto salvo em: {CAMINHO_SAIDA}")
    print(f"Atributos preenchidos encontrados: {len(resultado_cru.get('attributes', []))}")
    print("Suba esse arquivo na conversa pra eu analisar — nenhum campo foi filtrado.")