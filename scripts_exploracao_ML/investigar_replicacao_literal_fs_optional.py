# scripts_exploracao_ML/investigar_replicacao_literal_fs_optional.py
#
# Objetivo: replicação LITERAL do teste que originalmente reproduziu
# discount.type="fs_optional" (script investigar_reputacao_seller_status_abaixo_79.py,
# rodada 1 -- variante "a_baseline_sem_parametros_novos", sem nenhum parâmetro
# especulativo de reputação/seller_status/seller_type, que já foram confirmados
# "sem efeito nenhum em nenhuma variante" na investigação anterior).
#
# Contexto: as últimas 3 investigações desta sessão (127 chamadas no total --
# amostragem estratificada, densidade sintética, categoria de referência)
# NUNCA reproduziram fs_optional, sempre "mandatory". Mas nenhuma delas
# replicou os parâmetros EXATOS do teste original: mesmo item de referência
# (MLB6296787236), mesma caixa sintética (5x5x5cm/8500g forçado, ~68 g/cm³)
# e mesmas dimensões do Chinelo real (13x28x39cm/601g declarado, peso cubado
# 2,366kg vira o peso efetivo), nos mesmos 3 preços (R$15/R$35/R$65).
#
# Antes de seguir testando hipóteses novas (ex: densidade extrema x categoria
# confirmada), este script faz a pergunta mais básica: o fenômeno AINDA é
# reproduzível hoje, nas condições exatas em que foi visto da última vez?
#
# Roda cada uma das 2 configurações de dimensão x 3 preços x 2 valores de
# free_shipping (false -- igual ao script original; true -- controle, já que
# o script original tinha uma variante "f" testando free_shipping=false que
# era redundante com o baseline, o que pode indicar bug de cópia e que o
# valor pretendido em algum ponto do fluxo real era "true").
# Total: 2 x 3 x 2 = 12 chamadas.
#
# Cada chamada roda isolada (try/except próprio). Só leitura -- não toca
# no banco, não grava nada além do arquivo de saída.

import argparse
import json
import sys
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

parser = argparse.ArgumentParser(
    description="Replicação literal do teste original que reproduziu discount.type=fs_optional."
)
parser.add_argument("--conta", default="MB", choices=["MB", "SV"])
parser.add_argument(
    "--item-referencia", default="MLB6296787236",
    help="MLB usado originalmente pra puxar category_id/listing_type_id/condition "
         "(mesmo item de investigar_reputacao_seller_status_abaixo_79.py).",
)
args = parser.parse_args()

CONTA = args.conta
ITEM_ID = args.item_referencia

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / "investigacao_replicacao_literal_fs_optional.json"

TOLERANCIA_REAIS = 0.02

# Valores esperados pela tabela real (TABELA_FRETE), linha "De 8 a 9 kg" pra
# caixa sintética e linha "De 2 a 3 kg" pro Chinelo (peso cubado 2,366kg cai
# nessa faixa) -- mesmos valores usados em investigar_reputacao_seller_status_abaixo_79.py.
DIMENSOES_TESTADAS = [
    {
        "nome": "caixa_sintetica_5x5x5_8500g",
        "dimensions_str": "5x5x5,8500",
        "densidade_g_cm3": round(8500 / (5 * 5 * 5), 2),
        "precos_esperados_tabela": {15.00: 6.95, 35.00: 9.35, 65.00: 10.65},
    },
    {
        "nome": "chinelo_dimensoes_reais_13x28x39_601g_declarado",
        "dimensions_str": "13x28x39,601",
        "densidade_g_cm3": round(601 / (13 * 28 * 39), 4),
        "precos_esperados_tabela": {15.00: 6.35, 35.00: 8.65, 65.00: 9.15},
    },
]

PRECOS_TESTE = [15.00, 35.00, 65.00]


def chamar_simulacao(user_id, params, nome_log):
    endpoint = f"/users/{user_id}/shipping_options/free"
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log=nome_log,
    )
    return resposta.json()


def avaliar_resposta(resposta_json, valor_esperado):
    coverage = resposta_json.get("coverage", {}).get("all_country", {})
    list_cost = coverage.get("list_cost")
    discount = coverage.get("discount")
    discount_type = discount.get("type") if isinstance(discount, dict) else discount
    return {
        "list_cost_retornado": list_cost,
        "list_cost_esperado_pela_tabela": valor_esperado,
        "valor_bateu": list_cost is not None and abs(list_cost - valor_esperado) <= TOLERANCIA_REAIS,
        "discount": discount,
        "discount_type": discount_type,
        "billable_weight_retornado_g": coverage.get("billable_weight"),
    }


resultado = {"contexto": {}, "testes": {}}

# --- user_id ---
try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_replicacao_literal_fs_optional",
    )
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao autenticar / obter user_id: {erro}")
    sys.exit(1)

# --- category_id/listing_type_id/condition do item de referência (mesmo item do teste original) ---
try:
    resposta_item = chamar_api(
        "GET", f"/items/{ITEM_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_replicacao_literal_fs_optional",
    )
    item = resposta_item.json()
    category_id = item.get("category_id")
    listing_type_id = item.get("listing_type_id")
    condition = item.get("condition", "new")
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao buscar atributos do item de referência {ITEM_ID}: {erro}")
    sys.exit(1)

resultado["contexto"] = {
    "conta": CONTA,
    "item_referencia": ITEM_ID,
    "category_id": category_id,
    "listing_type_id": listing_type_id,
    "condition": condition,
}
print(f"Item de referência {ITEM_ID}: category_id={category_id}, listing_type_id={listing_type_id}, condition={condition}")

# --- roda as 2 dimensões x 3 preços x 2 free_shipping ---
for config_dimensao in DIMENSOES_TESTADAS:
    resultado["testes"][config_dimensao["nome"]] = {
        "densidade_g_cm3": config_dimensao["densidade_g_cm3"],
        "precos": {},
    }
    for preco in PRECOS_TESTE:
        resultado["testes"][config_dimensao["nome"]]["precos"][f"R${preco:.2f}"] = {}
        for free_shipping_valor in ("false", "true"):
            params = {
                "dimensions": config_dimensao["dimensions_str"],
                "item_price": preco,
                "verbose": "true",
                "condition": condition,
                "category_id": category_id,
                "listing_type_id": listing_type_id,
                "mode": "me2",
                "free_shipping": free_shipping_valor,
            }
            valor_esperado = config_dimensao["precos_esperados_tabela"][preco]
            chave_fs = f"free_shipping_{free_shipping_valor}"
            try:
                resposta = chamar_simulacao(user_id, params, "investigar_replicacao_literal_fs_optional")
                resultado["testes"][config_dimensao["nome"]]["precos"][f"R${preco:.2f}"][chave_fs] = avaliar_resposta(resposta, valor_esperado)
            except (ErroAPI, ErroAutenticacaoAPI) as erro:
                resultado["testes"][config_dimensao["nome"]]["precos"][f"R${preco:.2f}"][chave_fs] = {"erro": str(erro)}

texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    f.write(texto_json_oculto)

# --- resumo ---
print("\n--- Resumo: discount.type por dimensão x preço x free_shipping ---")
total_fs_optional = 0
total_chamadas = 0
for nome_dimensao, dados_dimensao in resultado["testes"].items():
    print(f"\n{nome_dimensao} (densidade: {dados_dimensao['densidade_g_cm3']} g/cm³):")
    for preco_chave, variantes in dados_dimensao["precos"].items():
        partes = []
        for chave_fs, dados in variantes.items():
            tipo = dados.get("discount_type", dados.get("erro", "ERRO"))
            partes.append(f"{chave_fs}={tipo}")
            total_chamadas += 1
            if tipo == "fs_optional":
                total_fs_optional += 1
        print(f"  {preco_chave}: " + " | ".join(partes))

print(f"\nTotal: {total_fs_optional}/{total_chamadas} chamadas retornaram fs_optional.")
print(f"\nRetorno completo (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
print("Suba esse arquivo na conversa pra eu analisar.")