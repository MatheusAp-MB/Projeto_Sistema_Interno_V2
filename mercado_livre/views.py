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


def view_competicao_catalogo(request, mlb):
    from mercado_livre.models import AnuncioMercadoLivre

    anuncio = AnuncioMercadoLivre.objects.filter(mlb=mlb).select_related('competicao', 'tipo_de_anuncio').first()

    if not anuncio or not hasattr(anuncio, 'competicao'):
        return render(request, 'mercado_livre/estrutura_competicao_catalogo.html', {'encontrado': False})

    competicao = anuncio.competicao

    return render(request, 'mercado_livre/estrutura_competicao_catalogo.html', {
        'encontrado': True,
        'mlb': anuncio.mlb,
        'titulo': anuncio.titulo_anuncio,
        'status': competicao.get_status_display(),
        'status_classe': competicao.status,
        'current_price': competicao.current_price,
        'price_to_win': competicao.price_to_win,
        'visit_share': competicao.visit_share,
        'competitors_sharing_first_place': competicao.competitors_sharing_first_place,
        'reason': competicao.reason,
        'boosts': competicao.boosts,
        'winner': competicao.winner,
    })