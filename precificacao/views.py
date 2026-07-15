from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q


def view_grade_precificacao_ml(request):
    from precificacao.models import GradePrecificacaoML
    from produtos.models import Produto
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre

    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')
    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    # * [EXPLICAÇÃO] → Paginação é por PRODUTO, não por linha — cada
    #                  produto vira 1 card com 8 preços dentro (2
    #                  tipos × 4 margens).
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

    MargemAlvo = GradePrecificacaoML.MargemAlvo
    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
    ORDEM_MARGENS = [MargemAlvo.COMPETICAO, MargemAlvo.MINIMA, MargemAlvo.PADRAO, MargemAlvo.MAXIMA]

    CAMPO_POR_MARGEM = {
        MargemAlvo.MINIMA: 'margem_minima',
        MargemAlvo.PADRAO: 'margem_padrao',
        MargemAlvo.MAXIMA: 'margem_maxima',
        MargemAlvo.COMPETICAO: 'margem_competicao',
    }

    # * [EXPLICAÇÃO] → Config buscada 1 vez, fora do loop de produtos
    #                  (só 2 linhas no banco, mesma pra todo o
    #                  catálogo). Clássico e Premium têm CABEÇALHOS
    #                  SEPARADOS agora — cada um mostra o percentual
    #                  da SUA PRÓPRIA config, nunca assumindo que os
    #                  dois tipos compartilham o mesmo valor (deixou
    #                  de ser garantido: são editáveis de forma
    #                  independente na tela de Configurações).
    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}

    def labels_do_tipo(tipo):
        config = configs.get(tipo)
        labels = []
        for margem in ORDEM_MARGENS:
            valor = getattr(config, CAMPO_POR_MARGEM[margem], None) if config else None
            labels.append(f'{margem.label} ({valor:.0f}%)' if valor is not None else margem.label)
        return labels

    labels_classico = labels_do_tipo(TipoAnuncio.CLASSICO)
    labels_premium = labels_do_tipo(TipoAnuncio.PREMIUM)

    from mercado_livre.funcoes_auxiliares.badges import BADGES_TIPO_ANUNCIO, badge_de
    badge_classico = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.CLASSICO)
    badge_premium = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.PREMIUM)

    def montar_linhas(mapa, tipo):
        return [
            {
                'label': label, 'celula': mapa.get((tipo, margem)),
                'eh_padrao': margem == MargemAlvo.PADRAO, 'margem_chave': margem,
            }
            for margem, label in zip(ORDEM_MARGENS, labels_do_tipo(tipo))
        ]

    produtos_com_grade = []
    for produto in pagina.object_list:
        linhas_produto = grade_por_produto.get(produto.id, [])
        mapa = {(l.tipo_anuncio.tipo_anuncio, l.margem_alvo): l for l in linhas_produto}

        produtos_com_grade.append({
            'produto': produto,
            'linhas_classico': montar_linhas(mapa, TipoAnuncio.CLASSICO),
            'linhas_premium': montar_linhas(mapa, TipoAnuncio.PREMIUM),
        })

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'precificacao/estrutura_grade_precificacao_ml.html', {
        'pagina': pagina,
        'busca': busca,
        'por_pagina': por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'produtos_com_grade': produtos_com_grade,
        'badge_classico': badge_classico,
        'badge_premium': badge_premium,
        'tipo_classico': TipoAnuncio.CLASSICO,
        'tipo_premium': TipoAnuncio.PREMIUM,
    })


def view_grade_detalhe(request, produto_id, tipo, margem):
    from precificacao.models import GradePrecificacaoML

    linha = GradePrecificacaoML.objects.select_related('produto', 'tipo_anuncio').filter(
        produto_id=produto_id, tipo_anuncio__tipo_anuncio=tipo, margem_alvo=margem,
    ).first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
            'sem_detalhamento': True,
        })

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
        'det': linha.detalhamento,
        'tipo_label': linha.tipo_anuncio.get_tipo_anuncio_display(),
        'margem_label': linha.get_margem_alvo_display(),
        'produto_id': produto_id,
        'tipo': tipo,
    })