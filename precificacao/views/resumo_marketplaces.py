# precificacao/views/resumo_marketplaces.py

# Função Objetivo: Tela "tipo Excel" — todos os marketplaces lado a lado, 1 registro central.
# Explicação em detalhe: MARKETPLACES_RESUMO é a ÚNICA lista que precisa mudar quando um
# marketplace novo entra no Resumo (ou vira real, saindo de placeholder) — tudo o resto
# (colunas ordenáveis, anotações da query, cabeçalho, grupos de cada linha) é gerado a
# partir dela, em loop. Antes disso, cada marketplace precisava de edição manual em uns
# 5 lugares diferentes (dataclass, ordenável, annotate, colunas, template) — risco real
# de esquecer 1 deles (já aconteceu: B2W/Site nunca devia ter existido).

from dataclasses import dataclass, field
from django.core.paginator import Paginator
from django.db.models import Subquery, OuterRef, DecimalField
from django.shortcuts import render
from produtos.funcoes_auxiliares.filtros_produtos import listar_produtos_filtrados
from precificacao.views.comum import MARGENS, MARGENS_CHAVES, FiltrosGrade, montar_coluna_ordenavel, _opcoes_filtro_produto


# Função Objetivo: Representa 1 marketplace/tipo exibido no Resumo — a fonte da verdade única.
@dataclass(frozen=True)
class MarketplaceResumoConfig:
    chave: str            # usado em TUDO: nome de campo anotado, chave de ordenação, chave do dict de grupos
    label: str             # nome exibido no cabeçalho
    model: type | None     # None = ainda é placeholder (sem dado real)
    filtro_extra: dict = field(default_factory=dict)  # filtro extra além de produto+margem (ex: tipo_anuncio)

    @property
    def eh_real(self):
        return self.model is not None


# * [EXPLICAÇÃO] → Importa os models aqui dentro (não no topo do arquivo) — evita import
#                  circular, já que precificacao/models também referencia esse módulo
#                  indiretamente em alguns pontos do projeto.
def _montar_marketplaces_resumo():
    from precificacao.models import (
        GradePrecificacaoML, GradePrecificacaoMagalu, GradePrecificacaoRaia,
        GradePrecificacaoShopee, GradePrecificacaoTiktok,
    )
    return [
        MarketplaceResumoConfig('classico', 'Mercado Livre — Clássico', GradePrecificacaoML,
                                 {'tipo_anuncio': 'classico', 'variacao__isnull': True}),
        MarketplaceResumoConfig('premium', 'Mercado Livre — Premium', GradePrecificacaoML,
                                 {'tipo_anuncio': 'premium', 'variacao__isnull': True}),
        MarketplaceResumoConfig('shopee', 'Shopee', GradePrecificacaoShopee),
        MarketplaceResumoConfig('amazon', 'Amazon', None),
        MarketplaceResumoConfig('magalu', 'Magalu', GradePrecificacaoMagalu),
        MarketplaceResumoConfig('mais_correios', 'Mais Correios', None),
        MarketplaceResumoConfig('raia', 'Raia', GradePrecificacaoRaia),
        MarketplaceResumoConfig('tiktok_sem_afiliado', 'TikTok — Sem Afiliado', GradePrecificacaoTiktok,
                                 {'tipo': 'sem_afiliado'}),
        MarketplaceResumoConfig('tiktok_com_afiliado', 'TikTok — Com Afiliado', GradePrecificacaoTiktok,
                                 {'tipo': 'com_afiliado'}),
        MarketplaceResumoConfig('tudo_de_agro', 'Tudo de Agro', None),
    ]


MARKETPLACES_RESUMO = _montar_marketplaces_resumo()

CAMPOS_IDENTIFICACAO = {
    'curva': 'curva', 'cod_fabricante': 'cod_fabricante', 'ean': 'ean', 'sku': 'sku',
    'titulo': 'titulo', 'custo': 'custo', 'custo_com_boni': 'custo_com_boni',
}


# Função Objetivo: Monta {chave_ordenavel: campo_orm ou None} pra TODOS os marketplaces, de uma vez.
def _gerar_colunas_ordenaveis():
    colunas = dict(CAMPOS_IDENTIFICACAO)
    for mkt in MARKETPLACES_RESUMO:
        for sufixo in ('frete', 'preco', 'margem'):
            colunas[f'{mkt.chave}_{sufixo}'] = f'{mkt.chave}_{sufixo}_anotado' if mkt.eh_real else None
    return colunas


COLUNAS_ORDENAVEIS = _gerar_colunas_ordenaveis()
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


# Função Objetivo: Monta a subquery de 1 campo, de 1 marketplace, respeitando seu filtro extra.
def _subquery_marketplace(mkt, campo, margem_geral):
    return Subquery(
        mkt.model.objects.filter(
            produto=OuterRef('pk'), margem=margem_geral, **mkt.filtro_extra,
        ).values(campo)[:1],
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )


# Função Objetivo: Representa 1 marketplace/tipo exibido na linha — só formato, sem lógica.
@dataclass
class GrupoMarketplaceExibido:
    preco: object
    margem_percentual_obtida: object
    frete_usado: object

    @classmethod
    def de_linha(cls, linha):
        if not linha:
            return None
        return cls(
            preco=linha.preco,
            margem_percentual_obtida=linha.margem_percentual_obtida,
            frete_usado=linha.frete_usado,
        )

    @classmethod
    def de_anotado(cls, produto, chave):
        preco = getattr(produto, f'{chave}_preco_anotado', None)
        if preco is None:
            return None
        return cls(
            preco=preco,
            margem_percentual_obtida=getattr(produto, f'{chave}_margem_anotado', None),
            frete_usado=getattr(produto, f'{chave}_frete_anotado', None),
        )


# Função Objetivo: Emparelha 1 MarketplaceResumoConfig com o grupo calculado daquela linha.
# Explicação em detalhe: existe só pra o template poder iterar {% for celula in linha.grupos %}
# e ter, ao mesmo tempo, o marketplace (pra classe CSS) e o dado (preço/margem/frete) — sem
# precisar de chave dinâmica nenhuma (Django não suporta dict['variável'] nativamente).
@dataclass
class CelulaMarketplace:
    mkt: object
    grupo: object


# Função Objetivo: Representa 1 linha da tabela de Resumo — 1 produto, todos os marketplaces.
@dataclass
class LinhaResumoMarketplace:
    produto: object
    margem_atual: str
    # * [EXPLICAÇÃO] → LISTA, não dict — mesma ordem de MARKETPLACES_RESUMO,
    #                  igual colunas_grupos no cabeçalho. Evita precisar de
    #                  chave dinâmica no template (Django não suporta
    #                  dict['variavel'] nativamente); o template só faz
    #                  {% for grupo in linha.grupos %}, na mesma posição
    #                  de coluna que o cabeçalho já garante.
    grupos: list

    # Função Objetivo: Monta 1 linha buscando cada marketplace direto no banco (1 query cada).
    # Explicação em detalhe: usada só quando o seletor de margem de 1 LINHA muda (HTMX) —
    # nunca na listagem em massa, que usa montar_do_anotado (sem N+1).
    @classmethod
    def montar(cls, produto, margem_alvo):
        grupos = []
        for mkt in MARKETPLACES_RESUMO:
            if not mkt.eh_real:
                grupos.append(CelulaMarketplace(mkt=mkt, grupo=None))
                continue
            linha = mkt.model.objects.filter(produto=produto, margem=margem_alvo, **mkt.filtro_extra).first()
            grupos.append(CelulaMarketplace(mkt=mkt, grupo=GrupoMarketplaceExibido.de_linha(linha)))

        return cls(produto=produto, margem_atual=margem_alvo, grupos=grupos)

    # Função Objetivo: Monta a linha a partir dos campos JÁ ANOTADOS na query principal.
    @classmethod
    def montar_do_anotado(cls, produto, margem_alvo):
        grupos = [
            CelulaMarketplace(mkt=mkt, grupo=GrupoMarketplaceExibido.de_anotado(produto, mkt.chave))
            for mkt in MARKETPLACES_RESUMO
        ]
        return cls(produto=produto, margem_atual=margem_alvo, grupos=grupos)


# Função Objetivo: Exibe a tabela "tipo Excel" — 1 linha por produto, todos os marketplaces lado a lado.
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

    anotacoes = {}
    for mkt in MARKETPLACES_RESUMO:
        if not mkt.eh_real:
            continue
        anotacoes[f'{mkt.chave}_preco_anotado'] = _subquery_marketplace(mkt, 'preco', margem_geral)
        anotacoes[f'{mkt.chave}_margem_anotado'] = _subquery_marketplace(mkt, 'margem_percentual_obtida', margem_geral)
        anotacoes[f'{mkt.chave}_frete_anotado'] = _subquery_marketplace(mkt, 'frete_usado', margem_geral)

    produtos_qs = produtos_qs.annotate(**anotacoes)
    produtos_qs = produtos_qs.order_by(f'{"-" if direcao_ativa == "desc" else ""}{campo_orm}')

    paginator = Paginator(produtos_qs, filtros.por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    linhas_tabela = [LinhaResumoMarketplace.montar_do_anotado(produto, margem_geral) for produto in pagina.object_list]

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    def col(chave, label):
        return montar_coluna_ordenavel(request, chave, label, coluna_ativa, direcao_ativa)

    colunas = {chave: col(chave, label) for chave, label in {
        'curva': 'Curva', 'cod_fabricante': 'Cód Fab.', 'ean': 'Cód Barras', 'sku': 'SKU',
        'titulo': 'Descrição', 'custo': 'Custo', 'custo_com_boni': 'Custo c/Boni',
    }.items()}

    # * [EXPLICAÇÃO] → Lista de grupos (1 por marketplace), cada 1 já com
    #                  seus 3 ColunaOrdenavel prontos — evita precisar
    #                  montar chave dinâmica ("mkt.chave + '_frete'")
    #                  dentro do template, que o Django não suporta
    #                  nativamente sem filtro customizado.
    colunas_grupos = []
    for mkt in MARKETPLACES_RESUMO:
        grupo = {'mkt': mkt}
        for sufixo, label in [('frete', 'Frete'), ('preco', 'Preço'), ('margem', 'Margem')]:
            coluna = col(f'{mkt.chave}_{sufixo}', label)
            colunas[f'{mkt.chave}_{sufixo}'] = coluna
            grupo[sufixo] = coluna
        colunas_grupos.append(grupo)

    return render(request, 'precificacao/estrutura_resumo_marketplaces.html', {
        'pagina': pagina,
        'busca': filtros.busca,
        'por_pagina': filtros.por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'margem_geral': margem_geral,
        'opcoes_margem': [(m.chave, m.label_padrao) for m in MARGENS],
        'linhas_tabela': linhas_tabela,
        'colunas': colunas,
        'colunas_grupos': colunas_grupos,
        'marketplaces': MARKETPLACES_RESUMO,
        'filtros_selecionados': {
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        'get_params': request.GET,
        **_opcoes_filtro_produto(),
    })


# Função Objetivo: Reexibe 1 linha da tabela quando o seletor de margem DESSA linha muda.
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