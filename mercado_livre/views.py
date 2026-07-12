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
    from mercado_livre.funcoes_auxiliares.badges import (
        BADGES_STATUS, BADGES_TIPO_ANUNCIO, BADGES_LOGISTICA, BADGES_CATALOGO,
        BADGE_FLEX_ATIVO, BADGE_FLEX_INATIVO,
        badge_de, badge_flex, opcoes_com_badge,
    )

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
        'desconto': request.GET.getlist('desconto'),
        'conexao_erp': request.GET.getlist('conexao_erp'),
        'faixas_score': request.GET.getlist('score'),
        'situacoes_competicao': request.GET.getlist('competicao'),
    }

    skus, total_anuncios_filtrados = listar_skus_filtrados(busca=busca or None, filtros=filtros)

    paginator = Paginator(skus, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    arvores = classificar_lote_de_skus(list(pagina.object_list), filtros=filtros)

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    querystring_atual = request.GET.urlencode()

    mapa_competicao = dict(CompeticaoCatalogo.StatusCompeticao.choices)
    mapa_estoque = {'com': 'Com estoque', 'sem': 'Sem estoque'}
    mapa_desconto = {'com': 'Com desconto', 'sem': 'Sem desconto'}
    mapa_conexao_erp = {'com': 'Com conexão ERP', 'sem': 'Sem conexão ERP'}
    mapa_score = {'ruim': 'Ruim', 'medio': 'Médio', 'bom': 'Bom', 'sem_dados': 'Sem dados'}

    # * [EXPLICAÇÃO] → Status/Tipo/Logística/Flex/Catálogo usam o mesmo
    #                  registro de badges do Resumo de Critérios agora
    #                  (badges.py). Estoque/Score/Competição ficam de
    #                  fora desse sistema — são conceitos diferentes,
    #                  sem badge própria ainda.
    chips_ativos = (
        [{'label': marca, 'classe': None, 'icone': None} for marca in filtros['marcas']] +
        [badge_de(BADGES_STATUS, v) for v in filtros['status']] +
        [badge_de(BADGES_TIPO_ANUNCIO, v) for v in filtros['tipos_anuncio']] +
        [badge_de(BADGES_LOGISTICA, v) for v in filtros['tipos_logisticos']] +
        [badge_de(BADGES_CATALOGO, v) for v in filtros['catalogos']] +
        [badge_flex(v == 'sim') for v in filtros['flex']] +
        [{'label': mapa_estoque.get(v, v), 'classe': None, 'icone': None} for v in filtros['estoque']] +
        [{'label': mapa_desconto.get(v, v), 'classe': None, 'icone': None} for v in filtros['desconto']] +
        [{'label': mapa_conexao_erp.get(v, v), 'classe': None, 'icone': None} for v in filtros['conexao_erp']] +
        [{'label': mapa_score.get(v, v), 'classe': None, 'icone': None} for v in filtros['faixas_score']] +
        [{'label': mapa_competicao.get(v, v), 'classe': None, 'icone': None} for v in filtros['situacoes_competicao']]
    )

    return render(request, 'mercado_livre/estrutura_hub_anuncios.html', {
        'pagina': pagina,
        'arvores': arvores,
        'busca': busca,
        'por_pagina': por_pagina,
        'filtros': filtros,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'total_anuncios_filtrados': total_anuncios_filtrados,

        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True)
            .exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'opcoes_status': opcoes_com_badge(BADGES_STATUS),
        'opcoes_tipo_anuncio': opcoes_com_badge(BADGES_TIPO_ANUNCIO),
        'opcoes_logistica': opcoes_com_badge(BADGES_LOGISTICA),
        'opcoes_catalogo': opcoes_com_badge(BADGES_CATALOGO),
        'opcoes_situacao_competicao': CompeticaoCatalogo.StatusCompeticao.choices,
        'badge_flex_ativo': BADGE_FLEX_ATIVO,
        'badge_flex_inativo': BADGE_FLEX_INATIVO,

        'chips_ativos': chips_ativos,
        'querystring_atual': querystring_atual,
    })

from mercado_livre.funcoes_auxiliares.qualidade_anuncio import montar_qualidade_da_folha


def view_qualidade_anuncio(request, mlb):
    from django.urls import reverse

    dados = montar_qualidade_da_folha(mlb)
    voltar = request.GET.get('voltar', '')
    voltar_url = f"{reverse('mercado_livre_anuncios')}?{voltar}" if voltar else reverse('mercado_livre_anuncios')

    return render(request, 'mercado_livre/estrutura_qualidade_anuncio.html', {
        'dados': dados,
        'voltar_url': voltar_url,
    })


VISIT_SHARE_LABELS = {
    'low': 'Baixo',
    'medium': 'Médio',
    'high': 'Alto',
}


def view_competicao_catalogo(request, mlb):
    from django.urls import reverse
    from mercado_livre.models import AnuncioMercadoLivre

    voltar = request.GET.get('voltar', '')
    voltar_url = f"{reverse('mercado_livre_anuncios')}?{voltar}" if voltar else reverse('mercado_livre_anuncios')

    anuncio = AnuncioMercadoLivre.objects.filter(
        mlb=mlb
    ).select_related('competicao', 'tipo_de_anuncio').prefetch_related('variacoes').first()

    if not anuncio or not hasattr(anuncio, 'competicao'):
        return render(request, 'mercado_livre/estrutura_competicao_catalogo.html', {
            'encontrado': False,
            'voltar_url': voltar_url,
        })

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
        'voltar_url': voltar_url,
    })

def view_resumo_criterios(request):
    from django.db.models import Prefetch
    from mercado_livre.models import (
        CriterioQualidade, QualidadeAnuncioCriterio, TipoDeAnuncioMercadoLivre,
    )
    from produtos.models import Produto
    from mercado_livre.funcoes_auxiliares.qualidade_anuncio import GRUPO_CORES
    from mercado_livre.funcoes_auxiliares.resumo_criterios import (
        listar_variacoes_resumo_filtradas, CAMPOS_ORDENACAO,
    )
    from mercado_livre.funcoes_auxiliares.badges import (
        BADGES_STATUS, BADGES_TIPO_ANUNCIO, BADGES_LOGISTICA, BADGES_CATALOGO,
        BADGE_FLEX_ATIVO, BADGE_FLEX_INATIVO,
        badge_de, badge_flex, opcoes_com_badge,
    )

    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')
    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    ordenar = request.GET.get('ordenar', 'sku')
    if ordenar.lstrip('-') not in CAMPOS_ORDENACAO:
        ordenar = 'sku'

    criterios = list(CriterioQualidade.objects.order_by('grupo', 'rule_key'))

    # * [EXPLICAÇÃO] → Filtro em grade: 1 GET param por critério
    #                  (crit_<rule_key>), cada um multi-select.
    criterios_grid_filtro = {}
    for c in criterios:
        valores = request.GET.getlist(f'crit_{c.rule_key}')
        if valores:
            criterios_grid_filtro[c.rule_key] = valores

    filtros = {
        'marcas': request.GET.getlist('marca'),
        'status': request.GET.getlist('status'),
        'tipos_anuncio': request.GET.getlist('tipo_anuncio'),
        'tipos_logisticos': request.GET.getlist('logistica'),
        'catalogos': request.GET.getlist('catalogo'),
        'flex': request.GET.getlist('flex'),
        'criterios_grid': criterios_grid_filtro,
    }

    # * [EXPLICAÇÃO] → Versão "pronta pro template" dos critérios: já traz
    #                  a cor do grupo e quais checkboxes devem vir marcados
    #                  (Django template não faz lookup de dict por chave
    #                  variável, então resolve isso aqui em vez de lá).
    criterios_para_filtro = [
        {
            'rule_key': c.rule_key,
            'pergunta': c.pergunta,
            'cor': GRUPO_CORES.get(c.grupo, GRUPO_CORES['DESCONHECIDO']),
            'selecionados': criterios_grid_filtro.get(c.rule_key, []),
        }
        for c in criterios
    ]

    colunas = [
        {
            'rule_key': c.rule_key,
            'pergunta': c.pergunta,
            'cor': GRUPO_CORES.get(c.grupo, GRUPO_CORES['DESCONHECIDO']),
        }
        for c in criterios
    ]

    variacoes = listar_variacoes_resumo_filtradas(
        busca=busca or None, filtros=filtros, ordenar=ordenar,
    ).prefetch_related(
        Prefetch(
            'qualidade__criterios',
            queryset=QualidadeAnuncioCriterio.objects.select_related('criterio'),
        )
    )

    paginator = Paginator(variacoes, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    opcoes_status_badges = opcoes_com_badge(BADGES_STATUS)
    opcoes_tipo_anuncio_badges = opcoes_com_badge(BADGES_TIPO_ANUNCIO)
    opcoes_logistica_badges = opcoes_com_badge(BADGES_LOGISTICA)
    # * [EXPLICAÇÃO] → "Anúncio de Catálogo" nunca aparece nessa tela
    #                  (a query já exclui isso na base), então oferecer
    #                  esse filtro aqui seria uma opção que sempre dá 0
    #                  resultado — removido só pra essa tela.
    opcoes_catalogo_badges = [
        opcao for opcao in opcoes_com_badge(BADGES_CATALOGO) if opcao['valor'] != 'catalogo'
    ]

    linhas = []
    for variacao in pagina.object_list:
        anuncio = variacao.anuncio
        tipo = anuncio.tipo_de_anuncio
        qualidade = getattr(variacao, 'qualidade', None)

        resultado_por_rule_key = {}
        if qualidade:
            for avaliacao in qualidade.criterios.all():
                resultado_por_rule_key[avaliacao.criterio.rule_key] = avaliacao.status

        resultados = [
            {
                'status': resultado_por_rule_key.get(c.rule_key),
                'cor': GRUPO_CORES.get(c.grupo, GRUPO_CORES['DESCONHECIDO']),
            }
            for c in criterios
        ]

        linhas.append({
            'imagem_url': variacao.imagem_principal_url or variacao.thumbnail_url,
            'sku': variacao.produto.sku,
            'mlb': anuncio.mlb,
            'marca': variacao.produto.marca,
            'titulo': anuncio.titulo_anuncio,

            'badge_status': badge_de(BADGES_STATUS, tipo.status) if tipo else None,
            'badge_tipo_anuncio': badge_de(BADGES_TIPO_ANUNCIO, tipo.tipo_anuncio) if tipo else None,
            'badge_logistica': badge_de(BADGES_LOGISTICA, tipo.tipo_logistico) if tipo else None,
            'badge_flex': badge_flex(bool(tipo and tipo.flex)),
            'badge_catalogo': badge_de(BADGES_CATALOGO, tipo.classificacao_catalogo) if tipo else None,

            'sem_dado_qualidade': qualidade is None,
            'score': qualidade.score if qualidade else None,
            'nivel': qualidade.nivel if qualidade else None,
            'resultados': resultados,
        })

    # * [EXPLICAÇÃO] → Monta o link/seta de cada cabeçalho ordenável.
    #                  Clicar de novo na mesma coluna inverte a direção;
    #                  clicar numa coluna diferente começa em ascendente.
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
        return {
            'label': label,
            'href': f'?{base_qs}&ordenar={proximo}',
            'icone': icone,
            'ativo': ativo,
        }

    cabecalhos = {
        'sku': cabecalho('sku', 'SKU'),
        'mlb': cabecalho('mlb', 'MLB'),
        'marca': cabecalho('marca', 'Marca'),
        'titulo': cabecalho('titulo', 'Título do anúncio'),
        'status': cabecalho('status', 'Situação'),
        'tipo_anuncio': cabecalho('tipo_anuncio', 'Tipo de anúncio'),
        'tipo_logistico': cabecalho('tipo_logistico', 'Logística'),
        'flex': cabecalho('flex', 'Flex'),
        'catalogo': cabecalho('catalogo', 'Situação do catálogo'),
        'score': cabecalho('score', 'Score'),
        'nivel': cabecalho('nivel', 'Nível'),
    }
    chips_ativos = (
        [{'label': marca, 'classe': None, 'icone': None} for marca in filtros['marcas']] +
        [badge_de(BADGES_STATUS, v) for v in filtros['status']] +
        [badge_de(BADGES_TIPO_ANUNCIO, v) for v in filtros['tipos_anuncio']] +
        [badge_de(BADGES_LOGISTICA, v) for v in filtros['tipos_logisticos']] +
        [badge_de(BADGES_CATALOGO, v) for v in filtros['catalogos']] +
        [badge_flex(v == 'sim') for v in filtros['flex']]
    )

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'mercado_livre/estrutura_resumo_criterios.html', {
        'pagina': pagina,
        'linhas': linhas,
        'colunas': colunas,
        'busca': busca,
        'por_pagina': por_pagina,
        'filtros': filtros,
        'cabecalhos': cabecalhos,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),

        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True)
            .exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'opcoes_status': opcoes_status_badges,
        'opcoes_tipo_anuncio': opcoes_tipo_anuncio_badges,
        'opcoes_logistica': opcoes_logistica_badges,
        'opcoes_catalogo': opcoes_catalogo_badges,
        'badge_flex_ativo': BADGE_FLEX_ATIVO,
        'badge_flex_inativo': BADGE_FLEX_INATIVO,
        'criterios_para_filtro': criterios_para_filtro,

        'chips_ativos': chips_ativos,
    })

def view_tabela_frete_ml(request):
    from mercado_livre.models import FreteML

    # * [EXPLICAÇÃO] → Busca as faixas de preço únicas pra montar os
    #                  cabeçalhos da tabela.
    faixas_preco = FreteML.objects.values(
        'preco_min', 'preco_max'
    ).distinct().order_by('preco_min')

    # * [EXPLICAÇÃO] → Busca as faixas de peso únicas pra montar as
    #                  linhas da tabela.
    faixas_peso = FreteML.objects.values(
        'peso_min', 'peso_max'
    ).distinct().order_by('peso_min')

    # * [EXPLICAÇÃO] → Monta um dicionário de lookup (peso_min, preco_min)
    #                  → valor pra montar a matriz sem múltiplas queries.
    lookup = {
        (float(f.peso_min), float(f.preco_min)): f.valor
        for f in FreteML.objects.all()
    }

    linhas = []
    for peso in faixas_peso:
        linha = {
            'peso_min': peso['peso_min'],
            'peso_max': peso['peso_max'],
            'valores': [
                {
                    'preco_min': preco['preco_min'],
                    'preco_max': preco['preco_max'],
                    'valor': lookup.get((float(peso['peso_min']), float(preco['preco_min'])))
                }
                for preco in faixas_preco
            ]
        }
        linhas.append(linha)

    return render(request, 'mercado_livre/estrutura_tabela_frete_ml.html', {
        'faixas_preco': faixas_preco,
        'linhas': linhas,
    })


def view_calcular_frete_ml(request):
    from decimal import Decimal
    from django.db.models import Q
    from mercado_livre.models import FreteML

    try:
        peso = Decimal(request.POST.get('peso', '0'))
        preco = Decimal(request.POST.get('preco', '0'))

        frete = FreteML.objects.filter(
            peso_min__lte=peso,
            preco_min__lte=preco
        ).filter(
            Q(peso_max__gte=peso) | Q(peso_max__isnull=True)
        ).filter(
            Q(preco_max__gte=preco) | Q(preco_max__isnull=True)
        ).first()

        if frete:
            return render(request, 'mercado_livre/parciais/estrutura_parcial_resultado_frete_ml.html', {
                'valor': frete.valor,
                'peso_min': frete.peso_min,
                'preco_min': frete.preco_min,
            })

        return render(request, 'mercado_livre/parciais/estrutura_parcial_resultado_frete_ml.html', {
            'valor': None,
        })

    except Exception as e:
        return render(request, 'mercado_livre/parciais/estrutura_parcial_resultado_frete_ml.html', {
            'valor': None,
            'erro': str(e),
        })
    

def view_recomendacao_precificacao(request):
    from decimal import Decimal
    from django.urls import reverse
    from mercado_livre.models import AnuncioMercadoLivre
    from mercado_livre.funcoes_auxiliares.promocoes_json import buscar_promocoes_do_mlb
    from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_margem, buscar_configuracao_tipo_anuncio
    from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import (
        recomendar_precificacao, melhor_margem, COMPORTAMENTOS,
    )

    mlb = request.GET.get('mlb', '').strip().upper()
    comportamento = request.GET.get('comportamento', 'padrao')
    if comportamento not in COMPORTAMENTOS:
        comportamento = 'padrao'

    voltar = request.GET.get('voltar', '')
    voltar_url = f"{reverse('mercado_livre_anuncios')}?{voltar}" if voltar else reverse('mercado_livre_anuncios')

    contexto = {
        'busca': mlb,
        'comportamento_atual': comportamento,
        'opcoes_comportamento': COMPORTAMENTOS,
        'voltar_url': voltar_url,
    }

    if not mlb:
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    anuncio = AnuncioMercadoLivre.objects.select_related('tipo_de_anuncio', 'competicao').filter(mlb=mlb).first()
    if not anuncio:
        contexto['erro'] = f'MLB {mlb} não encontrado no banco Django.'
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    variacao = anuncio.variacoes.select_related('produto').first()
    if not variacao or not variacao.produto:
        contexto['erro'] = f'MLB {mlb} não tem Produto vinculado — sem custo/dimensões, não dá pra calcular margem.'
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    produto = variacao.produto
    tipo_anuncio_obj = anuncio.tipo_de_anuncio
    if not tipo_anuncio_obj:
        contexto['erro'] = f'MLB {mlb} não tem Tipo de Anúncio vinculado — não dá pra saber comissão/margem.'
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    # * [EXPLICAÇÃO] → Configuração real (comissão, margens) pra essa
    #                  combinação exata de tipo/logística/catálogo —
    #                  buscada 1 vez aqui, reaproveitada no resto da view.
    config_tipo = buscar_configuracao_tipo_anuncio(tipo_anuncio_obj)
    if not config_tipo:
        contexto['erro'] = f'Nenhuma configuração encontrada pra esse tipo de anúncio (isso não deveria acontecer — as 8 combinações já foram seedadas).'
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    # * [EXPLICAÇÃO] → Hoje o corte de segurança é sempre margem_padrao
    #                  (regra de negócio atual: "tudo que vendemos tem
    #                  que estar acima de 15%"). margem_minima/maxima/
    #                  competicao já existem na configuração, esperando
    #                  uma tela futura onde o usuário escolhe qual delas
    #                  usar como corte — não fixar isso além do padrão
    #                  sem essa decisão de UI existir ainda.
    margem_minima = config_tipo.margem_padrao
    contexto['margem_minima'] = margem_minima

    from mercado_livre.funcoes_auxiliares.classificacao_catalogo import info_variacao
    from mercado_livre.funcoes_auxiliares.badges import BADGES_CATALOGO, badge_de

    # * [EXPLICAÇÃO] → Reaproveita a mesma função que já monta o card do
    #                  Hub (termômetro, badges de Status/Tipo/Logística/
    #                  Flex, preço/desconto) — nunca duplicar essa lógica.
    info = info_variacao(variacao, imagem_url=produto.imagem_url, titulo_produto=produto.titulo)
    contexto['info'] = info
    contexto['marca'] = produto.marca
    contexto['badge_catalogo'] = badge_de(BADGES_CATALOGO, tipo_anuncio_obj.classificacao_catalogo)

    contexto['titulo'] = anuncio.titulo_anuncio
    contexto['sku'] = produto.sku
    contexto['tipo_anuncio_label'] = tipo_anuncio_obj.get_tipo_anuncio_display()
    contexto['preco_atual'] = variacao.preco_atual

    margem_atual = None
    if variacao.preco_atual:
        margem_atual = calcular_margem(produto, variacao.preco_atual, tipo_anuncio_obj)
        contexto['margem_atual'] = margem_atual

    price_to_win = None
    eh_catalogo = hasattr(anuncio, 'competicao')
    contexto['eh_catalogo'] = eh_catalogo
    if eh_catalogo:
        competicao = anuncio.competicao
        price_to_win = competicao.price_to_win
        contexto['competicao_status'] = competicao.get_status_display() if competicao.status else None
        contexto['competicao_price_to_win'] = price_to_win
        contexto['competicao_current_price'] = competicao.current_price

    linhas = []

    if eh_catalogo and price_to_win:
        margem_preco_direto = calcular_margem(produto, price_to_win, tipo_anuncio_obj)
        linhas.append({
            'nome': 'Preço direto para ganhar',
            'tipo': 'PRECO_DIRETO',
            'status': None,
            'vigencia': None,
            'preco_original': variacao.preco_atual,
            'preco_promocional': price_to_win,
            'tem_rebate': False,
            'meli_percentage': None,
            'seller_percentage': None,
            'rebate_valor_reais': Decimal('0'),
            'margem_com_rebate': margem_preco_direto,
            'margem_sem_rebate': margem_preco_direto,
            'margem_real': margem_preco_direto,
            'diferenca': (margem_preco_direto['margem_percentual'] - margem_atual['margem_percentual']) if margem_preco_direto and margem_atual else None,
            'ganha_catalogo': True,
        })

    resultado_promocoes = buscar_promocoes_do_mlb(mlb)
    contexto['erro_promocoes'] = resultado_promocoes.get('erro')

    promocoes_ativas = [p for p in resultado_promocoes.get('promocoes', []) if p.get('status') == 'started']
    contexto['promocao_ativa'] = promocoes_ativas[0] if promocoes_ativas else None
    contexto['preco_base'] = variacao.preco_original or variacao.preco_atual

    if not eh_catalogo and margem_atual:
        linhas.append({
            'nome': 'Preço atual (sem promoção)',
            'tipo': 'PRECO_ATUAL',
            'status': None,
            'vigencia': None,
            'preco_original': variacao.preco_atual,
            'preco_promocional': variacao.preco_atual,
            'tem_rebate': False,
            'meli_percentage': None,
            'seller_percentage': None,
            'rebate_valor_reais': Decimal('0'),
            'margem_com_rebate': margem_atual,
            'margem_sem_rebate': margem_atual,
            'margem_real': margem_atual,
            'diferenca': Decimal('0'),
            'ganha_catalogo': None,
        })

    for promo in resultado_promocoes.get('promocoes', []):
        meli_percentage = promo.get('meli_percentage')
        seller_percentage = promo.get('seller_percentage')
        original_price = promo.get('original_price')
        tem_rebate = meli_percentage is not None

        preco_avaliado = promo.get('price') or promo.get('suggested_discounted_price')
        if not preco_avaliado:
            continue

        margem_com_rebate = calcular_margem(
            produto, preco_avaliado, tipo_anuncio_obj,
            rebate_percentual=meli_percentage if tem_rebate else None,
            preco_original=original_price if tem_rebate else None,
        )
        margem_sem_rebate = calcular_margem(produto, preco_avaliado, tipo_anuncio_obj)

        if not margem_com_rebate:
            continue

        diferenca = (margem_com_rebate['margem_percentual'] - margem_atual['margem_percentual']) if margem_atual else None

        ganha_catalogo = None
        if eh_catalogo and price_to_win:
            ganha_catalogo = Decimal(str(preco_avaliado)) <= price_to_win

        vigencia = None
        if promo.get('start_date'):
            vigencia = {'inicio': promo['start_date'][:10], 'fim': (promo.get('finish_date') or '?')[:10]}

        linhas.append({
            'nome': promo.get('name') or '—',
            'tipo': promo.get('type'),
            'status': promo.get('status'),
            'vigencia': vigencia,
            'preco_original': original_price,
            'preco_promocional': preco_avaliado,
            'tem_rebate': tem_rebate,
            'meli_percentage': meli_percentage,
            'seller_percentage': seller_percentage,
            'rebate_valor_reais': margem_com_rebate['rebate_valor'],
            'margem_com_rebate': margem_com_rebate,
            'margem_sem_rebate': margem_sem_rebate,
            'margem_real': margem_com_rebate,
            'diferenca': diferenca,
            'ganha_catalogo': ganha_catalogo,
        })

    contexto['linhas'] = linhas

    contexto['recomendacao'] = recomendar_precificacao(
        linhas, margem_minima, comportamento=comportamento, exigir_ganha_catalogo=eh_catalogo,
    )

    if eh_catalogo:
        contexto['categoria_1'] = [l for l in linhas if l['ganha_catalogo'] and l['margem_real']['margem_percentual'] >= margem_minima]
        contexto['categoria_2'] = [l for l in linhas if not l['ganha_catalogo'] and l['margem_real']['margem_percentual'] >= margem_minima]
        contexto['categoria_3'] = [l for l in linhas if l['ganha_catalogo'] and l['margem_real']['margem_percentual'] < margem_minima]
        contexto['categoria_4'] = [l for l in linhas if not l['ganha_catalogo'] and l['margem_real']['margem_percentual'] < margem_minima]
    else:
        contexto['dentro_margem'] = [l for l in linhas if l['margem_real']['margem_percentual'] >= margem_minima]
        contexto['abaixo_margem'] = [l for l in linhas if l['margem_real']['margem_percentual'] < margem_minima]

    return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

def view_configuracoes_mercado_livre(request):
    from mercado_livre.models import (
        ConfiguracaoMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre, FaixaArmazenagemMercadoLivre,
    )
    from mercado_livre.funcoes_auxiliares.badges import BADGES_TIPO_ANUNCIO, BADGES_LOGISTICA, badge_de

    config_geral = ConfiguracaoMercadoLivre.obter()
    faixas = FaixaArmazenagemMercadoLivre.objects.filter(ativo=True).order_by('ordem')

    tipos = []
    for tipo in ConfiguracaoTipoAnuncioMercadoLivre.objects.all():
        tipos.append({
            'badge_tipo_anuncio': badge_de(BADGES_TIPO_ANUNCIO, tipo.tipo_anuncio),
            'badge_logistica': badge_de(BADGES_LOGISTICA, tipo.tipo_logistico),
            'catalogo': tipo.catalogo,
            'comissao': tipo.comissao,
            'acrescimo_preco': tipo.acrescimo_preco,
            'margem_minima': tipo.margem_minima,
            'margem_padrao': tipo.margem_padrao,
            'margem_maxima': tipo.margem_maxima,
            'margem_competicao': tipo.margem_competicao,
        })

    return render(request, 'mercado_livre/estrutura_configuracoes_mercado_livre.html', {
        'config_geral': config_geral,
        'faixas': faixas,
        'tipos': tipos,
    })