#Views
from django.core.paginator import Paginator
from django.shortcuts import render

from mercado_livre.funcoes_auxiliares.classificacao_catalogo import (
    listar_skus_filtrados,
    classificar_lote_de_skus,
)

def view_hub_anuncios(request):
    from produtos.models import Produto
    from mercado_livre.models import TipoDeAnuncioMercadoLivre, CompeticaoCatalogo

    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')

    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    filtros = {
        'marcas': request.GET.getlist('marca'),
        'status': request.GET.getlist('status'),
        'tipos_anuncio': request.GET.getlist('tipo_anuncio'),
        'tipos_logisticos': request.GET.getlist('logistica'),
        'catalogos': request.GET.getlist('catalogo'),
        'flex': request.GET.getlist('flex'),
        'estoque': request.GET.getlist('estoque'),
        'faixas_score': request.GET.getlist('score'),
        'situacoes_competicao': request.GET.getlist('competicao'),
    }

    skus = listar_skus_filtrados(busca=busca or None, filtros=filtros)

    paginator = Paginator(skus, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    arvores = classificar_lote_de_skus(list(pagina.object_list), filtros=filtros)

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    mapa_status = dict(TipoDeAnuncioMercadoLivre.Status.choices)
    mapa_tipo_anuncio = dict(TipoDeAnuncioMercadoLivre.TipoAnuncio.choices)
    mapa_logistica = dict(TipoDeAnuncioMercadoLivre.TipoLogistico.choices)
    mapa_catalogo = dict(TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.choices)
    mapa_competicao = dict(CompeticaoCatalogo.StatusCompeticao.choices)
    mapa_flex = {'sim': 'Com Flex', 'nao': 'Sem Flex'}
    mapa_estoque = {'com': 'Com estoque', 'sem': 'Sem estoque'}
    mapa_score = {'ruim': 'Ruim', 'medio': 'Médio', 'bom': 'Bom', 'sem_dados': 'Sem dados'}

    chips_filtros_ativos = (
        [{'label': v} for v in filtros['marcas']] +
        [{'label': mapa_status.get(v, v)} for v in filtros['status']] +
        [{'label': mapa_tipo_anuncio.get(v, v)} for v in filtros['tipos_anuncio']] +
        [{'label': mapa_logistica.get(v, v)} for v in filtros['tipos_logisticos']] +
        [{'label': mapa_catalogo.get(v, v)} for v in filtros['catalogos']] +
        [{'label': mapa_flex.get(v, v)} for v in filtros['flex']] +
        [{'label': mapa_estoque.get(v, v)} for v in filtros['estoque']] +
        [{'label': mapa_score.get(v, v)} for v in filtros['faixas_score']] +
        [{'label': mapa_competicao.get(v, v)} for v in filtros['situacoes_competicao']]
    )

    return render(request, 'mercado_livre/estrutura_hub_anuncios.html', {
        'pagina': pagina,
        'arvores': arvores,
        'busca': busca,
        'por_pagina': por_pagina,
        'filtros': filtros,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),

        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True)
            .exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'opcoes_status': TipoDeAnuncioMercadoLivre.Status.choices,
        'opcoes_tipo_anuncio': TipoDeAnuncioMercadoLivre.TipoAnuncio.choices,
        'opcoes_logistica': TipoDeAnuncioMercadoLivre.TipoLogistico.choices,
        'opcoes_catalogo': TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.choices,
        'opcoes_situacao_competicao': CompeticaoCatalogo.StatusCompeticao.choices,

        'chips_filtros_ativos': chips_filtros_ativos,
    })

from mercado_livre.funcoes_auxiliares.qualidade_anuncio import montar_qualidade_da_folha


def view_qualidade_anuncio(request, mlb):
    dados = montar_qualidade_da_folha(mlb)
    return render(request, 'mercado_livre/estrutura_qualidade_anuncio.html', {'dados': dados})


VISIT_SHARE_LABELS = {
    'low': 'Baixo',
    'medium': 'Médio',
    'high': 'Alto',
}


def view_competicao_catalogo(request, mlb):
    from mercado_livre.models import AnuncioMercadoLivre

    anuncio = AnuncioMercadoLivre.objects.filter(
        mlb=mlb
    ).select_related('competicao', 'tipo_de_anuncio').prefetch_related('variacoes').first()

    if not anuncio or not hasattr(anuncio, 'competicao'):
        return render(request, 'mercado_livre/estrutura_competicao_catalogo.html', {'encontrado': False})

    competicao = anuncio.competicao
    variacao = anuncio.variacoes.first()

    BOOST_LABELS_CONHECIDOS = {
        'fulfillment', 'free_installments', 'free_shipping',
        'shipping_collect', 'same_day_shipping',
    }

    boosts_concluidos = []
    boosts_oportunidade = []
    boosts_novos = []

    for boost in (competicao.boosts or []):
        if boost.get('id') not in BOOST_LABELS_CONHECIDOS:
            boosts_novos.append(boost)
        elif boost.get('status') == 'boosted':
            boosts_concluidos.append(boost)
        elif boost.get('status') == 'opportunity':
            boosts_oportunidade.append(boost)
        else:
            boosts_novos.append(boost)

    winner = competicao.winner or {}
    winner_eh_outro = winner.get('item_id') and winner.get('item_id') != anuncio.mlb
    winner_link = f"https://produto.mercadolivre.com.br/{winner['item_id']}" if winner_eh_outro else None

    return render(request, 'mercado_livre/estrutura_competicao_catalogo.html', {
        'encontrado': True,
        'mlb': anuncio.mlb,
        'titulo': anuncio.titulo_anuncio,
        'permalink': anuncio.permalink,

        'status': competicao.get_status_display(),
        'status_classe': competicao.status,

        'current_price': competicao.current_price,
        'price_to_win': competicao.price_to_win,
        
        'sku': variacao.sku_ml if variacao else None,
        'imagem_url': (variacao.imagem_principal_url or variacao.thumbnail_url) if variacao else None,
        'visit_share': VISIT_SHARE_LABELS.get((competicao.visit_share or '').lower(), competicao.visit_share),
        'competitors_sharing_first_place': competicao.competitors_sharing_first_place,
        'consistent': competicao.consistent,
        'reason': competicao.reason,

        'winner_eh_outro': winner_eh_outro,
        'winner_item_id': winner.get('item_id'),
        'winner_price': winner.get('price'),
        'winner_link': winner_link,

        'boosts_concluidos': boosts_concluidos,
        'boosts_oportunidade': boosts_oportunidade,
        'boosts_novos': boosts_novos,

        'atualizado_em': anuncio.competicao.atualizado_em,
    })