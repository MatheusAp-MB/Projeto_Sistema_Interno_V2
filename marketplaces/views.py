from django.shortcuts import render
from .models import Marketplace

# * [EXPLICAÇÃO] → Mapeamento visual fixo, por sigla. O banco decide QUAIS
#                  marketplaces existem/estão ativos; aqui só decidimos
#                  COMO cada um aparece (nome de exibição, logo).
VISUAL_MARKETPLACES = {
    'ML':  {'nome': 'Mercado Livre', 'logo': 'marketplaces/img/logo_mercado_livre.png'},
    'SHOPEE':  {'nome': 'Shopee',        'logo': 'marketplaces/img/logo_shopee.png'},
    'MAGALU':  {'nome': 'Magalu',        'logo': 'marketplaces/img/logo_magalu.png'},
    'AMAZON':  {'nome': 'Amazon',        'logo': 'marketplaces/img/logo_amazon.png'},
    'TIKTOK':  {'nome': 'Tiktok Shop',   'logo': 'marketplaces/img/logo_tiktok_shop.png'},
    'CORREIOS': {'nome': 'Mais Correios', 'logo': 'marketplaces/img/logo_mais_correios.png'},
    'RAIA':    {'nome': 'Raia',          'logo': 'marketplaces/img/logo_raia.png'},
    'TD_AGRO':    {'nome': 'Tudo de Agro',  'logo': 'marketplaces/img/logo_tudo_de_agro.png'},
}

def view_marketplaces(request):
    marketplaces = []
    urls_marketplaces = {
        'ML': '/mercado-livre/anuncios/', 
    }

    for mp in Marketplace.objects.all():
        visual = VISUAL_MARKETPLACES.get(mp.sigla, {})
        marketplaces.append({
            'id':   mp.sigla,
            'nome': visual.get('nome', mp.nome),
            'logo': visual.get('logo'),
        })

    # * [EXPLICAÇÃO] → Um marketplace só recebe link clicável se
    #                  TEM uma URL real construída E está ativo.
    #                  Inativo sempre aparece como "em breve",
    #                  mesmo que a tela exista de verdade.
    urls_disponiveis = {
        mp.sigla: urls_marketplaces[mp.sigla]
        for mp in Marketplace.objects.filter(ativo=True)
        if mp.sigla in urls_marketplaces
    }

    return render(request, 'marketplaces/estrutura_marketplaces.html', {
        'marketplaces': marketplaces,
        'urls_marketplaces': urls_disponiveis,
    })