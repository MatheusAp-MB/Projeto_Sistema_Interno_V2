# scripts_exploracao_ML/investigar_frete_real_anuncio.py
#
# Objetivo ÚNICO: descobrir se o campo de frete real (o que o VENDEDOR paga,
# já com desconto aplicado) bate com o valor mostrado no painel do Mercado
# Livre ("Custo de envio"), usando GET /users/$USER_ID/shipping_options/free.
#
# Testa 2 cenários:
#   (A) Anúncio real e já publicado, via item_id — testando free_shipping=True
#       e free_shipping=False, pra comparar os dois valores retornados.
#   (B) "Fallback" simulando um produto que AINDA NÃO existe como anúncio,
#       via dimensions + item_price (sem item_id) — se funcionar, essa
#       chamada pode virar a base de uma calculadora de frete no sistema,
#       pra simular custo de envio antes de publicar.
#
# Não chama nenhum outro endpoint além desses. Não altera nada no ML.
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
ITEM_ID = "MLB5838465508"          # anúncio real já publicado, confirmado por você

# Cenário (B) "fallback" — simula um produto que ainda NÃO é anúncio.
# PRECISA preencher com valores reais antes de rodar (não inventei nada aqui
# de propósito — não sei as medidas/preço de nenhum produto seu):
#   formato: "altura x largura x comprimento,peso" -> cm e kg
#   exemplo da doc oficial: "30x40x20,5" (30cm x 40cm x 20cm, 5kg)
DIMENSOES_SIMULADAS = "30x40x20,5"   # <-- TROQUE por um produto real seu
PRECO_SIMULADO = 150.00              # <-- TROQUE pelo preço de venda desse produto
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_frete_real_{ITEM_ID}.json"


try:
    # Só pra poder ocultar seu próprio user_id no arquivo final, e porque o
    # endpoint de frete exige o user_id na própria URL (/users/$USER_ID/...).
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_frete_real",
    )
    user_id = resposta_me.json()["id"]

    endpoint = f"/users/{user_id}/shipping_options/free"

    # --- Cenário A1: anúncio real, free_shipping=True (o vendedor absorve o
    # custo do frete grátis pro comprador — é esse o valor que aparece no
    # "Custo de envio" do Resumo de custos do painel do ML) ---
    resposta_item_frete_gratis = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={
            "item_id": ITEM_ID,
            "verbose": "true",
            "free_shipping": "true",
        },
        nome_log="investigar_frete_real",
    )

    # --- Cenário A2: o mesmo anúncio, free_shipping=False (comprador paga)
    # — só pra comparar e confirmar que o valor muda mesmo com o parâmetro ---
    resposta_item_frete_pago = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={
            "item_id": ITEM_ID,
            "verbose": "true",
            "free_shipping": "false",
        },
        nome_log="investigar_frete_real",
    )

    # --- Cenário B: fallback simulado (sem item_id) — dimensions + item_price ---
    resposta_simulado = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={
            "dimensions": DIMENSOES_SIMULADAS,
            "item_price": PRECO_SIMULADO,
            "verbose": "true",
            "free_shipping": "true",
        },
        nome_log="investigar_frete_real",
    )

except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resultado_cru = {
        "cenario_A1_item_real_free_shipping_true": resposta_item_frete_gratis.json(),
        "cenario_A2_item_real_free_shipping_false": resposta_item_frete_pago.json(),
        "cenario_B_fallback_simulado_sem_item_id": resposta_simulado.json(),
    }

    texto_json = json.dumps(resultado_cru, ensure_ascii=False, indent=2)
    texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        f.write(texto_json_oculto)

    print(f"Retorno (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
    print("Suba esse arquivo na conversa pra eu analisar.")