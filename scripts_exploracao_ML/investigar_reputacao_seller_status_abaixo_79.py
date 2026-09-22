# scripts_exploracao_ML/investigar_reputacao_seller_status_abaixo_79.py
#
# Objetivo: testar se os parâmetros seller_status / seller_type / reputation
# (documentados no endpoint shipping_options/free, mas não usados na receita
# já validada) mudam o resultado da simulação nos 3 casos que já sabemos que
# falham hoje (R$15, R$35, R$65 -- discount.type vem "fs_optional" em vez de
# "mandatory").
#
# Rodada 1 (já feita antes, sem efeito nenhum em nenhuma variante): caixa
# SINTÉTICA 5x5x5cm com peso forçado em 8500g (faixa "De 8 a 9 kg"),
# reproduzindo a PARTE 2 do script de validação original
# (investigar_frete_validacao_tabela_completa.py).
#
# Rodada 2 (nova, a pedido do Matheus): controla a hipótese de que a caixa
# SINTÉTICA pode estar distorcendo o teste -- usa as dimensões REAIS de
# envio do ERP do Chinelo F7899947307029.001 (13x28x39cm, peso declarado
# 601g, peso cubado 2.366kg -- cai na faixa "De 2 a 3 kg").
#
# Nota sobre essa hipótese: na validação ORIGINAL (Parte 1, preço fixo
# R$378,90, ≥R$79), a MESMA caixa sintética 5x5x5cm bateu 30/30 contra a
# tabela real, em 30 faixas de peso diferentes -- ou seja, já existe
# evidência de que a caixa sintética reproduz o cálculo certo no regime
# "mandatory". Isso não descarta a hipótese (o problema pode só aparecer
# abaixo de R$79), mas é por isso que os 2 datasets rodam lado a lado no
# mesmo JSON, em vez de simplesmente substituir um pelo outro.
#
# Cada chamada roda isolada (try/except próprio). Só leitura -- não toca
# no banco, não grava nada além do arquivo de saída.

import json
import re
import sys
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"
ITEM_ID = "MLB6296787236"          # item de referência pra category_id/listing_type_id/condition
                                     # (mantido fixo nas 2 rodadas pra não misturar 2 variáveis no mesmo teste)

# Rodada 1 -- caixa sintética (já testada antes, mantida aqui pra reprodutibilidade)
DIMENSAO_BASE_CM = "5x5x5"
PESO_FIXO_GRAMAS = 8500             # faixa "De 8 a 9 kg"

# Rodada 2 -- dimensões REAIS do Chinelo F7899947307029.001 (ERP)
DIMENSAO_CHINELO_CM = "13x28x39"
PESO_DECLARADO_CHINELO_GRAMAS = 601  # peso do ERP -- API calcula o cubado (2.366kg) e pega o maior

TOLERANCIA_REAIS = 0.02

# NÃO documentado em nenhuma doc oficial -- achado só como tag "eshop" na
# conta MB (ver 'loja_oficial'.'tags' no JSON da rodada anterior). Chute
# educado pro valor de seller_type de loja oficial, testado isolado abaixo
# só pra ver se muda alguma coisa -- não vira padrão sem confirmação.
SELLER_TYPE_ESPECULATIVO = "eshop"
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / "investigacao_reputacao_seller_status_abaixo_79.json"

CASOS_QUE_FALHAM_CAIXA_SINTETICA = [
    {"chave": "0_a_18.99",  "preco_teste": 15.00, "list_cost_esperado_pela_tabela": 6.95},
    {"chave": "19_a_48.99", "preco_teste": 35.00, "list_cost_esperado_pela_tabela": 9.35},
    {"chave": "49_a_78.99", "preco_teste": 65.00, "list_cost_esperado_pela_tabela": 10.65},
]
CASOS_QUE_FALHAM_CHINELO = [
    {"chave": "0_a_18.99",  "preco_teste": 15.00, "list_cost_esperado_pela_tabela": 6.35},
    {"chave": "19_a_48.99", "preco_teste": 35.00, "list_cost_esperado_pela_tabela": 8.65},
    {"chave": "49_a_78.99", "preco_teste": 65.00, "list_cost_esperado_pela_tabela": 9.15},
]


def chamar_simulacao(user_id, params, nome_log):
    endpoint = f"/users/{user_id}/shipping_options/free"
    resposta = chamar_api(
        "GET", endpoint,
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params,
        nome_log=nome_log,
    )
    return resposta.json()


def montar_params_baseline(category_id, listing_type_id, condition, dimensions_str, preco):
    # Receita já validada -- agora recebe a string "dimensions" pronta (LxAxCx,PESOg)
    # em vez de montar a partir de uma caixa fixa -- serve tanto pra caixa sintética
    # quanto pra dimensões reais de um produto.
    return {
        "dimensions": dimensions_str,
        "item_price": preco,
        "verbose": "true",
        "condition": condition,
        "category_id": category_id,
        "listing_type_id": listing_type_id,
        "mode": "me2",
        "free_shipping": "false",
    }


def avaliar_resposta(resposta_json, valor_esperado):
    coverage = resposta_json.get("coverage", {}).get("all_country", {})
    list_cost = coverage.get("list_cost")
    discount = coverage.get("discount")

    valor_bateu = (
        list_cost is not None
        and abs(list_cost - valor_esperado) <= TOLERANCIA_REAIS
    )

    return {
        "list_cost_retornado": list_cost,
        "list_cost_esperado_pela_tabela": valor_esperado,
        "valor_bateu": valor_bateu,
        "discount": discount,
        "billable_weight_retornado_g": coverage.get("billable_weight"),
    }


def rodar_variantes(user_id, category_id, listing_type_id, condition, dimensions_str, preco, esperado,
                     seller_type, power_seller_status, reputation_cor, nome_log):
    """Roda as 5 variantes (a-e) pra 1 combinação de dimensão+preço, retorna o dict de resultado."""
    saida = {"item_price_testado": preco}
    params_base = montar_params_baseline(category_id, listing_type_id, condition, dimensions_str, preco)

    # a) baseline -- reconfirma a falha já conhecida
    try:
        resposta = chamar_simulacao(user_id, params_base, nome_log)
        saida["a_baseline_sem_parametros_novos"] = avaliar_resposta(resposta, esperado)
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        saida["a_baseline_sem_parametros_novos"] = {"erro": str(erro)}

    # b) + reputation apenas
    params_reputation = dict(params_base)
    if reputation_cor:
        params_reputation["reputation"] = reputation_cor
        try:
            resposta = chamar_simulacao(user_id, params_reputation, nome_log)
            saida["b_mais_reputation"] = avaliar_resposta(resposta, esperado)
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            saida["b_mais_reputation"] = {"erro": str(erro)}
    else:
        saida["b_mais_reputation"] = "pulado -- conta sem level_id"

    # c) + reputation + seller_status (+ seller_type só se confirmado -- ver Passo 0)
    params_completo = dict(params_reputation)
    if seller_type:
        params_completo["seller_type"] = seller_type
    if power_seller_status:
        params_completo["seller_status"] = power_seller_status
    try:
        resposta = chamar_simulacao(user_id, params_completo, nome_log)
        saida["c_combo_completo"] = avaliar_resposta(resposta, esperado)
        saida["c_combo_completo_params_usados"] = {
            k: v for k, v in params_completo.items() if k in ("reputation", "seller_status", "seller_type")
        }
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        saida["c_combo_completo"] = {"erro": str(erro)}

    # d) + seller_type ESPECULATIVO sozinho (isola o efeito dele, sem reputation/seller_status)
    params_seller_type_especulativo = dict(params_base)
    params_seller_type_especulativo["seller_type"] = SELLER_TYPE_ESPECULATIVO
    try:
        resposta = chamar_simulacao(user_id, params_seller_type_especulativo, nome_log)
        saida["d_seller_type_especulativo_isolado"] = avaliar_resposta(resposta, esperado)
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        saida["d_seller_type_especulativo_isolado"] = {"erro": str(erro)}

    # e) tudo junto -- reputation + seller_status + seller_type ESPECULATIVO
    params_tudo_junto = dict(params_reputation)
    if power_seller_status:
        params_tudo_junto["seller_status"] = power_seller_status
    params_tudo_junto["seller_type"] = SELLER_TYPE_ESPECULATIVO
    try:
        resposta = chamar_simulacao(user_id, params_tudo_junto, nome_log)
        saida["e_tudo_junto_com_seller_type_especulativo"] = avaliar_resposta(resposta, esperado)
        saida["e_tudo_junto_params_usados"] = {
            k: v for k, v in params_tudo_junto.items() if k in ("reputation", "seller_status", "seller_type")
        }
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        saida["e_tudo_junto_com_seller_type_especulativo"] = {"erro": str(erro)}

    # f) free_shipping=false -- a doc de custos pro vendedor (Central de Ajuda) mostra que
    # existem 2 tabelas diferentes abaixo de R$79: a "padrão" (que já usamos, TABELA_FRETE)
    # e uma "frete grátis rápido, opcional" -- que bate exatamente com o valor "piso" que a
    # API vem devolvendo. free_shipping="true" pode estar fazendo a API assumir que o
    # vendedor optou pelo modo rápido opcional -- testando com False pra ver se destrava
    # o valor padrão.
    params_free_shipping_false = dict(params_base)
    params_free_shipping_false["free_shipping"] = "false"
    try:
        resposta = chamar_simulacao(user_id, params_free_shipping_false, nome_log)
        saida["f_free_shipping_false"] = avaliar_resposta(resposta, esperado)
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        saida["f_free_shipping_false"] = {"erro": str(erro)}

    return saida


resultado = {"contexto": {}, "casos_caixa_sintetica_8500g": {}, "casos_chinelo_dimensoes_reais": {}}

# --- Passo 0: user_id + checar se é Loja Oficial (define seller_type) ---
try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_reputacao_seller_status",
    )
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao autenticar / obter user_id: {erro}")
    sys.exit(1)

seller_type = None
info_loja_oficial = None
try:
    resposta_brands = chamar_api(
        "GET", f"/users/{user_id}/brands",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_reputacao_seller_status",
    )
    info_loja_oficial = resposta_brands.json()
    print("A conta VEIO VINCULADA a uma Loja Oficial (ver 'loja_oficial' no JSON de saída).")
    print("seller_type fica de fora desta rodada (valor pra loja oficial ainda não confirmado).")
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    if "Erro 404" in str(erro):
        seller_type = "normal"
        print("Conta NÃO vinculada a Loja Oficial (404 em /brands) -- seller_type = 'normal'.")
    else:
        print(f"Erro inesperado ao checar /brands (não é o 404 esperado): {erro}")
        print("Script parado -- revisar antes de continuar.")
        sys.exit(1)

# --- Passo 1: reputação real da conta ---
try:
    resposta_user = chamar_api(
        "GET", f"/users/{user_id}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_reputacao_seller_status",
    )
    seller_reputation = resposta_user.json().get("seller_reputation", {})
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao buscar seller_reputation: {erro}")
    sys.exit(1)

level_id = seller_reputation.get("level_id")
power_seller_status = seller_reputation.get("power_seller_status")

reputation_cor = None
if level_id:
    match = re.match(r"^\d+_(.+)$", level_id)
    reputation_cor = match.group(1) if match else level_id

resultado["contexto"] = {
    "seller_type_usado": seller_type,
    "loja_oficial": info_loja_oficial,
    "level_id_bruto": level_id,
    "reputation_derivada": reputation_cor,
    "power_seller_status_bruto": power_seller_status,
}

if not reputation_cor:
    print("Conta sem level_id de reputação -- não dá pra testar o parâmetro 'reputation'.")
if not power_seller_status:
    print("Conta sem power_seller_status (não é Mercado Líder) -- não dá pra testar 'seller_status'.")

# --- Passo 2: category_id/listing_type_id/condition do item de referência ---
try:
    resposta_item = chamar_api(
        "GET", f"/items/{ITEM_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_reputacao_seller_status",
    )
    item = resposta_item.json()
    category_id = item.get("category_id")
    listing_type_id = item.get("listing_type_id")
    condition = item.get("condition", "new")
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao buscar atributos do item: {erro}")
    sys.exit(1)

resultado["contexto"].update({
    "category_id": category_id,
    "listing_type_id": listing_type_id,
    "condition": condition,
    "dimensao_caixa_sintetica_cm": DIMENSAO_BASE_CM,
    "peso_fixo_caixa_sintetica_gramas": PESO_FIXO_GRAMAS,
    "dimensao_chinelo_cm": DIMENSAO_CHINELO_CM,
    "peso_declarado_chinelo_gramas": PESO_DECLARADO_CHINELO_GRAMAS,
})

# --- Passo 3a: roda os 3 casos com a caixa SINTÉTICA (rodada 1, reprodutibilidade) ---
dimensions_caixa_sintetica = f"{DIMENSAO_BASE_CM},{PESO_FIXO_GRAMAS}"
for caso in CASOS_QUE_FALHAM_CAIXA_SINTETICA:
    resultado["casos_caixa_sintetica_8500g"][caso["chave"]] = rodar_variantes(
        user_id, category_id, listing_type_id, condition,
        dimensions_caixa_sintetica, caso["preco_teste"], caso["list_cost_esperado_pela_tabela"],
        seller_type, power_seller_status, reputation_cor,
        "investigar_reputacao_seller_status_caixa_sintetica",
    )

# --- Passo 3b: roda os 3 casos com as dimensões REAIS do Chinelo (rodada 2, controle) ---
dimensions_chinelo = f"{DIMENSAO_CHINELO_CM},{PESO_DECLARADO_CHINELO_GRAMAS}"
for caso in CASOS_QUE_FALHAM_CHINELO:
    resultado["casos_chinelo_dimensoes_reais"][caso["chave"]] = rodar_variantes(
        user_id, category_id, listing_type_id, condition,
        dimensions_chinelo, caso["preco_teste"], caso["list_cost_esperado_pela_tabela"],
        seller_type, power_seller_status, reputation_cor,
        "investigar_reputacao_seller_status_chinelo",
    )

texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    f.write(texto_json_oculto)


def imprimir_resumo(nome_dataset, casos):
    print(f"\n--- Resumo: {nome_dataset} ---")
    for chave, dados in casos.items():
        preco = dados.get("item_price_testado")
        a = dados.get("a_baseline_sem_parametros_novos", {})
        b = dados.get("b_mais_reputation", {})
        c = dados.get("c_combo_completo", {})
        d = dados.get("d_seller_type_especulativo_isolado", {})
        e = dados.get("e_tudo_junto_com_seller_type_especulativo", {})
        f = dados.get("f_free_shipping_false", {})
        a_tipo = a.get("discount", {}).get("type") if isinstance(a.get("discount"), dict) else a.get("discount")
        b_tipo = b.get("discount", {}).get("type") if isinstance(b, dict) and isinstance(b.get("discount"), dict) else None
        c_tipo = c.get("discount", {}).get("type") if isinstance(c.get("discount"), dict) else c.get("discount")
        d_tipo = d.get("discount", {}).get("type") if isinstance(d.get("discount"), dict) else d.get("discount")
        e_tipo = e.get("discount", {}).get("type") if isinstance(e.get("discount"), dict) else e.get("discount")
        f_tipo = f.get("discount", {}).get("type") if isinstance(f.get("discount"), dict) else f.get("discount")
        f_custo = f.get("list_cost_retornado")
        print(
            f"{chave} (R${preco}): baseline={a_tipo} | +reputation={b_tipo} | "
            f"+reputation+seller_status={c_tipo} | +seller_type(eshop) isolado={d_tipo} | "
            f"tudo junto={e_tipo} | free_shipping=false: type={f_tipo} list_cost={f_custo}"
        )


imprimir_resumo("caixa sintética 5x5x5cm / 8500g", resultado["casos_caixa_sintetica_8500g"])
imprimir_resumo("Chinelo -- dimensões reais 13x28x39cm / 601g declarado", resultado["casos_chinelo_dimensoes_reais"])

print(f"\nRetorno completo (com seu user_id oculto) salvo em: {CAMINHO_SAIDA}")
print("Suba esse arquivo na conversa pra eu analisar.")