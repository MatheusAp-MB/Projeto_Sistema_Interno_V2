#!/usr/bin/env python
"""
scripts_exploracao_ML/teste_paralelismo_por_produto.py

Valida a arquitetura de paralelismo proposta pra calcular_grade_precificacao_ml.py:
processar produtos em paralelo (1 worker por produto, thread principal só agrega/grava).

Reaproveita as MESMAS funções de produção (_calcular_ou_reaproveitar, _assinatura,
_formulas_sem_dimensao, FormulaPrecificacao) — não reimplementa nada da lógica de cálculo.

Roda o MESMO lote de produtos sequencial e depois em paralelo (cache de frete vazio nos 2
casos, pra comparação justa) e verifica:
  - Speedup real
  - Se o resultado (preço final, frete usado, origem_frete) é IDÊNTICO nos 2 casos —
    o teste mais importante: paralelismo só vale se o resultado não muda
  - Se algum erro/exceção aparece só no paralelo (sinal de problema de concorrência)

Uso:
    python scripts_exploracao_ML/teste_paralelismo_por_produto.py --empresa magazine
    python scripts_exploracao_ML/teste_paralelismo_por_produto.py --empresa magazine --qtd-produtos 100 --threads 20
    python scripts_exploracao_ML/teste_paralelismo_por_produto.py --empresa magazine --lock-cache-frete
"""
import os
import sys
import time
import threading
import argparse
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
import django
django.setup()

from core.empresa import EMPRESA_POR_ALIAS_BANCO, definir_empresa_ativa
from api_mercado_livre import ApiMercadoLivre
from produtos.models import Produto
from mercado_livre.models import (
    ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML,
    VariacaoAnuncioMercadoLivre,
)
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import (
    _calcular_ou_reaproveitar, _assinatura, _formulas_sem_dimensao, NOME_PASTA_LOGS_POR_EMPRESA,
)


def processar_produto(produto, variacoes_do_produto, configs, frete_todas, faixas_armazenagem,
                       config_geral, api_ml, TipoAnuncio):
    """Réplica FIEL do corpo do loop de produto em calcular_grade_precificacao_ml() — mesmas
    funções de produção, mesma ordem — só sem escrever no banco (sem _registrar_linhas) e
    devolvendo o resultado em memória, pra comparar sequencial vs paralelo linha a linha."""
    resultados = {}
    erros_locais = []
    contadores = {'novos': 0, 'reaproveitados': 0, 'sem_calculo': 0, 'sem_dimensao': 0,
                  'origem_api': 0, 'origem_tabela': 0}

    _cache_fiscal_produto = {}

    def obter_dados_fiscais_produto():
        if 'valor' not in _cache_fiscal_produto:
            _cache_fiscal_produto['valor'] = FormulaPrecificacao.resolver_dados_fiscais_produto(produto)
        return _cache_fiscal_produto['valor']

    def _acumular(resultado):
        contadores['novos'] += resultado['novos']
        contadores['reaproveitados'] += resultado['reaproveitados']
        contadores['sem_calculo'] += resultado['sem_calculo']
        contadores['origem_api'] += resultado['origem_api']
        contadores['origem_tabela'] += resultado['origem_tabela']

    def _coletar(variacao_id, tipo_grade, resultado):
        for margem_chave, formula in resultado['formulas'].items():
            if formula is None:
                resultados[(variacao_id, tipo_grade, margem_chave)] = (
                    'nao_resolvida', resultado['motivos'].get(margem_chave),
                )
            else:
                resultados[(variacao_id, tipo_grade, margem_chave)] = (
                    'ok', str(formula.saida.preco_final), str(formula.saida.frete_usado), formula.origem_frete,
                )

    grupos = {TipoAnuncio.CLASSICO: [], TipoAnuncio.PREMIUM: []}
    for v in variacoes_do_produto:
        tipo_v = v.anuncio.tipo_de_anuncio.tipo_anuncio
        if tipo_v in grupos:
            grupos[tipo_v].append(v)

    for tipo in (TipoAnuncio.CLASSICO, TipoAnuncio.PREMIUM):
        config = configs.get(tipo)
        if not config:
            continue
        tipo_grade = 'classico' if tipo == TipoAnuncio.CLASSICO else 'premium'
        cache_formulas = {}

        dim_fallback = resolver_dimensoes_efetivas(produto, variacao=None)
        if dim_fallback is None:
            formulas_fallback, motivos_fallback = _formulas_sem_dimensao(config)
            contadores['sem_dimensao'] += len(formulas_fallback)
            for margem_chave in formulas_fallback:
                resultados[(None, tipo_grade, margem_chave)] = ('sem_dimensao', motivos_fallback[margem_chave])
        else:
            resultado_fallback = _calcular_ou_reaproveitar(
                _assinatura(dim_fallback, None), dim_fallback, produto, config, frete_todas,
                faixas_armazenagem, config_geral, cache_formulas, None, tipo, erros_locais, api_ml,
                None, obter_dados_fiscais_produto,
            )
            _acumular(resultado_fallback)
            _coletar(None, tipo_grade, resultado_fallback)

        for variacao in grupos[tipo]:
            dim = resolver_dimensoes_efetivas(produto, variacao=variacao)
            if dim is None:
                formulas_variacao, motivos_variacao = _formulas_sem_dimensao(config)
                contadores['sem_dimensao'] += len(formulas_variacao)
                for margem_chave in formulas_variacao:
                    resultados[(variacao.id, tipo_grade, margem_chave)] = ('sem_dimensao', motivos_variacao[margem_chave])
                continue
            resultado = _calcular_ou_reaproveitar(
                _assinatura(dim, variacao), dim, produto, config, frete_todas,
                faixas_armazenagem, config_geral, cache_formulas, variacao, tipo, erros_locais, api_ml,
                None, obter_dados_fiscais_produto,
            )
            _acumular(resultado)
            _coletar(variacao.id, tipo_grade, resultado)

    return resultados, contadores, erros_locais


def montar_api_ml(pasta_logs, empresa, lock_cache_frete):
    api_ml = ApiMercadoLivre(pasta_logs=pasta_logs, empresa=empresa)
    if lock_cache_frete:
        # * [EXPLICAÇÃO] → Só pra TESTAR a proteção que pretendo levar pra produção —
        #                  envolve FreteRealML.simular() com um lock, sem tocar no
        #                  arquivo de produção (frete_real_ml.py). Monkeypatch só neste
        #                  script, pra medir o custo/benefício antes de aplicar de vez.
        contexto = api_ml._contexto_frete_real
        lock = threading.Lock()
        original = contexto.simular

        def simular_com_lock(*args, **kwargs):
            with lock:
                return original(*args, **kwargs)

        contexto.simular = simular_com_lock
    return api_ml


def rodar_lote(produtos, variacoes_por_produto, configs, frete_todas, faixas_armazenagem,
               config_geral, api_ml, TipoAnuncio, threads):
    resultados_totais = {}
    contadores_totais = {'novos': 0, 'reaproveitados': 0, 'sem_calculo': 0, 'sem_dimensao': 0,
                          'origem_api': 0, 'origem_tabela': 0}
    erros_totais = []
    exceções = []
    total = len(produtos)

    inicio = time.perf_counter()

    if threads == 1:
        for indice, produto in enumerate(produtos, start=1):
            r, c, e = processar_produto(
                produto, variacoes_por_produto.get(produto.id, []), configs, frete_todas,
                faixas_armazenagem, config_geral, api_ml, TipoAnuncio,
            )
            resultados_totais.update({(produto.id, *k): v for k, v in r.items()})
            for campo in contadores_totais:
                contadores_totais[campo] += c[campo]
            erros_totais.extend(e)
            decorrido = time.perf_counter() - inicio
            print(f'  [{indice}/{total}] EAN {produto.ean} processado ({decorrido:.1f}s decorridos)')
    else:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futuros = {
                executor.submit(
                    processar_produto, produto, variacoes_por_produto.get(produto.id, []), configs,
                    frete_todas, faixas_armazenagem, config_geral, api_ml, TipoAnuncio,
                ): produto
                for produto in produtos
            }
            indice = 0
            for futuro in as_completed(futuros):
                produto = futuros[futuro]
                indice += 1
                try:
                    r, c, e = futuro.result()
                except Exception as exc:
                    exceções.append((produto, exc))
                    decorrido = time.perf_counter() - inicio
                    print(f'  [{indice}/{total}] EAN {produto.ean} -> ⚠ EXCEÇÃO ({decorrido:.1f}s decorridos)')
                    continue
                resultados_totais.update({(produto.id, *k): v for k, v in r.items()})
                for campo in contadores_totais:
                    contadores_totais[campo] += c[campo]
                erros_totais.extend(e)
                decorrido = time.perf_counter() - inicio
                print(f'  [{indice}/{total}] EAN {produto.ean} processado ({decorrido:.1f}s decorridos)')

    tempo_total = time.perf_counter() - inicio
    return resultados_totais, contadores_totais, erros_totais, exceções, tempo_total


def main():
    parser = argparse.ArgumentParser(description='Valida paralelismo por produto (arquitetura completa, não só chamada isolada).')
    parser.add_argument('--empresa', required=True, choices=['magazine', 'samvale'])
    parser.add_argument('--qtd-produtos', type=int, default=60)
    parser.add_argument('--threads', type=int, default=20)
    parser.add_argument('--lock-cache-frete', action='store_true')
    args = parser.parse_args()

    empresa = EMPRESA_POR_ALIAS_BANCO[args.empresa]
    definir_empresa_ativa(empresa)
    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio

    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
    frete_todas = list(FreteML.objects.all())
    config_geral = ConfiguracaoOperacional.obter()
    faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

    variacoes_por_produto = defaultdict(list)
    for v in VariacaoAnuncioMercadoLivre.objects.filter(
        produto__isnull=False, anuncio__tipo_de_anuncio__isnull=False
    ).select_related('anuncio__tipo_de_anuncio', 'produto', 'categoria'):
        variacoes_por_produto[v.produto.id].append(v)

    produtos = list(Produto.objects.filter(id__in=list(variacoes_por_produto.keys()))[:args.qtd_produtos])
    print(f'{len(produtos)} produtos com MLB selecionados pro teste (de {len(variacoes_por_produto)} disponíveis).')

    pasta_logs = Path('integracao_mercado_livre') / 'logs' / NOME_PASTA_LOGS_POR_EMPRESA[empresa]

    print('\n=== Rodando SEQUENCIAL (baseline) ===')
    api_ml_seq = montar_api_ml(pasta_logs, empresa, args.lock_cache_frete)
    resultados_seq, contadores_seq, erros_seq, exceções_seq, tempo_seq = rodar_lote(
        produtos, variacoes_por_produto, configs, frete_todas, faixas_armazenagem,
        config_geral, api_ml_seq, TipoAnuncio, threads=1,
    )
    print(f'Sequencial: {tempo_seq:.1f}s | novos: {contadores_seq["novos"]} '
          f'(API: {contadores_seq["origem_api"]}, tabela: {contadores_seq["origem_tabela"]}) | '
          f'erros: {len(erros_seq)} | exceções: {len(exceções_seq)}')

    print(f'\n=== Rodando PARALELO ({args.threads} threads{" + lock no cache de frete" if args.lock_cache_frete else ""}) ===')
    api_ml_par = montar_api_ml(pasta_logs, empresa, args.lock_cache_frete)  # cache VAZIO — comparação justa
    resultados_par, contadores_par, erros_par, exceções_par, tempo_par = rodar_lote(
        produtos, variacoes_por_produto, configs, frete_todas, faixas_armazenagem,
        config_geral, api_ml_par, TipoAnuncio, threads=args.threads,
    )
    print(f'Paralelo: {tempo_par:.1f}s | novos: {contadores_par["novos"]} '
          f'(API: {contadores_par["origem_api"]}, tabela: {contadores_par["origem_tabela"]}) | '
          f'erros: {len(erros_par)} | exceções: {len(exceções_par)}')

    print('\n=== Comparação sequencial vs paralelo ===')
    speedup = tempo_seq / tempo_par if tempo_par else 0
    print(f'Speedup: {speedup:.1f}x ({tempo_seq:.1f}s -> {tempo_par:.1f}s)')

    if exceções_par:
        print(f'\n⚠ {len(exceções_par)} exceção(ões) NO PARALELO que não deveriam acontecer:')
        for produto, exc in exceções_par[:10]:
            print(f'  {produto} ({produto.id}): {exc!r}')

    todas_chaves = set(resultados_seq) | set(resultados_par)
    divergencias = [
        (chave, resultados_seq.get(chave), resultados_par.get(chave))
        for chave in todas_chaves
        if resultados_seq.get(chave) != resultados_par.get(chave)
    ]

    print(f'Combinações comparadas: {len(todas_chaves)}')
    print(f'Divergências encontradas: {len(divergencias)}')
    if divergencias:
        print('\n⚠ ATENÇÃO — resultado DIFERENTE entre sequencial e paralelo (não devia acontecer):')
        for chave, v_seq, v_par in divergencias[:20]:
            print(f'  {chave}: sequencial={v_seq} | paralelo={v_par}')
        if len(divergencias) > 20:
            print(f'  ... e mais {len(divergencias) - 20} divergência(s)')
    else:
        print('✓ Nenhuma divergência — resultado do paralelo é IDÊNTICO ao sequencial.')

    if len(erros_par) != len(erros_seq):
        print(f'\n⚠ Quantidade de erros de assert diferente: sequencial={len(erros_seq)} | paralelo={len(erros_par)}')


if __name__ == '__main__':
    main()