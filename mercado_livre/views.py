from django.core.paginator import Paginator
from django.shortcuts import render

from mercado_livre.management.commands.validar_classificacao_suporte.classificacao_catalogo import (
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