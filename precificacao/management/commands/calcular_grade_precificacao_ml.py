# * [RESUMO] → Reformulado em 15/07 (mudança de base: Grade passa a
#              viver por VARIAÇÃO/MLB real, não mais só por Produto —
#              descoberta do "frete real" da API do ML, que pode
#              divergir do frete de tabela e divergir ENTRE MLBs do
#              MESMO produto).
#
#              Algoritmo (validado com o usuário, exemplo SS-20B/21
#              MLBs):
#              1. PASSADA TABELA — pros 2 tipos (Clássico/Premium) do
#                 produto, calcula as 4 margens de cada usando busca
#                 de faixa (motor de sempre, com a circularidade
#                 preço↔faixa). Vira a linha de FALLBACK do produto
#                 (variacao=None) — E é reaproveitada como valor
#                 padrão pra qualquer MLB desse tipo SEM frete real.
#              2. Por tipo (Clássico/Premium), separa as variações
#                 (MLBs reais) publicadas desse produto.
#              3. PASSADA FRETE REAL — dentro de cada tipo, agrupa os
#                 MLBs por valor DISTINTO de frete_real (ignorando os
#                 que não têm) — calcula 1 vez por valor distinto ×
#                 4 margens (SEM busca de faixa, frete real já é
#                 número fechado).
#              4. Redistribui: cada MLB com frete_real usa o
#                 resultado da Passada 3; cada MLB sem frete_real usa
#                 o resultado da Passada 1 (mesmo do fallback).
#
#              Sem paralelismo, sem signal — só roda quando mandado.
#
#              Auditoria de otimização (15/07): contagem de consultas
#              trocada de len(connection.queries_log) (capado em 9.000
#              pelo Django — achado real: outro arquivo do pipeline
#              bateu EXATAMENTE nesse teto, escondendo o número
#              verdadeiro) pra contar_consultas() (sem teto).

import time
from collections import defaultdict
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.funcoes_auxiliares.contador_consultas import contar_consultas


def _margens_do_tipo(config):
    return [
        ('minima', config.margem_minima),
        ('padrao', config.margem_padrao),
        ('maxima', config.margem_maxima),
        ('competicao', config.margem_competicao),
    ]


def _campo_prefixo(tipo, tipo_classico):
    return 'classico' if tipo == tipo_classico else 'premium'


def calcular_grade_precificacao_ml(stdout, style):
    from produtos.models import Produto
    from mercado_livre.models import (
        ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre,
        FreteML, VariacaoAnuncioMercadoLivre, ConfiguracaoMercadoLivre, FaixaArmazenagemMercadoLivre,
    )
    from precificacao.funcoes_auxiliares.mercado_livre.montar_parametros_ml import (
        calcular_preco_grade_ml, calcular_preco_com_frete_real, preparar_fixo_e_faixas,
    )
    from precificacao.models import GradePrecificacaoML

    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio

    stdout.write('[GRADE DE PRECIFICAÇÃO ML] Calculando...')

    with contar_consultas() as contador:
        inicio_total = time.perf_counter()

        inicio_carga = time.perf_counter()
        produtos = list(Produto.objects.all())
        stdout.write(f'    {len(produtos)} produto(s) encontrados')

        configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
        frete_todas = list(FreteML.objects.all())
        config_geral = ConfiguracaoMercadoLivre.obter()
        faixas_armazenagem = list(FaixaArmazenagemMercadoLivre.objects.filter(ativo=True).order_by('ordem'))

        # * [EXPLICAÇÃO] → VariacaoAnuncioMercadoLivre.produto usa
        #                  to_field='sku' — o atalho v.produto_id guarda
        #                  o SKU (texto), NÃO o ID numérico do Produto.
        #                  Precisa acessar v.produto.id (o objeto de
        #                  verdade, via select_related pra não gerar 1
        #                  query por variação) pra pegar o ID real,
        #                  batendo com produto.id do loop principal.
        variacoes_por_produto = defaultdict(list)
        total_variacoes = 0
        for v in VariacaoAnuncioMercadoLivre.objects.filter(
            produto__isnull=False, anuncio__tipo_de_anuncio__isnull=False
        ).select_related('anuncio__tipo_de_anuncio', 'produto'):
            variacoes_por_produto[v.produto.id].append(v)
            total_variacoes += 1
        stdout.write(f'    {total_variacoes} variação(ões)/MLB(s) publicado(s) encontrado(s)')

        existentes = {
            (r.produto_id, r.variacao_id): r
            for r in GradePrecificacaoML.objects.all()
        }

        tempo_carga = time.perf_counter() - inicio_carga
        stdout.write(f'  ⏱ Carregar produtos/config/variações/existentes/frete: {tempo_carga:.1f}s')

        para_criar = []
        para_atualizar = []
        erros = []
        sem_calculo = 0

        inicio_calculo = time.perf_counter()
        qtd_calculos_tabela = 0
        qtd_calculos_frete_real = 0
        calculos_por_produto = []  # * [EXPLICAÇÃO] → só curiosidade/log, não usado por nenhuma decisão do sistema
        total_produtos = len(produtos)

        for indice_produto, produto in enumerate(produtos, start=1):
            if indice_produto % 200 == 0 or indice_produto == total_produtos:
                decorrido = time.perf_counter() - inicio_calculo
                stdout.write(f'    ... {indice_produto}/{total_produtos} produtos processados ({decorrido:.1f}s)')

            qtd_calculos_antes_deste_produto = qtd_calculos_tabela + qtd_calculos_frete_real

            fixo_produto, faixas_produto, peso_produto = preparar_fixo_e_faixas(
                produto, frete_todas, config_geral=config_geral, faixas_armazenagem=faixas_armazenagem
            )

            # * PASSADA 1 — TABELA, sempre, pros 2 tipos.
            resultado_tabela = {}
            for tipo in (TipoAnuncio.CLASSICO, TipoAnuncio.PREMIUM):
                config = configs.get(tipo)
                if not config:
                    continue
                for margem_chave, margem_valor in _margens_do_tipo(config):
                    try:
                        resultado = calcular_preco_grade_ml(
                            produto, config, margem_valor, fixo_produto, faixas_produto, peso_produto
                        )
                        qtd_calculos_tabela += 1
                        resultado_tabela[(tipo, margem_chave)] = resultado
                        if resultado is None:
                            sem_calculo += 1
                    except AssertionError as e:
                        erros.append(f'{produto} | tabela | {tipo} | {margem_chave} | {e}')
                        resultado_tabela[(tipo, margem_chave)] = None

            # * Linha de FALLBACK do produto (variacao=None) — os 2 tipos inteiros.
            dados_fallback = {}
            for tipo in (TipoAnuncio.CLASSICO, TipoAnuncio.PREMIUM):
                config = configs.get(tipo)
                if not config:
                    continue
                prefixo = _campo_prefixo(tipo, TipoAnuncio.CLASSICO)
                algum_resultado = None
                for margem_chave, _ in _margens_do_tipo(config):
                    r = resultado_tabela.get((tipo, margem_chave))
                    if r is None:
                        continue
                    algum_resultado = r
                    dados_fallback[f'{prefixo}_{margem_chave}_preco'] = r['preco_calculado']
                    dados_fallback[f'{prefixo}_{margem_chave}_margem'] = r['margem_percentual_obtida']
                if algum_resultado is not None:
                    dados_fallback[f'frete_{prefixo}_usado'] = algum_resultado['frete_usado']
                    dados_fallback[f'frete_{prefixo}_origem'] = 'tabela'
                    dados_fallback[f'{prefixo}_detalhamento'] = {
                        m: (resultado_tabela.get((tipo, m)) or {}).get('detalhamento')
                        for m, _ in _margens_do_tipo(config)
                    }

            _registrar_linha(produto, None, dados_fallback, existentes, para_criar, para_atualizar)

            # * PASSADA 2 e 3 — por tipo, separa as variações reais e
            #                  agrupa por valor distinto de frete real.
            variacoes_do_produto = variacoes_por_produto.get(produto.id, [])
            grupos = {TipoAnuncio.CLASSICO: [], TipoAnuncio.PREMIUM: []}
            for v in variacoes_do_produto:
                tipo_v = v.anuncio.tipo_de_anuncio.tipo_anuncio
                if tipo_v in grupos:
                    grupos[tipo_v].append(v)

            for tipo, lista_variacoes in grupos.items():
                if not lista_variacoes:
                    continue
                config = configs.get(tipo)
                if not config:
                    continue
                prefixo = _campo_prefixo(tipo, TipoAnuncio.CLASSICO)

                fretes_reais_distintos = sorted({
                    v.frete_real for v in lista_variacoes if v.frete_real is not None
                })

                cache_frete_real = {}
                for frete_valor in fretes_reais_distintos:
                    for margem_chave, margem_valor in _margens_do_tipo(config):
                        try:
                            resultado = calcular_preco_com_frete_real(
                                produto, config, margem_valor, fixo_produto, peso_produto, frete_valor
                            )
                            qtd_calculos_frete_real += 1
                            cache_frete_real[(frete_valor, margem_chave)] = resultado
                            if resultado is None:
                                sem_calculo += 1
                        except AssertionError as e:
                            erros.append(f'{produto} | frete_real={frete_valor} | {tipo} | {margem_chave} | {e}')
                            cache_frete_real[(frete_valor, margem_chave)] = None

                for v in lista_variacoes:
                    dados_variacao = {}
                    usa_frete_real = v.frete_real is not None
                    algum_resultado = None

                    for margem_chave, _ in _margens_do_tipo(config):
                        if usa_frete_real:
                            r = cache_frete_real.get((v.frete_real, margem_chave))
                        else:
                            r = resultado_tabela.get((tipo, margem_chave))
                        if r is None:
                            continue
                        algum_resultado = r
                        dados_variacao[f'{prefixo}_{margem_chave}_preco'] = r['preco_calculado']
                        dados_variacao[f'{prefixo}_{margem_chave}_margem'] = r['margem_percentual_obtida']

                    if algum_resultado is not None:
                        dados_variacao[f'frete_{prefixo}_usado'] = algum_resultado['frete_usado']
                        dados_variacao[f'frete_{prefixo}_origem'] = 'real' if usa_frete_real else 'tabela'
                        if usa_frete_real:
                            dados_variacao[f'{prefixo}_detalhamento'] = {
                                m: (cache_frete_real.get((v.frete_real, m)) or {}).get('detalhamento')
                                for m, _ in _margens_do_tipo(config)
                            }
                        else:
                            dados_variacao[f'{prefixo}_detalhamento'] = {
                                m: (resultado_tabela.get((tipo, m)) or {}).get('detalhamento')
                                for m, _ in _margens_do_tipo(config)
                            }

                    _registrar_linha(produto, v, dados_variacao, existentes, para_criar, para_atualizar)

            calculos_deste_produto = (qtd_calculos_tabela + qtd_calculos_frete_real) - qtd_calculos_antes_deste_produto
            calculos_por_produto.append(calculos_deste_produto)

        tempo_calculo_total = time.perf_counter() - inicio_calculo
        stdout.write(f'  ⏱ Loop de cálculo, total: {tempo_calculo_total:.1f}s')
        stdout.write(f'      ↳ Cálculos com frete de tabela: {qtd_calculos_tabela}')
        stdout.write(f'      ↳ Cálculos com frete real: {qtd_calculos_frete_real}')
        if calculos_por_produto:
            media = sum(calculos_por_produto) / len(calculos_por_produto)
            stdout.write(
                f'      ↳ Cálculos por produto — mín: {min(calculos_por_produto)}, '
                f'média: {media:.1f}, máx: {max(calculos_por_produto)}'
            )

        inicio_salvar = time.perf_counter()

        campos_atualizaveis = [
            'frete_classico_usado', 'frete_classico_origem',
            'classico_minima_preco', 'classico_minima_margem',
            'classico_padrao_preco', 'classico_padrao_margem',
            'classico_maxima_preco', 'classico_maxima_margem',
            'classico_competicao_preco', 'classico_competicao_margem',
            'classico_detalhamento',
            'frete_premium_usado', 'frete_premium_origem',
            'premium_minima_preco', 'premium_minima_margem',
            'premium_padrao_preco', 'premium_padrao_margem',
            'premium_maxima_preco', 'premium_maxima_margem',
            'premium_competicao_preco', 'premium_competicao_margem',
            'premium_detalhamento',
        ]

        if para_criar:
            GradePrecificacaoML.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
        if para_atualizar:
            GradePrecificacaoML.objects.bulk_update(para_atualizar, campos_atualizaveis, batch_size=BATCH_SIZE_PADRAO)

        tempo_salvar = time.perf_counter() - inicio_salvar
        stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {tempo_salvar:.1f}s')

        tempo_total = time.perf_counter() - inicio_total

    stdout.write(style.SUCCESS(
        f'[GRADE DE PRECIFICAÇÃO ML] Concluído em {tempo_total:.1f}s!\n'
        f'    Linhas criadas: {len(para_criar)}\n'
        f'    Linhas atualizadas: {len(para_atualizar)}\n'
        f'    Sem cálculo possível (meta inatingível): {sem_calculo}\n'
        f'    Erros de assert: {len(erros)}'
    ))

    if erros:
        stdout.write(style.ERROR('    ATENÇÃO — erros de assert encontrados:'))
        for erro in erros[:20]:
            stdout.write(style.ERROR(f'      {erro}'))
        if len(erros) > 20:
            stdout.write(style.ERROR(f'      ... e mais {len(erros) - 20} erro(s)'))

    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {contador["total"]}')


def _registrar_linha(produto, variacao, dados, existentes, para_criar, para_atualizar):
    """Cria ou atualiza 1 linha (fallback do produto ou de 1 variação
    real) — mesmo padrão de sempre (dict de chave→instância em
    memória, bulk no final, nunca 1 save() por linha)."""
    from precificacao.models import GradePrecificacaoML

    if not dados:
        return

    chave = (produto.id, variacao.id if variacao else None)
    existente = existentes.get(chave)
    if existente:
        for campo, valor in dados.items():
            setattr(existente, campo, valor)
        para_atualizar.append(existente)
    else:
        nova = GradePrecificacaoML(produto=produto, variacao=variacao, **dados)
        para_criar.append(nova)
        existentes[chave] = nova