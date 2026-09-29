# scripts_exploracao_ML/validar_estabilidade_listing_prices_top_repetidos.py
#
# Objetivo: confirmar que a comissão devolvida por /sites/MLB/listing_prices
# é realmente a mesma pra chamadas repetidas com os MESMOS parâmetros
# (price, category_id, listing_type_id) -- premissa por trás do cache
# cross-produto proposto pra buscar_comissao_real_ml (achado do script
# anterior: 57,8% das chamadas da última rodada real eram duplicatas exatas
# dessa tupla).
#
# Pega as N combinações mais repetidas do log real (mesma contagem de
# medir_duplicidade_listing_prices_via_log.py) e rechama cada uma 3x ao
# vivo, direto na API -- mesmo padrão de validação já usado pro cache do
# frete (Frente A, seção 20: "5 combinações mais repetidas... reconsultadas
# 3x cada... 5/5 determinísticas").
#
# Cada chamada roda isolada (try/except próprio). Só leitura -- não toca
# no banco, não grava nada além do arquivo de saída.

import argparse
import ast
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

NOME_PASTA_POR_EMPRESA = {'magazine': 'Magazine', 'samvale': 'Samvale'}
CONTA_POR_EMPRESA = {'magazine': 'MB', 'samvale': 'SV'}

parser = argparse.ArgumentParser(
    description="Rechama ao vivo as combinações mais repetidas de listing_prices, checando estabilidade."
)
parser.add_argument("--empresa", required=True, choices=list(NOME_PASTA_POR_EMPRESA), help="magazine ou samvale")
parser.add_argument("--log", default=None, help="Caminho do log (default: o mesmo do script de medição).")
parser.add_argument("--top", type=int, default=5, help="Quantas combinações mais repetidas testar (default 5).")
parser.add_argument("--repeticoes", type=int, default=3, help="Quantas vezes rechamar cada combinação (default 3).")
args = parser.parse_args()

CONTA = CONTA_POR_EMPRESA[args.empresa]

if args.log:
    caminho_log = Path(args.log)
else:
    pasta_empresa = NOME_PASTA_POR_EMPRESA[args.empresa]
    caminho_log = _RAIZ_DO_PROJETO / 'integracao_mercado_livre' / 'logs' / pasta_empresa / 'buscar_comissao_real_ml.log'

if not caminho_log.exists():
    print(f"Log não encontrado em: {caminho_log}")
    raise SystemExit(1)

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / "investigacao_estabilidade_listing_prices.json"

PADRAO_LINHA = re.compile(r"Chamando GET /sites/MLB/listing_prices \| (\{.*\})\s*$")


def contar_combinacoes(caminho):
    chaves = Counter()
    with open(caminho, "r", encoding="utf-8") as f:
        for linha in f:
            m = PADRAO_LINHA.search(linha)
            if not m:
                continue
            try:
                dados = ast.literal_eval(m.group(1))
            except (ValueError, SyntaxError):
                continue
            if dados.get("tentativa") != 1:
                continue
            params = dados.get("params") or {}
            chave = (params.get("price"), params.get("category_id"), params.get("listing_type_id"))
            if None in chave:
                continue
            chaves[chave] += 1
    return chaves


def chamar_listing_prices(price_str, category_id, listing_type_id):
    resposta = chamar_api(
        "GET", "/sites/MLB/listing_prices",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={"price": price_str, "category_id": category_id, "listing_type_id": listing_type_id},
        nome_log="validar_estabilidade_listing_prices",
    )
    corpo = resposta.json()
    if isinstance(corpo, list):
        corpo = corpo[0] if corpo else {}
    detalhes = corpo.get("sale_fee_details") or {}
    return {
        "sale_fee_amount": corpo.get("sale_fee_amount"),
        "percentage_fee": detalhes.get("percentage_fee"),
    }


chaves = contar_combinacoes(caminho_log)
top_n = chaves.most_common(args.top)

print(f"Log lido: {caminho_log}")
print(f"Testando as {len(top_n)} combinações mais repetidas, {args.repeticoes}x cada (ao vivo)...\n")

resultado = {"combinacoes_testadas": []}
todas_deterministicas = True

for (price_str, category_id, listing_type_id), qtd_no_log in top_n:
    print(f"price={price_str} category_id={category_id} listing_type_id={listing_type_id} ({qtd_no_log}x no log)")
    chamadas = []
    for tentativa in range(1, args.repeticoes + 1):
        try:
            r = chamar_listing_prices(price_str, category_id, listing_type_id)
            chamadas.append(r)
            print(f"  tentativa {tentativa}: percentage_fee={r['percentage_fee']}  sale_fee_amount={r['sale_fee_amount']}")
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            chamadas.append({"erro": str(erro)})
            print(f"  tentativa {tentativa}: ERRO — {erro}")
        time.sleep(0.3)

    percentuais = {c.get("percentage_fee") for c in chamadas if "erro" not in c}
    deterministico = len(percentuais) <= 1
    if not deterministico:
        todas_deterministicas = False
    print(f"  → {'ESTÁVEL' if deterministico else 'DIVERGIU'}\n")

    resultado["combinacoes_testadas"].append({
        "price": price_str, "category_id": category_id, "listing_type_id": listing_type_id,
        "qtd_no_log": qtd_no_log, "chamadas": chamadas, "deterministico": deterministico,
    })

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(resultado, f, ensure_ascii=False, indent=2, default=str)

qtd_estaveis = sum(1 for c in resultado["combinacoes_testadas"] if c["deterministico"])
print(f"Resumo: {qtd_estaveis}/{len(top_n)} combinações estáveis (mesmo valor nas {args.repeticoes} chamadas).")
if todas_deterministicas:
    print("Nenhuma divergência — premissa do cache cross-produto confirmada nesta amostra.")
else:
    print("Alguma combinação divergiu — ver JSON completo antes de confiar no cache em produção.")
print(f"\nRetorno completo salvo em: {CAMINHO_SAIDA}")