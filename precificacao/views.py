from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q


def view_grade_precificacao_ml(request):
    from precificacao.models import GradePrecificacaoML
    from produtos.models import Produto

    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')
    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    # * [EXPLICAÇÃO] → Paginação é por PRODUTO, não por linha — cada
    #                  produto vira 1 card com até 28 preços dentro.
    produtos_qs = Produto.objects.filter(grade_precificacao_ml__isnull=False).distinct()
    if busca:
        produtos_qs = produtos_qs.filter(Q(ean__icontains=busca) | Q(titulo__icontains=busca))
    produtos_qs = produtos_qs.order_by('titulo')

    paginator = Paginator(produtos_qs, por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    produtos_ids = [p.id for p in pagina.object_list]
    linhas = GradePrecificacaoML.objects.filter(
        produto_id__in=produtos_ids
    ).select_related('tipo_anuncio')

    grade_por_produto = {}
    for linha in linhas:
        grade_por_produto.setdefault(linha.produto_id, []).append(linha)

    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre

    MargemAlvo = GradePrecificacaoML.MargemAlvo
    ORDEM_MARGEM_SIMPLES = [MargemAlvo.MINIMA, MargemAlvo.PADRAO, MargemAlvo.MAXIMA]
    ORDEM_MARGEM_CATALOGO = [MargemAlvo.COMPETICAO, MargemAlvo.MINIMA, MargemAlvo.PADRAO, MargemAlvo.MAXIMA]

    # * [EXPLICAÇÃO] → Os percentuais de cada margem-alvo vêm da
    #                  configuração global (mesmos pra todo o catálogo,
    #                  não variam por produto) — busca 1 vez só, fora
    #                  do loop de produtos, pra montar o cabeçalho tipo
    #                  "Mínima (10%)".
    CAMPO_POR_MARGEM = {
        MargemAlvo.MINIMA: 'margem_minima',
        MargemAlvo.PADRAO: 'margem_padrao',
        MargemAlvo.MAXIMA: 'margem_maxima',
        MargemAlvo.COMPETICAO: 'margem_competicao',
    }
    config_referencia = ConfiguracaoTipoAnuncioMercadoLivre.objects.filter(
        tipo_anuncio='gold_special', tipo_logistico='cross_docking'
    ).first()

    def label_com_percentual(margem):
        if config_referencia:
            valor = getattr(config_referencia, CAMPO_POR_MARGEM[margem], None)
            if valor is not None:
                return f'{margem.label} ({valor:.0f}%)'
        return margem.label


    # * [EXPLICAÇÃO] → Ordem fixa das 4 combinações de tipo×logística —
    #                  a mesma pras 2 sub-tabelas (Simples/Base e Catálogo).
    COMBINACOES = [
        ('gold_special', 'cross_docking', 'Clássico', 'Coleta'),
        ('gold_pro', 'cross_docking', 'Premium', 'Coleta'),
        ('gold_special', 'fulfillment', 'Clássico', 'FULL'),
        ('gold_pro', 'fulfillment', 'Premium', 'FULL'),
    ]

    def montar_tabela(mapa, catalogo_bool, ordem_margens):
        linhas_tabela = []
        for tipo, logistico, tipo_label, logistico_label in COMBINACOES:
            celulas = [mapa.get((tipo, logistico, catalogo_bool, margem)) for margem in ordem_margens]
            linhas_tabela.append({
                'tipo_label': tipo_label,
                'logistico_label': logistico_label,
                'eh_premium': tipo == 'gold_pro',
                'celulas': celulas,
            })
        return linhas_tabela

    produtos_com_grade = []
    for produto in pagina.object_list:
        linhas_produto = grade_por_produto.get(produto.id, [])
        mapa = {
            (l.tipo_anuncio.tipo_anuncio, l.tipo_anuncio.tipo_logistico, l.tipo_anuncio.catalogo, l.margem_alvo): l
            for l in linhas_produto
        }
        produtos_com_grade.append({
            'produto': produto,
            'tabela_simples': montar_tabela(mapa, False, ORDEM_MARGEM_SIMPLES),
            'tabela_catalogo': montar_tabela(mapa, True, ORDEM_MARGEM_CATALOGO),
        })

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'precificacao/estrutura_grade_precificacao_ml.html', {
        'pagina': pagina,
        'busca': busca,
        'por_pagina': por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'produtos_com_grade': produtos_com_grade,
        'labels_margem_simples': [label_com_percentual(m) for m in ORDEM_MARGEM_SIMPLES],
        'labels_margem_catalogo': [label_com_percentual(m) for m in ORDEM_MARGEM_CATALOGO],
    })