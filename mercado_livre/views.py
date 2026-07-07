#Views
from django.core.paginator import Paginator
from django.shortcuts import render

from mercado_livre.funcoes_auxiliares.classificacao_catalogo import (
    listar_skus_filtrados,
    classificar_lote_de_skus,
)


def view_hub_anuncios(request):
    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')

    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    skus = listar_skus_filtrados(busca=busca or None)

    paginator = Paginator(skus, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    # * [EXPLICAÇÃO] → Só processa a árvore completa dos SKUs da página
    #                  atual — nunca dos 1.639 de uma vez.
    arvores = classificar_lote_de_skus(list(pagina.object_list))

    return render(request, 'mercado_livre/estrutura_hub_anuncios.html', {
        'pagina': pagina,
        'arvores': arvores,
        'busca': busca,
        'por_pagina': por_pagina,
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