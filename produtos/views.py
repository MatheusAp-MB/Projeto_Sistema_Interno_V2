from django.shortcuts import render, get_object_or_404
from .models import Produto
from django.core.paginator import Paginator
from produtos.funcoes_auxiliares.filtros_produtos import (
    listar_produtos_filtrados, CAMPOS_ORDENACAO, CAMPOS_FAIXA,
)


def view_produtos(request):

    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')
    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    ordenar = request.GET.get('ordenar', 'titulo')
    if ordenar.lstrip('-') not in CAMPOS_ORDENACAO:
        ordenar = 'titulo'

    # * [EXPLICAÇÃO] → 3 filtros de checkbox (baixa cardinalidade) + 20
    #                  filtros de faixa (mín/máx), todos no mesmo dict —
    #                  aplicar_filtro_faixa() já sabe ler cada par
    #                  "<campo>_min"/"<campo>_max" direto daqui.
    filtros = {
        'marcas': request.GET.getlist('marca'),
        'categorias': request.GET.getlist('categoria'),
        'curvas': request.GET.getlist('curva'),
    }
    for campo in CAMPOS_FAIXA:
        filtros[f'{campo}_min'] = request.GET.get(f'{campo}_min', '')
        filtros[f'{campo}_max'] = request.GET.get(f'{campo}_max', '')

    produtos = listar_produtos_filtrados(
        busca=busca or None, filtros=filtros, ordenar=ordenar)

    paginator = Paginator(produtos, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    # * [EXPLICAÇÃO] → Rótulo amigável de cada coluna, numa única fonte
    #                  — usado tanto pros cabeçalhos ordenáveis quanto
    #                  pros chips de "filtro ativo" mais abaixo.
    LABELS_COLUNAS = {
        'ean': 'EAN', 'sku': 'SKU', 'cod_fabricante': 'Cód. Fabricante', 'ncm': 'NCM',
        'titulo': 'Nome', 'marca': 'Marca', 'categoria': 'Categoria', 'curva': 'Curva',
        'estoque': 'Estoque',
        'custo': 'Custo', 'custo_com_boni': 'Custo c/ Boni',
        'peso': 'Peso', 'peso_cubado': 'Peso Cubado', 'altura': 'Altura',
        'largura': 'Largura', 'profundidade': 'Profundidade',
        'mva': 'MVA', 'st_valor': 'ST Valor', 'icms_entrada': 'ICMS Entrada',
        'icms_saida_sp': 'ICMS Saída SP', 'icms_saida_media': 'ICMS Saída Média',
        'ipi': 'IPI', 'pis_cofins': 'PIS/COFINS', 'frete_cif_fob': 'Frete CIF/FOB',
        'ultima_compra': 'Última Compra', 'cadastrado_erp_em': 'Cadastro no ERP',
        'criado_em': 'Entrada no DB', 'atualizado_em': 'Atualização no DB',
    }

    # * [EXPLICAÇÃO] → Estrutura do painel de filtro por faixa, seguindo
    #                  exatamente as 6 seções que já existem no ERP —
    #                  não inventei agrupamento novo.
    SECOES_FILTRO_FAIXA = [
        {'titulo': 'Identificação', 'campos': [('estoque', 'Estoque')]},
        {'titulo': 'Dimensões', 'campos': [
            ('peso', 'Peso'), ('peso_cubado', 'Peso Cubado'), ('altura', 'Altura'),
            ('largura', 'Largura'), ('profundidade', 'Profundidade'),
        ]},
        {'titulo': 'Financeiro', 'campos': [
            ('custo', 'Custo'), ('custo_com_boni', 'Custo c/ Boni')]},
        {'titulo': 'Fiscal', 'campos': [
            ('ipi', 'IPI'), ('icms_entrada',
                             'ICMS Entrada'), ('icms_saida_sp', 'ICMS Saída SP'),
            ('icms_saida_media', 'ICMS Saída Média'), ('pis_cofins', 'PIS/COFINS'),
            ('mva', 'MVA'), ('st_valor',
                             'ST Valor'), ('frete_cif_fob', 'Frete CIF/FOB'),
        ]},
        {'titulo': 'Controle DB', 'campos': [
            ('criado_em', 'Entrada no DB'), ('atualizado_em', 'Atualização no DB')]},
        {'titulo': 'Controle ERP', 'campos': [
            ('ultima_compra', 'Última Compra'), ('cadastrado_erp_em', 'Cadastro no ERP')]},
    ]

    # * [EXPLICAÇÃO] → Monta o link/seta de cada cabeçalho ordenável —
    #                  mesmo padrão da tela de Resumo de Critérios.
    querystring_sem_ordenar_pagina = request.GET.copy()
    querystring_sem_ordenar_pagina.pop('ordenar', None)
    querystring_sem_ordenar_pagina.pop('pagina', None)
    base_qs = querystring_sem_ordenar_pagina.urlencode()

    def cabecalho(chave, label):
        ativo = ordenar.lstrip('-') == chave
        esta_asc = ativo and not ordenar.startswith('-')
        proximo = f'-{chave}' if esta_asc else chave
        if ativo:
            icone = 'fa-sort-up' if esta_asc else 'fa-sort-down'
        else:
            icone = 'fa-sort'
        return {'label': label, 'href': f'?{base_qs}&ordenar={proximo}', 'icone': icone, 'ativo': ativo}

    cabecalhos = {chave: cabecalho(chave, label)
                  for chave, label in LABELS_COLUNAS.items()}

    # * [EXPLICAÇÃO] → Chips de "filtro ativo": marca/categoria/curva
    #                  aparecem como estão; cada filtro de faixa vira
    #                  1 frase (ex: "Estoque: 10 até 50").
    chips_ativos = (
        [{'label': v} for v in filtros['marcas']] +
        [{'label': v} for v in filtros['categorias']] +
        [{'label': v} for v in filtros['curvas']]
    )
    for campo in CAMPOS_FAIXA:
        minimo = filtros.get(f'{campo}_min')
        maximo = filtros.get(f'{campo}_max')
        if minimo or maximo:
            label = LABELS_COLUNAS.get(campo, campo)
            if minimo and maximo:
                chips_ativos.append(
                    {'label': f'{label}: {minimo} até {maximo}'})
            elif minimo:
                chips_ativos.append(
                    {'label': f'{label}: a partir de {minimo}'})
            else:
                chips_ativos.append({'label': f'{label}: até {maximo}'})

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'produtos/estrutura_produtos.html', {
        'pagina': pagina,
        'busca': busca,
        'por_pagina': por_pagina,
        'filtros': filtros,
        'cabecalhos': cabecalhos,
        'chips_ativos': chips_ativos,
        'secoes_filtro_faixa': SECOES_FILTRO_FAIXA,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),

        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True)
        .exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'categorias_disponiveis': Produto.objects.exclude(categoria__isnull=True)
        .exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
        'curvas_disponiveis': Produto.objects.exclude(curva__isnull=True)
        .exclude(curva='').values_list('curva', flat=True).distinct().order_by('curva'),
    })


def view_painel_produto(request, produto_id):
    produto = get_object_or_404(Produto, pk=produto_id)
    return render(request, 'produtos/parciais/estrutura_parcial_painel_produto.html', {
        'produto': produto,
    })
