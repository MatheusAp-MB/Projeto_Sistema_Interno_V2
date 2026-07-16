from django.shortcuts import render
from django.core.paginator import Paginator
from produtos.funcoes_auxiliares.filtros_produtos import listar_produtos_filtrados

# * [EXPLICAÇÃO] → Reformulado em 15/07 (mudança de base: GradePrecificacaoML
#                  agora é 1 linha por produto/variação, com as 8
#                  combinações (Clássico/Premium × 4 margens) como
#                  COLUNAS diretas — não mais linhas separadas por
#                  margem). Isso simplifica os filtros de faixa de
#                  preço: agora é 1 campo direto por combinação, sem
#                  precisar combinar tipo_anuncio+margem_alvo.
FAIXAS_PRECO_GRADE = {
    'classico_competicao': 'classico_competicao_preco',
    'classico_minima':     'classico_minima_preco',
    'classico_padrao':     'classico_padrao_preco',
    'classico_maxima':     'classico_maxima_preco',
    'premium_competicao':  'premium_competicao_preco',
    'premium_minima':      'premium_minima_preco',
    'premium_padrao':      'premium_padrao_preco',
    'premium_maxima':      'premium_maxima_preco',
}

ORDEM_MARGENS = ['competicao', 'minima', 'padrao', 'maxima']

LABELS_MARGEM_FILTRO = {
    'competicao': 'Competição (5%)', 'minima': 'Mínima (10%)',
    'padrao': 'Padrão (15%)', 'maxima': 'Máxima (20%)',
}

CAMPO_CONFIG_POR_MARGEM = {
    'minima': 'margem_minima', 'padrao': 'margem_padrao',
    'maxima': 'margem_maxima', 'competicao': 'margem_competicao',
}


def montar_filtros_preco(request, prefixo_tipo):
    """Monta a lista de 4 faixas de preço (uma por margem) já com
    nome do campo e valor atual prontos — o template só percorre e
    exibe, sem precisar calcular nome de campo dinamicamente."""
    resultado = []
    for margem in ORDEM_MARGENS:
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


def _labels_do_tipo(configs, tipo):
    """Rótulos com percentual real da config (ex: 'Padrão (15%)') —
    Clássico e Premium são editáveis de forma independente, cada um
    mostra o percentual da SUA PRÓPRIA config."""
    config = configs.get(tipo)
    labels = []
    for margem in ORDEM_MARGENS:
        valor = getattr(config, CAMPO_CONFIG_POR_MARGEM[margem], None) if config else None
        labels.append(f'{LABELS_MARGEM_FILTRO[margem].split(" (")[0]} ({valor:.0f}%)' if valor is not None else LABELS_MARGEM_FILTRO[margem])
    return labels


def _montar_linhas_margem(linha, prefixo, labels):
    """linha: 1 registro de GradePrecificacaoML (ou None). prefixo:
    'classico' ou 'premium'. Lê as 4 margens direto dos campos
    (classico_padrao_preco, classico_padrao_margem, etc) — não
    precisa mais juntar várias linhas do banco, já vem tudo na mesma."""
    resultado = []
    for margem_chave, label in zip(ORDEM_MARGENS, labels):
        preco = getattr(linha, f'{prefixo}_{margem_chave}_preco', None) if linha else None
        margem_valor = getattr(linha, f'{prefixo}_{margem_chave}_margem', None) if linha else None
        resultado.append({
            'label': label,
            'preco': preco,
            'margem': margem_valor,
            'eh_padrao': margem_chave == 'padrao',
            'margem_chave': margem_chave,
        })
    return resultado


def view_grade_precificacao_ml(request):
    from precificacao.models import GradePrecificacaoML
    from produtos.models import Produto
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre
    from mercado_livre.funcoes_auxiliares.badges import BADGES_TIPO_ANUNCIO, badge_de

    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

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

    # * [EXPLICAÇÃO] → As 8 faixas de preço filtram pela linha de
    #                  FALLBACK do produto (variacao=None) — é a
    #                  referência de planejamento, não um MLB
    #                  específico (filtrar por MLB multiplicaria
    #                  produtos de forma confusa quando há vários).
    for chave, campo_preco in FAIXAS_PRECO_GRADE.items():
        minimo = request.GET.get(f'preco_{chave}_min', '')
        maximo = request.GET.get(f'preco_{chave}_max', '')
        if minimo or maximo:
            condicoes = {'grade_precificacao_ml__variacao__isnull': True}
            if minimo:
                condicoes[f'grade_precificacao_ml__{campo_preco}__gte'] = minimo
            if maximo:
                condicoes[f'grade_precificacao_ml__{campo_preco}__lte'] = maximo
            produtos_qs = produtos_qs.filter(**condicoes)

    produtos_qs = produtos_qs.distinct()

    paginator = Paginator(produtos_qs, por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    produtos_ids = [p.id for p in pagina.object_list]

    linhas = GradePrecificacaoML.objects.filter(
        produto_id__in=produtos_ids
    ).select_related('variacao__anuncio__tipo_de_anuncio')

    # * [EXPLICAÇÃO] → Agrupa por produto: fallback (variacao=None) +
    #                  lista de linhas reais (1 por MLB publicado).
    fallback_por_produto = {}
    reais_por_produto = {}
    for linha in linhas:
        if linha.variacao_id is None:
            fallback_por_produto[linha.produto_id] = linha
        else:
            reais_por_produto.setdefault(linha.produto_id, []).append(linha)

    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
    labels_classico = _labels_do_tipo(configs, TipoAnuncio.CLASSICO)
    labels_premium = _labels_do_tipo(configs, TipoAnuncio.PREMIUM)

    badge_classico = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.CLASSICO)
    badge_premium = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.PREMIUM)

    def montar_card_mlb(linha):
        anuncio = linha.variacao.anuncio
        tipo_real = anuncio.tipo_de_anuncio.tipo_anuncio if anuncio.tipo_de_anuncio else None
        eh_classico = tipo_real == TipoAnuncio.CLASSICO
        prefixo = 'classico' if eh_classico else 'premium'
        labels = labels_classico if eh_classico else labels_premium
        return {
            'mlb': anuncio.mlb,
            'variacao_id': linha.variacao_id,
            'prefixo': prefixo,
            'tipo_valor': tipo_real,
            'badge': badge_classico if eh_classico else badge_premium,
            'frete_origem': linha.frete_classico_origem if eh_classico else linha.frete_premium_origem,
            'linhas': _montar_linhas_margem(linha, prefixo, labels),
        }

    produtos_com_grade = []
    for produto in pagina.object_list:
        fallback = fallback_por_produto.get(produto.id)
        reais = reais_por_produto.get(produto.id, [])

        cards_simples_base = []
        cards_catalogo = []
        for linha_real in reais:
            anuncio = linha_real.variacao.anuncio
            tipo_de_anuncio = anuncio.tipo_de_anuncio
            eh_catalogo = bool(tipo_de_anuncio and tipo_de_anuncio.classificacao_catalogo == Classificacao.CATALOGO)
            card = montar_card_mlb(linha_real)
            if eh_catalogo:
                cards_catalogo.append(card)
            else:
                cards_simples_base.append(card)

        produtos_com_grade.append({
            'produto': produto,
            'linhas_classico': _montar_linhas_margem(fallback, 'classico', labels_classico),
            'linhas_premium': _montar_linhas_margem(fallback, 'premium', labels_premium),
            'cards_simples_base': cards_simples_base,
            'cards_catalogo': cards_catalogo,
            'total_mlbs': len(reais),
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

    # * [EXPLICAÇÃO] → variacao vem por querystring (?variacao=<id>),
    #                  não pelo caminho da URL — ausente/vazio =
    #                  fallback do produto (variacao=None). Com
    #                  variação real, filtra pela linha específica
    #                  daquele MLB.
    variacao_id = request.GET.get('variacao') or None

    linha = GradePrecificacaoML.objects.filter(
        produto_id=produto_id, variacao_id=variacao_id,
    ).select_related('produto').first()

    if not linha:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
            'sem_detalhamento': True,
        })

    prefixo = 'classico' if tipo == 'gold_special' else 'premium'
    detalhamento_tipo = getattr(linha, f'{prefixo}_detalhamento', None) or {}
    det = dict(detalhamento_tipo.get(margem) or {})

    if not det:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
            'sem_detalhamento': True,
        })

    # * [EXPLICAÇÃO] → Percentual do frete sobre o preço final — só
    #                  informativo (não faz parte da fórmula em si,
    #                  frete não é uma taxa sobre o preço). Calculado
    #                  aqui, não no template (regra do projeto: conta
    #                  fica em Python).
    #
    #                  Decimal(str(...)) é necessário aqui: valores
    #                  dentro de um JSONField voltam do MySQL como
    #                  STRING (JSON não tem tipo Decimal nativo — o
    #                  DjangoJSONEncoder converte na gravação, e a
    #                  leitura não reconverte sozinha).
    from decimal import Decimal
    if det.get('preco_calculado'):
        det['frete_percentual_do_preco'] = (Decimal(str(det['frete_usado'])) / Decimal(str(det['preco_calculado']))) * 100
    else:
        det['frete_percentual_do_preco'] = None

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
        'det': det,
        'tipo_label': 'Clássico' if prefixo == 'classico' else 'Premium',
        'margem_label': LABELS_MARGEM_FILTRO.get(margem, margem),
        'produto_id': produto_id,
        'tipo': tipo,
        'variacao_id': variacao_id or '',
    })


def _montar_linha_resumo(produto, margem_alvo):
    """Monta o dict de 1 linha da tabela de resumo — SEMPRE a partir
    do FALLBACK do produto (variacao=None), a referência de
    planejamento. Reaproveitado pela tabela inteira (várias linhas) e
    pelo endpoint HTMX de 1 linha só."""
    from precificacao.models import GradePrecificacaoML

    linha = GradePrecificacaoML.objects.filter(produto=produto, variacao__isnull=True).first()

    def campo(prefixo, sufixo):
        return getattr(linha, f'{prefixo}_{margem_alvo}_{sufixo}', None) if linha else None

    return {
        'produto': produto,
        'margem_atual': margem_alvo,
        'classico_preco': campo('classico', 'preco'),
        'classico_margem': campo('classico', 'margem'),
        'classico_frete': linha.frete_classico_usado if linha else None,
        'premium_preco': campo('premium', 'preco'),
        'premium_margem': campo('premium', 'margem'),
        'premium_frete': linha.frete_premium_usado if linha else None,
    }


def view_resumo_marketplaces(request):
    from produtos.models import Produto
    from precificacao.models import GradePrecificacaoML

    margens_validas = ORDEM_MARGENS

    margem_geral = request.GET.get('margem', 'padrao')
    if margem_geral not in margens_validas:
        margem_geral = 'padrao'

    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')
    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

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

    paginator = Paginator(produtos_qs, por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    linhas_tabela = [_montar_linha_resumo(produto, margem_geral) for produto in pagina.object_list]

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'precificacao/estrutura_resumo_marketplaces.html', {
        'pagina': pagina,
        'busca': busca,
        'por_pagina': por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'margem_geral': margem_geral,
        'opcoes_margem': [(m, LABELS_MARGEM_FILTRO[m]) for m in ORDEM_MARGENS],
        'linhas_tabela': linhas_tabela,
        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'categorias_disponiveis': Produto.objects.exclude(categoria__isnull=True).exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
        'curvas_disponiveis': Produto.objects.exclude(curva__isnull=True).exclude(curva='').values_list('curva', flat=True).distinct().order_by('curva'),
        'filtros_selecionados': {
            'marca': filtros_produto['marcas'],
            'categoria': filtros_produto['categorias'],
            'curva': filtros_produto['curvas'],
        },
        'get_params': request.GET,
    })


def view_resumo_linha(request, produto_id):
    from django.shortcuts import get_object_or_404
    from produtos.models import Produto

    margem = request.GET.get('margem', 'padrao')
    if margem not in ORDEM_MARGENS:
        margem = 'padrao'

    produto = get_object_or_404(Produto, id=produto_id)
    linha = _montar_linha_resumo(produto, margem)

    return render(request, 'precificacao/parciais/estrutura_parcial_resumo_linha.html', {
        'linha': linha,
        'opcoes_margem': [(m, LABELS_MARGEM_FILTRO[m]) for m in ORDEM_MARGENS],
    })