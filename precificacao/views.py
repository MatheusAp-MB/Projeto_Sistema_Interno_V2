from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q
from produtos.funcoes_auxiliares.filtros_produtos import listar_produtos_filtrados

# * [EXPLICAÇÃO] → As 8 combinações possíveis de filtro de faixa de
#                  preço — cada uma vira 2 campos na URL
#                  (preco_<chave>_min / preco_<chave>_max). Única
#                  fonte de verdade da combinação (tipo_anuncio real +
#                  margem_alvo real) por trás de cada chave amigável.
FAIXAS_PRECO_GRADE = {
    'classico_competicao': ('gold_special', 'competicao'),
    'classico_minima':     ('gold_special', 'minima'),
    'classico_padrao':     ('gold_special', 'padrao'),
    'classico_maxima':     ('gold_special', 'maxima'),
    'premium_competicao':  ('gold_pro', 'competicao'),
    'premium_minima':      ('gold_pro', 'minima'),
    'premium_padrao':      ('gold_pro', 'padrao'),
    'premium_maxima':      ('gold_pro', 'maxima'),
}


LABELS_MARGEM_FILTRO = {
    'competicao': 'Competição (5%)', 'minima': 'Mínima (10%)',
    'padrao': 'Padrão (15%)', 'maxima': 'Máxima (20%)',
}


def montar_filtros_preco(request, prefixo_tipo):
    """Monta a lista de 4 faixas de preço (uma por margem) já com
    nome do campo e valor atual prontos — o template só percorre e
    exibe, sem precisar calcular nome de campo dinamicamente."""
    resultado = []
    for margem in ['competicao', 'minima', 'padrao', 'maxima']:
        campo_min = f'preco_{prefixo_tipo}_{margem}_min'
        campo_max = f'preco_{prefixo_tipo}_{margem}_max'
        resultado.append({
            'label': LABELS_MARGEM_FILTRO[margem],
            'campo_min': campo_min,
            'campo_max': campo_max,
            'valor_min': request.GET.get(campo_min, ''),
            'valor_max': request.GET.get(campo_max, ''),
        })
    return resultado


LABELS_MARGEM_FILTRO = {
    'competicao': 'Competição (5%)', 'minima': 'Mínima (10%)',
    'padrao': 'Padrão (15%)', 'maxima': 'Máxima (20%)',
}


def montar_filtros_preco(request, prefixo_tipo):
    """Monta a lista de 4 faixas de preço (uma por margem) já com
    nome do campo e valor atual prontos — o template só percorre e
    exibe, sem precisar calcular nome de campo dinamicamente."""
    resultado = []
    for margem in ['competicao', 'minima', 'padrao', 'maxima']:
        campo_min = f'preco_{prefixo_tipo}_{margem}_min'
        campo_max = f'preco_{prefixo_tipo}_{margem}_max'
        resultado.append({
            'label': LABELS_MARGEM_FILTRO[margem],
            'campo_min': campo_min,
            'campo_max': campo_max,
            'valor_min': request.GET.get(campo_min, ''),
            'valor_max': request.GET.get(campo_max, ''),
        })
    return resultado


LABELS_MARGEM_FILTRO = {
    'competicao': 'Competição (5%)', 'minima': 'Mínima (10%)',
    'padrao': 'Padrão (15%)', 'maxima': 'Máxima (20%)',
}


def montar_filtros_preco(request, prefixo_tipo):
    """Monta a lista de 4 faixas de preço (uma por margem) já com
    nome do campo e valor atual prontos — o template só percorre e
    exibe, sem precisar calcular nome de campo dinamicamente."""
    resultado = []
    for margem in ['competicao', 'minima', 'padrao', 'maxima']:
        campo_min = f'preco_{prefixo_tipo}_{margem}_min'
        campo_max = f'preco_{prefixo_tipo}_{margem}_max'
        resultado.append({
            'label': LABELS_MARGEM_FILTRO[margem],
            'campo_min': campo_min,
            'campo_max': campo_max,
            'valor_min': request.GET.get(campo_min, ''),
            'valor_max': request.GET.get(campo_max, ''),
        })
    return resultado


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

    # * [EXPLICAÇÃO] → Reaproveita a busca/filtros já validados da
    #                  tela de Produtos (multi-palavra em Título/SKU/
    #                  EAN/Cód. Fabricante/Marca + Marca/Categoria/
    #                  Curva/Estoque/Custo) — não duplica essa lógica.
    filtros_produto = {
        'marcas': request.GET.getlist('marca'),
        'categorias': request.GET.getlist('categoria'),
        'curvas': request.GET.getlist('curva'),
        'estoque_min': request.GET.get('estoque_min', ''),
        'estoque_max': request.GET.get('estoque_max', ''),
        'custo_min': request.GET.get('custo_min', ''),
        'custo_max': request.GET.get('custo_max', ''),
    }
    produtos_qs = listar_produtos_filtrados(busca=busca or None, filtros=filtros_produto, ordenar='titulo')
    produtos_qs = produtos_qs.filter(grade_precificacao_ml__isnull=False).distinct()

    # * [EXPLICAÇÃO] → As 8 faixas de preço — cada uma filtra pela
    #                  linha ESPECÍFICA da Grade daquela combinação
    #                  (tipo × margem). unique_together garante só 1
    #                  linha por combinação, então min/max no MESMO
    #                  filter() sempre olham pra essa mesma linha —
    #                  nunca 2 linhas diferentes por engano.
    for chave, (tipo, margem) in FAIXAS_PRECO_GRADE.items():
        minimo = request.GET.get(f'preco_{chave}_min', '')
        maximo = request.GET.get(f'preco_{chave}_max', '')
        if minimo or maximo:
            condicoes = {
                'grade_precificacao_ml__tipo_anuncio__tipo_anuncio': tipo,
                'grade_precificacao_ml__margem_alvo': margem,
            }
            if minimo:
                condicoes['grade_precificacao_ml__preco_calculado__gte'] = minimo
            if maximo:
                condicoes['grade_precificacao_ml__preco_calculado__lte'] = maximo
            produtos_qs = produtos_qs.filter(**condicoes)

    produtos_qs = produtos_qs.distinct()

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
        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'categorias_disponiveis': Produto.objects.exclude(categoria__isnull=True).exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
        'curvas_disponiveis': Produto.objects.exclude(curva__isnull=True).exclude(curva='').values_list('curva', flat=True).distinct().order_by('curva'),
        'filtros_selecionados': {
            'marca': filtros_produto['marcas'],
            'categoria': filtros_produto['categorias'],
            'curva': filtros_produto['curvas'],
        },
        'get_params': request.GET,
        'filtros_preco_classico': montar_filtros_preco(request, 'classico'),
        'filtros_preco_premium': montar_filtros_preco(request, 'premium'),
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