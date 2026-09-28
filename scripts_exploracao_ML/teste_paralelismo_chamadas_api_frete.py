#!/usr/bin/env python
"""
scripts_exploracao_ML/teste_paralelismo_chamadas_api_frete.py

Valida se paralelizar as chamadas de simulação de frete (FreteRealML.simular, via
ApiMercadoLivre.simular_frete) é seguro e realmente reduz o tempo total — antes de
mexer no código de produção (calcular_grade_precificacao_ml.py).

Mede, pra cada nível de paralelismo testado (--threads, ex: 1,5,10,20):
  - tempo total pra rodar N chamadas REAIS e DISTINTAS (nunca repete combinação,
    pra não deixar o cache de FreteRealML mascarar o resultado)
  - quantos 429 (rate limit) a API devolveu durante o teste
  - quantos erros (ErroAPI/ErroAutenticacaoAPI) aconteceram
  - tempo médio por chamada

Uso:
    python scripts_exploracao_ML/teste_paralelismo_chamadas_api_frete.py --empresa magazine
    python scripts_exploracao_ML/teste_paralelismo_chamadas_api_frete.py --empresa magazine --qtd 60 --threads 1,5,10,20,30
"""
import os
import sys
import time
import logging
import argparse
from pathlib import Path
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
import django
django.setup()

from core.empresa import EMPRESA_POR_ALIAS_BANCO, definir_empresa_ativa
from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI
from mercado_livre.models import VariacaoAnuncioMercadoLivre
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import (
    NOME_PASTA_LOGS_POR_EMPRESA,
)


class _ContadorDe429(logging.Handler):
    """Conta quantas vezes o logger do cliente_api avisou '429' (rate limit) durante
    o teste — chamar_api() já trata 429 sozinho (retry com backoff, não levanta
    exceção), então a única forma de saber que ele aconteceu é observando o log."""
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.total = 0

    def emit(self, record):
        if '429' in record.getMessage():
            self.total += 1


def montar_combinacoes_reais(qtd):
    """Monta até `qtd` combinações REAIS e DISTINTAS de parâmetros de simulação — 1
    por MLB (categoria + dimensão efetiva + preço), igual ao que
    FormulaPrecificacao._tentar_resolver_preco_via_api monta em produção. Nunca
    repete a mesma combinação (senão o cache de FreteRealML absorve a repetição e o
    teste deixa de medir chamada de rede real)."""
    combinacoes = []
    vistas = set()
    variacoes = (
        VariacaoAnuncioMercadoLivre.objects
        .filter(produto__isnull=False, anuncio__tipo_de_anuncio__isnull=False, categoria__isnull=False)
        .select_related('anuncio__tipo_de_anuncio', 'produto', 'categoria')
        .order_by('?')[:qtd * 3]  # margem de sobra — nem toda variação resolve dimensão
    )
    for v in variacoes:
        if len(combinacoes) >= qtd:
            break
        dim = resolver_dimensoes_efetivas(v.produto, variacao=v)
        if dim is None or dim.peso_fisico is None:
            continue

        f = FormulaPrecificacao._formatar_numero_dimensao
        peso_gramas = int((dim.peso_fisico * 1000).to_integral_value())
        dimensions_str = f'{f(dim.altura)}x{f(dim.largura)}x{f(dim.comprimento)},{peso_gramas}'

        item_price = str(v.produto.custo or Decimal('50.00'))
        category_id = v.categoria.category_id
        listing_type_id = v.anuncio.tipo_de_anuncio.tipo_anuncio

        chave = (dimensions_str, item_price, category_id, listing_type_id)
        if chave in vistas:
            continue
        vistas.add(chave)
        combinacoes.append(chave)

    return combinacoes


def rodar_nivel(api_ml, pasta_logs, combinacoes, threads):
    """Roda TODAS as combinações com o nível de paralelismo pedido, numa instância
    NOVA de ApiMercadoLivre (cache vazio) — cada nível de teste é isolado, senão o
    nível seguinte reaproveitaria do cache do anterior e o teste ficaria viciado."""
    contador_429 = _ContadorDe429()
    logger_cliente_api = logging.getLogger(f'cliente_api.{pasta_logs}.simular_frete_ml')
    logger_cliente_api.addHandler(contador_429)

    sucesso = 0
    erros = 0
    inicio = time.perf_counter()

    def _chamar(combo):
        dimensions_str, item_price, category_id, listing_type_id = combo
        return api_ml.simular_frete(
            dimensions_str, item_price, category_id, listing_type_id, free_shipping=False,
        )

    if threads == 1:
        for combo in combinacoes:
            try:
                _chamar(combo)
                sucesso += 1
            except (ErroAPI, ErroAutenticacaoAPI):
                erros += 1
    else:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futuros = [executor.submit(_chamar, combo) for combo in combinacoes]
            for futuro in as_completed(futuros):
                try:
                    futuro.result()
                    sucesso += 1
                except (ErroAPI, ErroAutenticacaoAPI):
                    erros += 1

    tempo_total = time.perf_counter() - inicio
    logger_cliente_api.removeHandler(contador_429)

    return {
        'threads': threads, 'tempo_total': tempo_total, 'sucesso': sucesso, 'erros': erros,
        'tempo_medio_por_chamada': tempo_total / len(combinacoes) if combinacoes else 0,
        'total_429': contador_429.total,
    }


def main():
    parser = argparse.ArgumentParser(description='Valida paralelismo nas chamadas de simulação de frete.')
    parser.add_argument('--empresa', required=True, choices=['magazine', 'samvale'])
    parser.add_argument('--qtd', type=int, default=40, help='Quantidade de combinações reais e distintas a testar por nível (default: 40)')
    parser.add_argument('--threads', type=str, default='1,5,10,20', help='Níveis de paralelismo a testar, separados por vírgula (default: 1,5,10,20)')
    args = parser.parse_args()

    empresa = EMPRESA_POR_ALIAS_BANCO[args.empresa]
    definir_empresa_ativa(empresa)

    niveis = [int(n.strip()) for n in args.threads.split(',')]
    pasta_logs = Path('integracao_mercado_livre') / 'logs' / NOME_PASTA_LOGS_POR_EMPRESA[empresa]

    print(f'Montando {args.qtd} combinações reais e distintas...')
    combinacoes = montar_combinacoes_reais(args.qtd)
    print(f'  {len(combinacoes)} combinações prontas (pediu {args.qtd} — nem toda variação tem dimensão resolvível).')
    if not combinacoes:
        print('Nenhuma combinação disponível — abortando.')
        return

    print()
    print(f'{"threads":>8} | {"tempo total":>12} | {"tempo médio/chamada":>20} | {"sucesso":>8} | {"erros":>6} | {"429 (rate limit)":>17}')
    print('-' * 90)

    resultados = []
    for threads in niveis:
        api_ml = ApiMercadoLivre(pasta_logs=pasta_logs, empresa=empresa)  # cache vazio a cada nível
        resultado = rodar_nivel(api_ml, pasta_logs, combinacoes, threads)
        resultados.append(resultado)
        print(
            f'{resultado["threads"]:>8} | {resultado["tempo_total"]:>10.1f}s | '
            f'{resultado["tempo_medio_por_chamada"]:>18.3f}s | {resultado["sucesso"]:>8} | '
            f'{resultado["erros"]:>6} | {resultado["total_429"]:>17}'
        )

    print()
    base = resultados[0]
    print(f'Baseline sequencial ({base["threads"]} thread): {base["tempo_total"]:.1f}s')
    for r in resultados[1:]:
        speedup = base['tempo_total'] / r['tempo_total'] if r['tempo_total'] else 0
        print(f'  {r["threads"]} threads: {r["tempo_total"]:.1f}s ({speedup:.1f}x mais rápido) | 429: {r["total_429"]} | erros: {r["erros"]}')


if __name__ == '__main__':
    main()