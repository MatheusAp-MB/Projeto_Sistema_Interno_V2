# precificacao/views/resumo_marketplaces.py

from dataclasses import dataclass
from django.core.paginator import Paginator
from django.shortcuts import render
from produtos.funcoes_auxiliares.filtros_produtos import listar_produtos_filtrados
from precificacao.views.comum import MARGENS, MARGENS_CHAVES, FiltrosGrade, montar_coluna_ordenavel, _opcoes_filtro_produto
from precificacao.views.grade_mercado_livre import subquery_grade_campo
from precificacao.views.grade_magalu import subquery_grade_magalu_campo


COLUNAS_ORDENAVEIS = {
    'curva': 'curva',
    'cod_fabricante': 'cod_fabricante',
    'ean': 'ean',
    'sku': 'sku',
    'titulo': 'titulo',
    'custo': 'custo',
    'custo_com_boni': 'custo_com_boni',
    'classico_frete': 'classico_frete_anotado',
    'classico_preco': 'classico_preco_anotado',
    'classico_margem': 'classico_margem_anotado',
    'premium_frete': 'premium_frete_anotado',
    'premium_preco': 'premium_preco_anotado',
    'premium_margem': 'premium_margem_anotado',
    'shopee_frete': None, 'shopee_preco': None, 'shopee_margem': None,
    'amazon_frete': None, 'amazon_preco': None, 'amazon_margem': None,
    'magalu_frete': 'magalu_frete_anotado', 'magalu_preco': 'magalu_preco_anotado', 'magalu_margem': 'magalu_margem_anotado',
    'tiktok_frete': None, 'tiktok_preco': None, 'tiktok_margem': None,
    'raia_frete': None, 'raia_preco': None, 'raia_margem': None,
    'b2w_frete': None, 'b2w_preco': None, 'b2w_margem': None,
}
COLUNA_ORDENACAO_PADRAO = 'titulo'


def _resolver_ordenacao(request):
    coluna = request.GET.get('ordenar', COLUNA_ORDENACAO_PADRAO)
    direcao = request.GET.get('direcao', 'asc')
    if direcao not in ('asc', 'desc'):
        direcao = 'asc'

    campo_orm = COLUNAS_ORDENAVEIS.get(coluna)
    if campo_orm is None:
        coluna = COLUNA_ORDENACAO_PADRAO
        campo_orm = COLUNAS_ORDENAVEIS[COLUNA_ORDENACAO_PADRAO]

    return coluna, direcao, campo_orm


@dataclass
class GrupoMarketplaceExibido:
    preco: object
    margem_percentual_obtida: object
    frete_usado: object


@dataclass
class LinhaResumoMarketplace:
    produto: object
    margem_atual: str
    classico: object
    premium: object
    magalu: object

    @classmethod
    def montar(cls, produto, margem_alvo):
        from precificacao.models import GradePrecificacaoML, GradePrecificacaoMagalu

        linhas = GradePrecificacaoML.objects.filter(
            produto=produto, variacao__isnull=True, margem=margem_alvo,
        )
        por_tipo = {linha.tipo_anuncio: linha for linha in linhas}

        def montar_grupo(tipo):
            linha = por_tipo.get(tipo)
            if not linha:
                return None
            return GrupoMarketplaceExibido(
                preco=linha.preco,
                margem_percentual_obtida=linha.margem_percentual_obtida,
                frete_usado=linha.frete_usado,
            )

        linha_magalu = GradePrecificacaoMagalu.objects.filter(produto=produto, margem=margem_alvo).first()
        magalu = None
        if linha_magalu:
            magalu = GrupoMarketplaceExibido(
                preco=linha_magalu.preco,
                margem_percentual_obtida=linha_magalu.margem_percentual_obtida,
                frete_usado=linha_magalu.frete_usado,
            )

        return cls(
            produto=produto,
            margem_atual=margem_alvo,
            classico=montar_grupo('classico'),
            premium=montar_grupo('premium'),
            magalu=magalu,
        )

    @classmethod
    def montar_do_anotado(cls, produto, margem_alvo):
        def montar_grupo(prefixo):
            preco = getattr(produto, f'{prefixo}_preco_anotado', None)
            if preco is None:
                return None
            return GrupoMarketplaceExibido(
                preco=preco,
                margem_percentual_obtida=getattr(produto, f'{prefixo}_margem_anotado', None),
                frete_usado=getattr(produto, f'{prefixo}_frete_anotado', None),
            )

        return cls(
            produto=produto,
            margem_atual=margem_alvo,
            classico=montar_grupo('classico'),
            premium=montar_grupo('premium'),
            magalu=montar_grupo('magalu'),
        )


def view_resumo_marketplaces(request):
    margem_geral = request.GET.get('margem', 'padrao')
    if margem_geral not in MARGENS_CHAVES:
        margem_geral = 'padrao'

    filtros = FiltrosGrade.montar(request)
    coluna_ativa, direcao_ativa, campo_orm = _resolver_ordenacao(request)

    produtos_qs = listar_produtos_filtrados(
        busca=filtros.busca or None, filtros=filtros.para_filtros_produto(), ordenar='titulo'
    )
    produtos_qs = produtos_qs.filter(grade_precificacao_ml__isnull=False).distinct()

    produtos_qs = produtos_qs.annotate(
        classico_preco_anotado=subquery_grade_campo('classico', 'preco', margem_geral),
        classico_margem_anotado=subquery_grade_campo('classico', 'margem_percentual_obtida', margem_geral),
        classico_frete_anotado=subquery_grade_campo('classico', 'frete_usado', margem_geral),
        premium_preco_anotado=subquery_grade_campo('premium', 'preco', margem_geral),
        premium_margem_anotado=subquery_grade_campo('premium', 'margem_percentual_obtida', margem_geral),
        premium_frete_anotado=subquery_grade_campo('premium', 'frete_usado', margem_geral),
        magalu_preco_anotado=subquery_grade_magalu_campo('preco', margem_geral),
        magalu_margem_anotado=subquery_grade_magalu_campo('margem_percentual_obtida', margem_geral),
        magalu_frete_anotado=subquery_grade_magalu_campo('frete_usado', margem_geral),
    )
    produtos_qs = produtos_qs.order_by(f'{"-" if direcao_ativa == "desc" else ""}{campo_orm}')

    paginator = Paginator(produtos_qs, filtros.por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    linhas_tabela = [LinhaResumoMarketplace.montar_do_anotado(produto, margem_geral) for produto in pagina.object_list]

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    def col(chave, label):
        return montar_coluna_ordenavel(request, chave, label, coluna_ativa, direcao_ativa)

    colunas = {
        'curva': col('curva', 'Curva'),
        'cod_fabricante': col('cod_fabricante', 'Cód Fab.'),
        'ean': col('ean', 'Cód Barras'),
        'sku': col('sku', 'SKU'),
        'titulo': col('titulo', 'Descrição'),
        'custo': col('custo', 'Custo'),
        'custo_com_boni': col('custo_com_boni', 'Custo c/Boni'),
        'classico_frete': col('classico_frete', 'Frete'),
        'classico_preco': col('classico_preco', 'Preço'),
        'classico_margem': col('classico_margem', 'Margem'),
        'premium_frete': col('premium_frete', 'Frete'),
        'premium_preco': col('premium_preco', 'Preço'),
        'premium_margem': col('premium_margem', 'Margem'),
        'shopee_frete': col('shopee_frete', 'Frete'),
        'shopee_preco': col('shopee_preco', 'Preço'),
        'shopee_margem': col('shopee_margem', 'Margem'),
        'amazon_frete': col('amazon_frete', 'Frete'),
        'amazon_preco': col('amazon_preco', 'Preço'),
        'amazon_margem': col('amazon_margem', 'Margem'),
        'magalu_frete': col('magalu_frete', 'Frete'),
        'magalu_preco': col('magalu_preco', 'Preço'),
        'magalu_margem': col('magalu_margem', 'Margem'),
        'tiktok_frete': col('tiktok_frete', 'Frete'),
        'tiktok_preco': col('tiktok_preco', 'Preço'),
        'tiktok_margem': col('tiktok_margem', 'Margem'),
        'raia_frete': col('raia_frete', 'Frete'),
        'raia_preco': col('raia_preco', 'Preço'),
        'raia_margem': col('raia_margem', 'Margem'),
        'b2w_frete': col('b2w_frete', 'Frete'),
        'b2w_preco': col('b2w_preco', 'Preço'),
        'b2w_margem': col('b2w_margem', 'Margem'),
    }

    return render(request, 'precificacao/estrutura_resumo_marketplaces.html', {
        'pagina': pagina,
        'busca': filtros.busca,
        'por_pagina': filtros.por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'margem_geral': margem_geral,
        'opcoes_margem': [(m.chave, m.label_padrao) for m in MARGENS],
        'linhas_tabela': linhas_tabela,
        'colunas': colunas,
        'filtros_selecionados': {
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        'get_params': request.GET,
        **_opcoes_filtro_produto(),
    })


def view_resumo_linha(request, produto_id):
    from django.shortcuts import get_object_or_404
    from produtos.models import Produto

    margem = request.GET.get('margem', 'padrao')
    if margem not in MARGENS_CHAVES:
        margem = 'padrao'

    produto = get_object_or_404(Produto, id=produto_id)
    linha = LinhaResumoMarketplace.montar(produto, margem)

    return render(request, 'precificacao/parciais/estrutura_parcial_resumo_linha.html', {
        'linha': linha,
        'opcoes_margem': [(m.chave, m.label_padrao) for m in MARGENS],
    })