# scripts_exploracao_ML/medir_duplicidade_listing_prices_via_log.py
#
# Objetivo: medir, sem nenhuma chamada nova à API, quanto da rodada real de
# `buscar_comissao_real_ml` teria sido evitável se o cache de
# /sites/MLB/listing_prices fosse pela tupla (price, category_id,
# listing_type_id) -- os únicos parâmetros que esse endpoint recebe --
# CROSS-PRODUTO, não por MLB. Hoje não existe cache nenhum pro
# /listing_prices (só o /items é cacheado, e por MLB).
#
# Mesmo método já validado pro frete (Frente A, seção 20): ler o log real
# já gerado (sem gastar chamada nova) e contar repetições exatas por chave
# completa dos parâmetros enviados.
#
# Só leitura de arquivo de log em disco -- não toca no banco, não chama a
# API, não precisa do Django.

import argparse
import ast
import re
from collections import Counter
from pathlib import Path

NOME_PASTA_POR_EMPRESA = {'magazine': 'Magazine', 'samvale': 'Samvale'}

parser = argparse.ArgumentParser(
    description="Mede duplicidade de chamadas a /listing_prices num log real de buscar_comissao_real_ml."
)
parser.add_argument("--empresa", required=True, choices=list(NOME_PASTA_POR_EMPRESA), help="magazine ou samvale")
parser.add_argument(
    "--log", default=None,
    help="Caminho do arquivo de log (default: integracao_mercado_livre/logs/<Empresa>/buscar_comissao_real_ml.log, "
         "relativo à raiz do projeto).",
)
args = parser.parse_args()

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent

if args.log:
    caminho_log = Path(args.log)
else:
    pasta_empresa = NOME_PASTA_POR_EMPRESA[args.empresa]
    caminho_log = _RAIZ_DO_PROJETO / 'integracao_mercado_livre' / 'logs' / pasta_empresa / 'buscar_comissao_real_ml.log'

if not caminho_log.exists():
    print(f"Log não encontrado em: {caminho_log}")
    print("Passe o caminho certo com --log <caminho>, se o arquivo estiver em outro lugar (ex: rotacionado).")
    raise SystemExit(1)

# Casa a linha inteira de 1 chamada a /listing_prices, capturando o dict de
# 'dados_limpos' que cliente_api.py loga (params/headers_extra/tentativa).
PADRAO_LINHA = re.compile(r"Chamando GET /sites/MLB/listing_prices \| (\{.*\})\s*$")

total_chamadas = 0
total_ignoradas_retry = 0
total_linhas_nao_casadas = 0
chaves = Counter()

with open(caminho_log, "r", encoding="utf-8") as f:
    for linha in f:
        m = PADRAO_LINHA.search(linha)
        if not m:
            continue

        try:
            dados = ast.literal_eval(m.group(1))
        except (ValueError, SyntaxError):
            total_linhas_nao_casadas += 1
            continue

        # Só conta a 1ª tentativa de cada chamada -- retry (429/timeout) da
        # MESMA chamada não é uma pergunta nova à API, é a mesma pergunta
        # repetida por instabilidade de rede.
        if dados.get("tentativa") != 1:
            total_ignoradas_retry += 1
            continue

        params = dados.get("params") or {}
        chave = (params.get("price"), params.get("category_id"), params.get("listing_type_id"))
        if None in chave:
            total_linhas_nao_casadas += 1
            continue

        total_chamadas += 1
        chaves[chave] += 1

combinacoes_unicas = len(chaves)
evitaveis = total_chamadas - combinacoes_unicas
percentual_evitavel = (evitaveis / total_chamadas * 100) if total_chamadas else 0

print(f"Log lido: {caminho_log}")
print(f"\nChamadas a /listing_prices (1ª tentativa): {total_chamadas}")
print(f"Combinações únicas de (price, category_id, listing_type_id): {combinacoes_unicas}")
print(f"Chamadas evitáveis com cache cross-produto: {evitaveis} ({percentual_evitavel:.1f}%)")
if total_ignoradas_retry:
    print(f"(Retries ignorados na contagem: {total_ignoradas_retry})")
if total_linhas_nao_casadas:
    print(f"(Linhas de listing_prices não parseadas/incompletas: {total_linhas_nao_casadas})")

print("\n--- Top 15 combinações mais repetidas ---")
for chave, qtd in chaves.most_common(15):
    if qtd <= 1:
        break
    price, category_id, listing_type_id = chave
    print(f"  {qtd}x  price={price}  category_id={category_id}  listing_type_id={listing_type_id}")

print(
    "\nPróximo passo, se a duplicidade for relevante: pegar as combinações mais repetidas daqui e "
    "rechamar cada uma 2-3x ao vivo, confirmando que o valor não muda -- mesmo padrão de validação "
    "já usado pro cache do frete, antes de confiar nisso em produção."
)