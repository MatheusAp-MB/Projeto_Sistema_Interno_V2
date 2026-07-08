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
        'faixas_score': request.GET.getlist('score'),
        'situacoes_competicao': request.GET.getlist('competicao'),
    }

    skus = listar_skus_filtrados(busca=busca or None, filtros=filtros)

    paginator = Paginator(skus, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    arvores = classificar_lote_de_skus(list(pagina.object_list), filtros=filtros)

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    mapa_competicao = dict(CompeticaoCatalogo.StatusCompeticao.choices)
    mapa_estoque = {'com': 'Com estoque', 'sem': 'Sem estoque'}
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