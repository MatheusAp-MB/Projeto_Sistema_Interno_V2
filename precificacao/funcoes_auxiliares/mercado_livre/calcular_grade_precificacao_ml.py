# precificacao/funcoes_auxiliares/mercado_livre/calcular_grade_precificacao_ml.py

# Função Objetivo: Calcula a Grade de Precificação (Mínima/Padrão/Máxima/Competição) por MLB.
# Explicação em detalhe: reescrito pra usar FormulaPrecificacao + DimensoesEfetivas — 1 caminho
# só de cálculo (busca de faixa sempre), sem mais a distinção "tabela vs frete real fixo" (esse
# conceito morreu — calcular_preco_com_frete_real/preparar_fixo_e_faixas/calcular_preco_grade_ml,
# de montar_parametros_ml.py, ficam obsoletos). Cache por ASSINATURA de dimensão (altura,largura,
# comprimento,peso,origem) — variações com a mesma assinatura reaproveitam o mesmo cálculo, sem
# recalcular Coleta/Armazenagem/preço do zero pra cada MLB (a busca de faixa de frete em si já
# é discreta por peso — isso é aproveitado dentro de FormulaPrecificacao.filtrar_faixas_frete()).
# Salva no formato LONGO (1 linha por variação × tipo_anuncio × margem), igual
# RecomendacaoPrecificacao — chega de campo prefixado.
#
# resolvida/motivo_nao_resolvida (10/09) — antes, quando 1 margem não resolvia (meta inatingível
# ou AssertionError), _registrar_linhas pulava a linha com 'continue': não gravava, não
# atualizava, não apagava. Agora toda combinação processada SEMPRE grava uma linha — nunca mais
# deixa linha antiga (de uma resolução anterior que parou de valer) obsoleta e silenciosa.
#
# * [CORREÇÃO 11/09/2026] → resolver_dimensoes_efetivas agora devolve None quando não há
#   embalagem cadastrada no ERP nem variação ML com dimensão declarada (ver dimensoes_
#   efetivas.py — antes fabricava altura/largura/comprimento/peso = 0, e isso "resolvia"
#   com sucesso usando a faixa de frete mais barata, silenciosamente). Os 2 pontos que
#   chamam resolver_dimensoes_efetivas agora tratam esse None ANTES de tentar calcular
#   qualquer coisa — grava direto resolvida=False com motivo claro, sem nem instanciar
#   FormulaPrecificacao.

import time
from collections import defaultdict
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao


# Função Objetivo: Devolve as 4 margens configuradas pro tipo de anúncio (nome, valor).
def _margens_do_tipo(config):
    return [
        ('minima', config.margem_minima),
        ('padrao', config.margem_padrao),
        ('maxima', config.margem_maxima),
        ('competicao', config.margem_competicao),
    ]


# Função Objetivo: Monta a chave de cache — mesma dimensão efetiva reaproveita o mesmo cálculo.
def _assinatura(dim):
    return (dim.altura, dim.largura, dim.comprimento, dim.peso, dim.origem)


# Função Objetivo: Monta formulas/motivos "tudo não resolvida" pras 4 margens do tipo, sem
# calcular nada — usado quando resolver_dimensoes_efetivas devolveu None (sem embalagem no
# ERP e sem variação ML com dimensão declarada).
def _formulas_sem_dimensao(config):
    motivo = 'Produto sem dimensão/peso de embalagem cadastrados no ERP (e sem variação ML com dimensão declarada)'
    formulas = {}
    motivos = {}
    for margem_chave, _ in _margens_do_tipo(config):
        formulas[margem_chave] = None
        motivos[margem_chave] = motivo
    return formulas, motivos


# Função Objetivo: Roda FormulaPrecificacao pras 4 margens dessa assinatura, ou reaproveita do cache.
# Explicação em detalhe: motivos[margem_chave] só existe (não-None) quando formulas[margem_chave]
# é None — guarda o TEXTO do porquê não resolveu (meta inatingível vs. a mensagem exata do
# AssertionError), pra _registrar_linhas gravar em GradePrecificacaoML.motivo_nao_resolvida.
def _calcular_ou_reaproveitar(assinatura, dim, produto, config, frete_todas, faixas_armazenagem,
                               config_geral, cache_formulas, variacao, tipo, erros):
    if assinatura in cache_formulas:
        cache = cache_formulas[assinatura]
        return {
            'formulas': cache['formulas'], 'motivos': cache['motivos'],
            'novos': 0, 'reaproveitados': 4, 'sem_calculo': 0,
        }

    formulas = {}
    motivos = {}
    novos = 0
    sem_calculo = 0
    for margem_chave, margem_valor in _margens_do_tipo(config):
        try:
            formula = FormulaPrecificacao(
                produto=produto, dimensoes_efetivas=dim, config_tipo=config,
                config_geral=config_geral, margem_alvo_percentual=margem_valor,
                frete_todas=frete_todas, faixas_armazenagem=faixas_armazenagem,
            ).calcular()
            novos += 1
            if not formula.resolvida:
                sem_calculo += 1
                formulas[margem_chave] = None
                motivos[margem_chave] = (
                    'Meta de margem inatingível — nenhuma faixa de frete gerou solução consistente'
                )
            else:
                formulas[margem_chave] = formula
                motivos[margem_chave] = None
        except AssertionError as e:
            alvo = f'MLB {variacao.anuncio.mlb}' if variacao else 'fallback'
            erros.append(f'{produto} | {alvo} | {tipo} | {margem_chave} | {e}')
            formulas[margem_chave] = None
            motivos[margem_chave] = str(e)

    cache_formulas[assinatura] = {'formulas': formulas, 'motivos': motivos}
    return {'formulas': formulas, 'motivos': motivos, 'novos': novos, 'reaproveitados': 0, 'sem_calculo': sem_calculo}


# Função Objetivo: Cria ou atualiza as 4 linhas (1 por margem) de 1 (produto, variação, tipo).
# Explicação em detalhe: SEMPRE grava — não pula mais quando formula é None. resolvida=False
# limpa os campos de preço (nunca deixa preço de uma resolução ANTERIOR sobrevivendo junto com
# um motivo de falha ATUAL — ou os 2 batem, ou nenhum dos 2 aparece).
def _registrar_linhas(produto, variacao, tipo_grade, formulas, motivos, existentes, para_criar, para_atualizar):
    from precificacao.models import GradePrecificacaoML

    for margem_chave, formula in formulas.items():
        if formula is None:
            dados = dict(
                resolvida=False,
                motivo_nao_resolvida=(motivos.get(margem_chave) or 'Não resolvida')[:255],
                preco=None, margem_percentual_obtida=None, frete_usado=None,
                origem_dimensao=None, detalhamento=None,
            )
        else:
            dados = dict(
                resolvida=True,
                motivo_nao_resolvida=None,
                preco=formula.saida.preco_final,
                margem_percentual_obtida=formula.saida.margem_percentual_obtida,
                frete_usado=formula.saida.frete_usado,
                origem_dimensao=formula.entrada.origem_dimensao,
                detalhamento=formula.para_dict_auditoria(),
            )

        chave = (produto.id, variacao.id if variacao else None, tipo_grade, margem_chave)
        existente = existentes.get(chave)
        if existente:
            for campo, valor in dados.items():
                setattr(existente, campo, valor)
            para_atualizar.append(existente)
        else:
            nova = GradePrecificacaoML(
                produto=produto, variacao=variacao, tipo_anuncio=tipo_grade, margem=margem_chave, **dados
            )
            para_criar.append(nova)
            existentes[chave] = nova


# Função Objetivo: Ponto de entrada chamado pelo popular_banco.
def calcular_grade_precificacao_ml(stdout, style):
    from django.db import connection
    from produtos.models import Produto
    from mercado_livre.models import (
        ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre,
        FreteML, VariacaoAnuncioMercadoLivre,
    )
    from precificacao.models import GradePrecificacaoML, ConfiguracaoOperacional, FaixaArmazenagem

    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio

    stdout.write('[GRADE DE PRECIFICAÇÃO ML] Calculando...')
    inicio_total = time.perf_counter()

    connection.force_debug_cursor = True
    connection.queries_log.clear()

    inicio_carga = time.perf_counter()
    produtos = list(Produto.objects.all())
    stdout.write(f'    {len(produtos)} produto(s) encontrados')

    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
    frete_todas = list(FreteML.objects.all())
    config_geral = ConfiguracaoOperacional.obter()
    faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

    variacoes_por_produto = defaultdict(list)
    total_variacoes = 0
    for v in VariacaoAnuncioMercadoLivre.objects.filter(
        produto__isnull=False, anuncio__tipo_de_anuncio__isnull=False
    ).select_related('anuncio__tipo_de_anuncio', 'produto'):
        variacoes_por_produto[v.produto.id].append(v)
        total_variacoes += 1
    stdout.write(f'    {total_variacoes} variação(ões)/MLB(s) publicado(s) encontrado(s)')

    existentes = {
        (r.produto_id, r.variacao_id, r.tipo_anuncio, r.margem): r
        for r in GradePrecificacaoML.objects.all()
    }

    tempo_carga = time.perf_counter() - inicio_carga
    stdout.write(f'  ⏱ Carregar produtos/config/variações/existentes/frete: {tempo_carga:.1f}s')

    para_criar = []
    para_atualizar = []
    erros = []
    sem_calculo = 0
    sem_dimensao = 0

    inicio_calculo = time.perf_counter()
    qtd_calculos = 0
    qtd_reaproveitados = 0
    total_produtos = len(produtos)

    for indice_produto, produto in enumerate(produtos, start=1):
        if indice_produto % 200 == 0 or indice_produto == total_produtos:
            decorrido = time.perf_counter() - inicio_calculo
            stdout.write(f'    ... {indice_produto}/{total_produtos} produtos processados ({decorrido:.1f}s)')

        variacoes_do_produto = variacoes_por_produto.get(produto.id, [])
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

            # * Fallback do produto (variacao=None) — sempre calculado, mesmo sem MLB publicado.
            dim_fallback = resolver_dimensoes_efetivas(produto, variacao=None)
            if dim_fallback is None:
                formulas_fallback, motivos_fallback = _formulas_sem_dimensao(config)
                sem_dimensao += len(formulas_fallback)
                _registrar_linhas(
                    produto, None, tipo_grade, formulas_fallback, motivos_fallback,
                    existentes, para_criar, para_atualizar,
                )
            else:
                resultado_fallback = _calcular_ou_reaproveitar(
                    _assinatura(dim_fallback), dim_fallback, produto, config, frete_todas,
                    faixas_armazenagem, config_geral, cache_formulas, None, tipo, erros
                )
                qtd_calculos += resultado_fallback['novos']
                qtd_reaproveitados += resultado_fallback['reaproveitados']
                sem_calculo += resultado_fallback['sem_calculo']
                _registrar_linhas(
                    produto, None, tipo_grade, resultado_fallback['formulas'], resultado_fallback['motivos'],
                    existentes, para_criar, para_atualizar,
                )

            # * Variações reais do tipo.
            for variacao in grupos[tipo]:
                dim = resolver_dimensoes_efetivas(produto, variacao=variacao)
                if dim is None:
                    formulas_variacao, motivos_variacao = _formulas_sem_dimensao(config)
                    sem_dimensao += len(formulas_variacao)
                    _registrar_linhas(
                        produto, variacao, tipo_grade, formulas_variacao, motivos_variacao,
                        existentes, para_criar, para_atualizar,
                    )
                    continue
                resultado = _calcular_ou_reaproveitar(
                    _assinatura(dim), dim, produto, config, frete_todas,
                    faixas_armazenagem, config_geral, cache_formulas, variacao, tipo, erros
                )
                qtd_calculos += resultado['novos']
                qtd_reaproveitados += resultado['reaproveitados']
                sem_calculo += resultado['sem_calculo']
                _registrar_linhas(
                    produto, variacao, tipo_grade, resultado['formulas'], resultado['motivos'],
                    existentes, para_criar, para_atualizar,
                )

    tempo_calculo_total = time.perf_counter() - inicio_calculo
    stdout.write(f'  ⏱ Loop de cálculo, total: {tempo_calculo_total:.1f}s')
    stdout.write(f'      ↳ Cálculos novos: {qtd_calculos}')
    stdout.write(f'      ↳ Reaproveitados (mesma assinatura): {qtd_reaproveitados}')

    inicio_salvar = time.perf_counter()

    campos_atualizaveis = [
        'preco', 'margem_percentual_obtida', 'frete_usado', 'origem_dimensao', 'detalhamento',
        'resolvida', 'motivo_nao_resolvida',
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
        f'    Sem cálculo possível (sem dimensão/peso de embalagem no ERP): {sem_dimensao}\n'
        f'    Erros de assert: {len(erros)}'
    ))

    if erros:
        stdout.write(style.ERROR('    ATENÇÃO — erros de assert encontrados:'))
        for erro in erros[:20]:
            stdout.write(style.ERROR(f'      {erro}'))
        if len(erros) > 20:
            stdout.write(style.ERROR(f'      ... e mais {len(erros) - 20} erro(s)'))

    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {len(connection.queries_log)}')