# scripts_exploracao_ML/investigar_frete_validacao_tabela_completa.py
#
# Objetivo ÚNICO: validar a simulação de frete (shipping_options/free,
# sem item_id) contra a tabela de frete REAL que o sistema já usa hoje
# (Tabela_Frete_Mercado_Livre.xlsx — 30 faixas de peso x 8 faixas de
# valor), em 3 partes:
#
#   PARTE 1: preço FIXO, percorre TODAS as 30 faixas de peso da tabela
#   PARTE 2: peso FIXO, percorre as 8 faixas de valor da tabela
#   PARTE 3: combinações "aleatórias" do meio da tabela (peso e valor
#            variando juntos), pra checar se o lookup está correto de
#            forma geral, não só nos extremos
#
# Pra cada chamada, o script já compara o list_cost retornado com o
# valor esperado da tabela (mesma célula peso x preço), E confere se o
# billable_weight retornado caiu na faixa de peso pretendida — porque
# já vimos um caso em que o valor bateu com uma célula da tabela, mas
# era a célula ERRADA (faixa de peso diferente da que a gente queria
# testar).
#
# Usa o combo já validado: category_id/listing_type_id/condition reais
# do MLB5838465508, mode=me2, SEM logistic_type, caixa fixa 5x5x5cm
# (peso cúbico ~21g, desprezível em qualquer faixa de peso testada).
#
# Cada chamada roda isolada (try/except próprio).
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
ITEM_ID = "MLB5838465508"          # usado só pra puxar category_id/listing_type_id/condition reais

DIMENSAO_BASE_CM = "5x5x5"          # caixa mínima, cubagem ~21g, desprezível em qualquer faixa
TOLERANCIA_REAIS = 0.02             # tolerância de arredondamento na comparação

# Preço usado na PARTE 1 (percorre peso) — dentro da faixa "a partir de R$200",
# já validado antes contra o item real.
PRECO_FIXO_PARTE_1 = 378.90

# Faixa de peso usada na PARTE 2 (percorre preço) — "De 8 a 9 kg", a mesma
# faixa do item real MLB5838465508 (8802g), pra manter ancorado num caso já validado.
PESO_FIXO_PARTE_2_GRAMAS = 8500
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_frete_validacao_tabela_{ITEM_ID}.json"

# Colunas de preço na MESMA ordem da planilha, com um valor de teste
# representativo dentro de cada faixa.
COLUNAS_PRECO = [
    {"chave": "0_a_18.99",        "preco_teste": 15.00},
    {"chave": "19_a_48.99",       "preco_teste": 35.00},
    {"chave": "49_a_78.99",       "preco_teste": 65.00},
    {"chave": "79_a_99.99",       "preco_teste": 90.00},
    {"chave": "100_a_119.99",     "preco_teste": 110.00},
    {"chave": "120_a_149.99",     "preco_teste": 135.00},
    {"chave": "150_a_199.99",     "preco_teste": 175.00},
    {"chave": "a_partir_de_200",  "preco_teste": 250.00},
]

# Tabela real completa, extraída de Tabela_Frete_Mercado_Livre.xlsx.
# "precos" segue a MESMA ordem de COLUNAS_PRECO acima.
TABELA_FRETE = [
    {"nome": "Até 0,3 kg",        "peso_min": 0,   "peso_max": 0.3, "precos": [5.65, 6.85, 8.15, 12.95, 14.95, 16.95, 19.05, 21.65]},
    {"nome": "De 0,3 a 0,5 kg",   "peso_min": 0.3, "peso_max": 0.5, "precos": [5.95, 6.95, 8.25, 13.85, 16.15, 18.15, 20.45, 23.25]},
    {"nome": "De 0,5 a 1 kg",     "peso_min": 0.5, "peso_max": 1,   "precos": [6.05, 7.15, 8.45, 14.45, 16.85, 19.05, 21.35, 24.45]},
    {"nome": "De 1 a 1,5 kg",     "peso_min": 1,   "peso_max": 1.5, "precos": [6.15, 7.35, 8.65, 14.75, 17.15, 19.45, 21.75, 25.45]},
    {"nome": "De 1,5 a 2 kg",     "peso_min": 1.5, "peso_max": 2,   "precos": [6.25, 7.45, 8.75, 15.05, 17.65, 19.85, 22.25, 25.55]},
    {"nome": "De 2 a 3 kg",       "peso_min": 2,   "peso_max": 3,   "precos": [6.35, 8.65, 9.15, 16.45, 19.15, 21.65, 24.35, 27.05]},
    {"nome": "De 3 a 4 kg",       "peso_min": 3,   "peso_max": 4,   "precos": [6.45, 8.75, 9.75, 17.85, 20.75, 23.35, 26.35, 29.25]},
    {"nome": "De 4 a 5 kg",       "peso_min": 4,   "peso_max": 5,   "precos": [6.55, 8.85, 10.25, 19.75, 22.85, 26.05, 29.25, 32.45]},
    {"nome": "De 5 a 6 kg",       "peso_min": 5,   "peso_max": 6,   "precos": [6.65, 8.95, 10.35, 25.95, 29.15, 33.35, 36.45, 40.85]},
    {"nome": "De 6 a 7 kg",       "peso_min": 6,   "peso_max": 7,   "precos": [6.75, 9.05, 10.45, 27.55, 31.65, 36.75, 40.85, 45.25]},
    {"nome": "De 7 a 8 kg",       "peso_min": 7,   "peso_max": 8,   "precos": [6.85, 9.25, 10.55, 29.45, 34.35, 39.25, 44.15, 49.35]},
    {"nome": "De 8 a 9 kg",       "peso_min": 8,   "peso_max": 9,   "precos": [6.95, 9.35, 10.65, 30.25, 35.25, 40.35, 45.35, 50.75]},
    {"nome": "De 9 a 10 kg",      "peso_min": 9,   "peso_max": 10,  "precos": [7.05, 9.45, 10.85, 38.25, 45.05, 51.95, 58.75, 65.85]},
    {"nome": "De 10 a 11 kg",     "peso_min": 10,  "peso_max": 11,  "precos": [7.05, 9.65, 11.05, 41.65, 48.55, 55.45, 62.35, 69.35]},
    {"nome": "De 11 a 13 kg",     "peso_min": 11,  "peso_max": 13,  "precos": [7.15, 10.05, 11.45, 42.55, 49.75, 56.85, 63.85, 70.95]},
    {"nome": "De 13 a 15 kg",     "peso_min": 13,  "peso_max": 15,  "precos": [7.25, 10.25, 11.65, 45.55, 52.95, 60.55, 68.15, 75.65]},
    {"nome": "De 15 a 17 kg",     "peso_min": 15,  "peso_max": 17,  "precos": [7.35, 10.45, 11.85, 48.95, 56.55, 64.05, 71.35, 79.35]},
    {"nome": "De 17 a 20 kg",     "peso_min": 17,  "peso_max": 20,  "precos": [7.45, 10.65, 12.05, 55.15, 64.35, 73.55, 82.75, 91.95]},
    {"nome": "De 20 a 25 kg",     "peso_min": 20,  "peso_max": 25,  "precos": [7.65, 11.05, 12.25, 64.55, 75.75, 85.45, 96.25, 106.85]},
    {"nome": "De 25 a 30 kg",     "peso_min": 25,  "peso_max": 30,  "precos": [7.75, 11.25, 12.45, 66.45, 76.05, 86.25, 97.15, 107.85]},
    {"nome": "De 30 a 40 kg",     "peso_min": 30,  "peso_max": 40,  "precos": [7.85, 11.45, 12.65, 68.35, 79.65, 89.75, 100.05, 107.95]},
    {"nome": "De 40 a 50 kg",     "peso_min": 40,  "peso_max": 50,  "precos": [7.95, 11.65, 12.85, 70.95, 81.85, 92.85, 103.45, 111.65]},
    {"nome": "De 50 a 60 kg",     "peso_min": 50,  "peso_max": 60,  "precos": [8.05, 11.85, 13.05, 75.55, 87.25, 99.05, 110.25, 119.05]},
    {"nome": "De 60 a 70 kg",     "peso_min": 60,  "peso_max": 70,  "precos": [8.15, 12.05, 13.25, 80.95, 93.75, 105.95, 118.05, 127.45]},
    {"nome": "De 70 a 80 kg",     "peso_min": 70,  "peso_max": 80,  "precos": [8.25, 12.25, 13.45, 84.65, 97.95, 110.75, 123.35, 133.15]},
    {"nome": "De 80 a 90 kg",     "peso_min": 80,  "peso_max": 90,  "precos": [8.35, 12.45, 13.65, 94.05, 108.35, 122.95, 136.95, 147.85]},
    {"nome": "De 90 a 100 kg",    "peso_min": 90,  "peso_max": 100, "precos": [8.45, 12.65, 13.85, 107.45, 124.85, 140.45, 156.45, 168.85]},
    {"nome": "De 100 a 125 kg",   "peso_min": 100, "peso_max": 125, "precos": [8.55, 12.85, 14.05, 120.15, 138.95, 156.95, 174.85, 188.85]},
    {"nome": "De 125 a 150 kg",   "peso_min": 125, "peso_max": 150, "precos": [8.65, 12.85, 14.25, 127.45, 147.05, 166.55, 185.55, 200.35]},
    {"nome": "Mais de 150 kg",    "peso_min": 150, "peso_max": None, "precos": [8.75, 12.85, 14.45, 167.05, 193.35, 218.45, 243.45, 262.85]},
]

# PARTE 3: combinações do meio da tabela (índice da linha em TABELA_FRETE,
# índice da coluna em COLUNAS_PRECO), pra cruzar peso e preço variando juntos.
COMBINACOES_ALEATORIAS_MEIO = [
    (6, 3),    # De 3 a 4 kg   x R$79 a R$99,99      -> esperado 17.85
    (12, 4),   # De 9 a 10 kg  x R$100 a R$119,99     -> esperado 45.05
    (18, 2),   # De 20 a 25 kg x R$49 a R$78,99       -> esperado 12.25
    (23, 6),   # De 60 a 70 kg x R$150 a R$199,99     -> esperado 118.05
    (14, 7),   # De 11 a 13 kg x A partir de R$200    -> esperado 70.95
    (21, 0),   # De 40 a 50 kg x R$0 a R$18,99        -> esperado 7.95
]


def peso_representativo_gramas(peso_min_kg, peso_max_kg):
    if peso_max_kg is None:
        return int((peso_min_kg + 30) * 1000)   # acima de 150kg, testa um valor plausível (180kg)
    return int(((peso_min_kg + peso_max_kg) / 2) * 1000)


def chamar_simulacao(user_id, params, nome_log):
    endpoint = f"/users/{user_id}/shipping_options/free"
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log=nome_log,
    )
    return resposta.json()


def montar_params(category_id, listing_type_id, condition, peso_gramas, preco):
    return {
        "dimensions": f"{DIMENSAO_BASE_CM},{peso_gramas}",
        "item_price": preco,
        "verbose": "true",
        "condition": condition,
        "category_id": category_id,
        "listing_type_id": listing_type_id,
        "mode": "me2",
        "free_shipping": "false",
    }


def aplicar_teto_produtos_baratos(valor_nominal_tabela, item_price):
    # Regra oficial do ML (doc "Custos dos Envios no Mercado Livre para
    # MercadoLíder, reputação verde ou sem reputação", rodapé da tabela
    # principal): "Os produtos de menos de R$19 pagam no máximo metade
    # do preço do produto". O valor nominal da tabela (peso x faixa de
    # preço) só vale como teto máximo pra item_price < 19 — o custo real
    # é o menor entre os dois.
    if item_price < 19:
        return min(valor_nominal_tabela, item_price / 2)
    return valor_nominal_tabela


def avaliar_resposta(resposta_json, valor_nominal_tabela, peso_min_kg, peso_max_kg, item_price):
    coverage = resposta_json.get("coverage", {}).get("all_country", {})
    list_cost = coverage.get("list_cost")
    billable_weight_g = coverage.get("billable_weight")

    valor_esperado = aplicar_teto_produtos_baratos(valor_nominal_tabela, item_price)
    teto_metade_preco_aplicado = valor_esperado != valor_nominal_tabela

    valor_bateu = (
        list_cost is not None
        and abs(list_cost - valor_esperado) <= TOLERANCIA_REAIS
    )

    faixa_peso_bateu = None
    if billable_weight_g is not None:
        peso_retornado_kg = billable_weight_g / 1000
        dentro_do_minimo = peso_retornado_kg >= peso_min_kg
        dentro_do_maximo = peso_max_kg is None or peso_retornado_kg < peso_max_kg
        faixa_peso_bateu = dentro_do_minimo and dentro_do_maximo

    return {
        "list_cost_retornado": list_cost,
        "list_cost_nominal_da_tabela": valor_nominal_tabela,
        "teto_metade_preco_aplicado": teto_metade_preco_aplicado,
        "list_cost_esperado_pela_tabela": valor_esperado,
        "valor_bateu": valor_bateu,
        "billable_weight_retornado_g": billable_weight_g,
        "faixa_de_peso_pretendida": f"{peso_min_kg} a {peso_max_kg if peso_max_kg is not None else '∞'} kg",
        "billable_weight_caiu_na_faixa_certa": faixa_peso_bateu,
        "discount": coverage.get("discount"),
    }


resultado = {"contexto": {}, "parte_1_preco_fixo_percorre_peso": {}, "parte_2_peso_fixo_percorre_preco": {}, "parte_3_combinacoes_meio_da_tabela": {}}

try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_frete_validacao_tabela",
    )
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao autenticar / obter user_id: {erro}")
    sys.exit(1)

try:
    resposta_item = chamar_api(
        "GET", f"/items/{ITEM_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_frete_validacao_tabela",
    )
    item = resposta_item.json()
    category_id = item.get("category_id")
    listing_type_id = item.get("listing_type_id")
    condition = item.get("condition", "new")
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao buscar atributos do item: {erro}")
    sys.exit(1)

resultado["contexto"] = {
    "category_id": category_id,
    "listing_type_id": listing_type_id,
    "condition": condition,
    "dimensao_base_cm": DIMENSAO_BASE_CM,
}

# --- PARTE 1: preço fixo, percorre as 30 faixas de peso ---
indice_coluna_preco_fixo_parte_1 = 7  # "a_partir_de_200", onde PRECO_FIXO_PARTE_1 se encaixa
for linha in TABELA_FRETE:
    peso_gramas = peso_representativo_gramas(linha["peso_min"], linha["peso_max"])
    params = montar_params(category_id, listing_type_id, condition, peso_gramas, PRECO_FIXO_PARTE_1)
    chave = linha["nome"]
    try:
        resposta = chamar_simulacao(user_id, params, "investigar_frete_validacao_tabela")
        avaliacao = avaliar_resposta(
            resposta,
            linha["precos"][indice_coluna_preco_fixo_parte_1],
            linha["peso_min"], linha["peso_max"],
            PRECO_FIXO_PARTE_1,
        )
        resultado["parte_1_preco_fixo_percorre_peso"][chave] = {
            "peso_testado_gramas": peso_gramas,
            "item_price_testado": PRECO_FIXO_PARTE_1,
            **avaliacao,
        }
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultado["parte_1_preco_fixo_percorre_peso"][chave] = {"erro": str(erro)}

# --- PARTE 2: peso fixo, percorre as 8 faixas de preço ---
linha_peso_fixo = next(l for l in TABELA_FRETE if l["nome"] == "De 8 a 9 kg")
for indice_coluna, coluna in enumerate(COLUNAS_PRECO):
    params = montar_params(category_id, listing_type_id, condition, PESO_FIXO_PARTE_2_GRAMAS, coluna["preco_teste"])
    chave = coluna["chave"]
    try:
        resposta = chamar_simulacao(user_id, params, "investigar_frete_validacao_tabela")
        avaliacao = avaliar_resposta(
            resposta,
            linha_peso_fixo["precos"][indice_coluna],
            linha_peso_fixo["peso_min"], linha_peso_fixo["peso_max"],
            coluna["preco_teste"],
        )
        resultado["parte_2_peso_fixo_percorre_preco"][chave] = {
            "peso_testado_gramas": PESO_FIXO_PARTE_2_GRAMAS,
            "item_price_testado": coluna["preco_teste"],
            **avaliacao,
        }
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultado["parte_2_peso_fixo_percorre_preco"][chave] = {"erro": str(erro)}

# --- PARTE 3: combinações "aleatórias" do meio da tabela ---
for indice_linha, indice_coluna in COMBINACOES_ALEATORIAS_MEIO:
    linha = TABELA_FRETE[indice_linha]
    coluna = COLUNAS_PRECO[indice_coluna]
    peso_gramas = peso_representativo_gramas(linha["peso_min"], linha["peso_max"])
    params = montar_params(category_id, listing_type_id, condition, peso_gramas, coluna["preco_teste"])
    chave = f"{linha['nome']} x {coluna['chave']}"
    try:
        resposta = chamar_simulacao(user_id, params, "investigar_frete_validacao_tabela")
        avaliacao = avaliar_resposta(
            resposta,
            linha["precos"][indice_coluna],
            linha["peso_min"], linha["peso_max"],
            coluna["preco_teste"],
        )
        resultado["parte_3_combinacoes_meio_da_tabela"][chave] = {
            "peso_testado_gramas": peso_gramas,
            "item_price_testado": coluna["preco_teste"],
            **avaliacao,
        }
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        resultado["parte_3_combinacoes_meio_da_tabela"][chave] = {"erro": str(erro)}

texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    f.write(texto_json_oculto)

# Resumo rápido no console
for nome_parte, testes in resultado.items():
    if not isinstance(testes, dict) or nome_parte == "contexto":
        continue
    total = len(testes)
    bateram = sum(1 for t in testes.values() if t.get("valor_bateu"))
    print(f"{nome_parte}: {bateram}/{total} bateram o valor esperado")

print(f"\nRetorno completo (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
print("Suba esse arquivo na conversa pra eu analisar.")