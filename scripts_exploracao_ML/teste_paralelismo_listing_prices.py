# scripts_exploracao_ML/teste_paralelismo_listing_prices.py
#
# Objetivo: medir o throughput real de /sites/MLB/listing_prices sob
# paralelismo via ThreadPoolExecutor -- mesmo método já validado pro frete
# (Frente A, seção 23): dispara um lote de N chamadas em T threads
# simultâneas, mede o tempo total, conta erros e 429 (429 não vira exceção
# nessa camada -- é retry automático com warning no log -- por isso o
# contador engancha direto no logger, não em try/except).
#
# Usa 1 combinação REAL já validada como estável (script anterior:
# price=139.9, category_id=MLB264314, listing_type_id=gold_special,
# 3/3 chamadas idênticas) -- não testa correção de novo aqui, só throughput
# cru. Cada chamada é isolada; erro em 1 não derruba o lote.
import ativar_pool_conexao
import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import (
    chamar_api, ErroAPI, ErroAutenticacaoAPI, _configurar_logger,
)

CONTA_POR_EMPRESA = {'magazine': 'MB', 'samvale': 'SV'}

parser = argparse.ArgumentParser(description="Mede throughput de /listing_prices sob paralelismo.")
parser.add_argument("--empresa", required=True, choices=list(CONTA_POR_EMPRESA), help="magazine ou samvale")
parser.add_argument("--qtd", type=int, default=300, help="Chamadas por lote testado (default 300, igual ao teste do frete).")
parser.add_argument(
    "--niveis", type=int, nargs="+", default=[5, 10, 20, 30, 50],
    help="Quantidades de threads simultâneas a testar (default 5 10 20 30 50).",
)
parser.add_argument(
    "--pool", action="store_true",
    help="Ativa o patch de Session com pool de conexão (ativar_pool_conexao.py) antes de rodar os níveis.",
)
args = parser.parse_args()

CONTA = CONTA_POR_EMPRESA[args.empresa]
PASTA_LOGS = Path(__file__).resolve().parent / "logs"
NOME_LOG = "teste_paralelismo_listing_prices"

# Combinação real, já validada como estável no script anterior (3/3 idênticas).
PRICE_TESTE = "139.9"
CATEGORY_ID_TESTE = "MLB264314"
LISTING_TYPE_TESTE = "gold_special"


class ContadorDe429(logging.Handler):
    """Engancha no logger real de chamar_api pra contar quantas vezes um 429
    apareceu -- 429 nunca vira exceção nessa camada (é retry automático com
    warning), então não dá pra contar via try/except."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.contagem = 0
        self._lock = threading.Lock()

    def emit(self, record):
        if "429" in record.getMessage():
            with self._lock:
                self.contagem += 1


logger = _configurar_logger(PASTA_LOGS, NOME_LOG)
contador_429 = ContadorDe429()
logger.addHandler(contador_429)


def chamar_uma_vez():
    chamar_api(
        "GET", "/sites/MLB/listing_prices",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={"price": PRICE_TESTE, "category_id": CATEGORY_ID_TESTE, "listing_type_id": LISTING_TYPE_TESTE},
        nome_log=NOME_LOG,
    )


def rodar_lote(qtd_chamadas, max_workers):
    contador_429.contagem = 0
    erros = []
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(chamar_uma_vez) for _ in range(qtd_chamadas)]
        for f in as_completed(futures):
            try:
                f.result()
            except (ErroAPI, ErroAutenticacaoAPI) as e:
                erros.append(str(e))
    duracao = time.perf_counter() - inicio
    return duracao, erros, contador_429.contagem


print(f"Testando {args.qtd} chamadas por nível, níveis de threads: {args.niveis}\n")

if "--pool" in sys.argv:
    ativar_pool_conexao.instalar(pool_size=max(args.niveis))
    print()

resultados = []
for nivel in args.niveis:
    duracao, erros, qtd_429 = rodar_lote(args.qtd, nivel)
    throughput = args.qtd / duracao if duracao else 0
    print(
        f"{nivel:>3} threads: {duracao:6.1f}s  •  {throughput:5.1f} req/s  •  "
        f"{len(erros)} erro(s)  •  {qtd_429} warning(s) de 429"
    )
    if erros:
        for e in erros[:5]:
            print(f"    erro: {e}")
    resultados.append({
        "threads": nivel, "duracao_segundos": round(duracao, 1),
        "throughput_req_s": round(throughput, 1), "erros": len(erros), "qtd_429": qtd_429,
    })

print("\n--- Resumo ---")
for r in resultados:
    print(r)
print(
    "\nProcure o nível onde o throughput para de crescer (satura) -- esse é o teto real pra "
    "listing_prices, não necessariamente igual aos ~20 threads que valeram pro frete (endpoint "
    "diferente, pode se comportar diferente sob carga)."
)