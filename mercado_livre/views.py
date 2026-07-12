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
    from django.shortcuts import redirect

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


def view_recomendacao_precificacao(request):
    from django.urls import reverse
    from django.shortcuts import redirect
    from urllib.parse import quote
    from mercado_livre.models import AnuncioMercadoLivre, RecomendacaoPrecificacao
    from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import COMPORTAMENTOS
    from mercado_livre.funcoes_auxiliares.montar_linhas_precificacao import montar_linhas_candidatas

    mlb = request.GET.get('mlb', '').strip().upper() or request.POST.get('mlb', '').strip().upper()

    # * [EXPLICAÇÃO] → None (não 'padrao') quando a URL não especifica
    #                  nada — assim dá pra diferenciar "usuário não
    #                  escolheu" de "usuário escolheu padrao explicitamente".
    #                  O valor real só é decidido mais abaixo, depois de
    #                  saber qual é o comportamento_ativo dessa variação.
    comportamento_do_request = request.GET.get('comportamento') or request.POST.get('comportamento')
    if comportamento_do_request not in COMPORTAMENTOS:
        comportamento_do_request = None

    voltar = request.GET.get('voltar', '')
    voltar_url = f"{reverse('mercado_livre_anuncios')}?{voltar}" if voltar else reverse('mercado_livre_anuncios')

    contexto = {
        'busca': mlb,
        'opcoes_comportamento': COMPORTAMENTOS,
        'voltar_url': voltar_url,
    }

    if not mlb:
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    anuncio = AnuncioMercadoLivre.objects.select_related('tipo_de_anuncio', 'competicao').filter(mlb=mlb).first()
    if not anuncio:
        contexto['erro'] = f'MLB {mlb} não encontrado no banco Django.'
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    variacao = anuncio.variacoes.select_related('produto').prefetch_related('promocoes', 'recomendacoes').first()
    if not variacao or not variacao.produto:
        contexto['erro'] = f'MLB {mlb} não tem Produto vinculado — sem custo/dimensões, não dá pra calcular margem.'
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    produto = variacao.produto
    tipo_anuncio_obj = anuncio.tipo_de_anuncio
    if not tipo_anuncio_obj:
        contexto['erro'] = f'MLB {mlb} não tem Tipo de Anúncio vinculado — não dá pra saber comissão/margem.'
        return render(request, 'mercado_livre/estrutura_recomendacao_precificacao.html', contexto)

    # * [EXPLICAÇÃO] → Sem escolha explícita na URL, mostra o que já
    #                  está salvo como ativo pra ESSA variação — não
    #                  mais um "padrao" genérico ignorando o que o
    #                  usuário já decidiu antes.
    comportamento = comportamento_do_request or variacao.comportamento_ativo
    contexto['comportamento_atual'] = comportamento

    # * [EXPLICAÇÃO] → "Salvar decisão" é uma ação separada de
    #                  "visualizar" — só grava comportamento_ativo
    #                  quando o botão é de fato clicado (POST). Depois
    #                  de salvar, REDIRECIONA (Post-Redirect-Get) em vez
    #                  de renderizar direto — evita o aviso do navegador
    #                  de "reenviar formulário" ao recarregar a página.
    if request.method == 'POST' and request.POST.get('acao') == 'salvar_decisao':
        variacao.comportamento_ativo = comportamento
        variacao.save(update_fields=['comportamento_ativo'])

        url_volta = f"{reverse('mercado_livre_recomendacao_precificacao')}?mlb={mlb}&comportamento={comportamento}&decisao_salva=1"
        if voltar:
            url_volta += f"&voltar={quote(voltar)}"
        return redirect(url_volta)

    contexto['comportamento_ativo_hoje'] = variacao.comportamento_ativo
    contexto['decisao_salva'] = request.GET.get('decisao_salva') == '1'

    linhas, eh_catalogo, margem_minima, margem_atual, config_tipo = montar_linhas_candidatas(variacao)

    contexto['margem_minima'] = margem_minima
    contexto['margem_atual'] = margem_atual
    contexto['eh_catalogo'] = eh_catalogo
    contexto['preco_atual'] = variacao.preco_atual
    contexto['preco_base'] = variacao.preco_original or variacao.preco_atual
    contexto['linhas'] = linhas

    if eh_catalogo:
        competicao = anuncio.competicao
        contexto['competicao_status'] = competicao.get_status_display() if competicao.status else None
        contexto['competicao_price_to_win'] = competicao.price_to_win
        contexto['competicao_current_price'] = competicao.current_price

    promocao_ativa_obj = variacao.promocoes.filter(status='started').first()
    contexto['promocao_ativa'] = {
        'name': promocao_ativa_obj.nome, 'type': promocao_ativa_obj.tipo,
    } if promocao_ativa_obj else None

    from mercado_livre.funcoes_auxiliares.classificacao_catalogo import info_variacao
    from mercado_livre.funcoes_auxiliares.badges import BADGES_CATALOGO, badge_de

    info = info_variacao(variacao, imagem_url=produto.imagem_url, titulo_produto=produto.titulo)
    contexto['info'] = info
    contexto['marca'] = produto.marca
    contexto['badge_catalogo'] = badge_de(BADGES_CATALOGO, tipo_anuncio_obj.classificacao_catalogo)
    contexto['titulo'] = anuncio.titulo_anuncio
    contexto['sku'] = produto.sku
    contexto['tipo_anuncio_label'] = tipo_anuncio_obj.get_tipo_anuncio_display()

    # * [EXPLICAÇÃO] → O "veredito" agora é LIDO do banco (calculado em
    #                  lote por calcular_recomendacoes_precificacao.py),
    #                  nunca mais recalculado ao vivo nessa tela.
    recomendacao_salva = RecomendacaoPrecificacao.objects.filter(
        variacao=variacao, comportamento=comportamento
    ).first()

    if recomendacao_salva:
        contexto['recomendacao'] = {
            'escolhida': {
                'nome': recomendacao_salva.cenario_nome,
                'preco_promocional': recomendacao_salva.preco_recomendado,
                'margem_real': {'margem_percentual': recomendacao_salva.margem_recomendada},
            } if recomendacao_salva.tem_escolha else None,
            'bucket_nome': recomendacao_salva.bucket_nome,
            'exige_aprovacao': recomendacao_salva.exige_aprovacao,
        }
    else:
        contexto['recomendacao'] = {'escolhida': None, 'bucket_nome': None, 'exige_aprovacao': False}

    # * [EXPLICAÇÃO] → Quanto a margem muda se a recomendação for
    #                  aceita, comparado com a margem de hoje —
    #                  arredondado ANTES de comparar (mesmo motivo já
    #                  corrigido na tabela: evita "diferença zero"
    #                  aparente por causa de casa decimal escondida).
    contexto['diferenca_recomendacao'] = None
    if margem_atual and contexto['recomendacao']['escolhida']:
        contexto['diferenca_recomendacao'] = round(
            contexto['recomendacao']['escolhida']['margem_real']['margem_percentual'] - margem_atual['margem_percentual'], 2
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

def view_hub_promocoes(request):
    from produtos.models import Produto
    from mercado_livre.models import TipoDeAnuncioMercadoLivre, CompeticaoCatalogo
    from mercado_livre.funcoes_auxiliares.classificacao_catalogo import (
        listar_skus_filtrados, classificar_lote_de_skus,
    )
    from mercado_livre.funcoes_auxiliares.hub_promocoes import (
        enriquecer_arvores_com_veredito, calcular_contadores_promocao,
    )
    from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import COMPORTAMENTOS
    from mercado_livre.models import RecomendacaoPrecificacao
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
        'categorias_estado': request.GET.getlist('categoria_estado'),
        'comportamentos': request.GET.getlist('comportamento'),
    }

    skus, total_anuncios_filtrados = listar_skus_filtrados(busca=busca or None, filtros=filtros)

    paginator = Paginator(skus, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    arvores = classificar_lote_de_skus(list(pagina.object_list), filtros=filtros)
    enriquecer_arvores_com_veredito(arvores)

    querystring_atual = request.GET.urlencode()

    contadores = calcular_contadores_promocao(skus)

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    mapa_competicao = dict(CompeticaoCatalogo.StatusCompeticao.choices)
    mapa_estoque = {'com': 'Com estoque', 'sem': 'Sem estoque'}
    mapa_desconto = {'com': 'Com desconto', 'sem': 'Sem desconto'}
    mapa_conexao_erp = {'com': 'Com conexão ERP', 'sem': 'Sem conexão ERP'}
    mapa_score = {'ruim': 'Ruim', 'medio': 'Médio', 'bom': 'Bom', 'sem_dados': 'Sem dados'}
    mapa_categoria_estado = dict(RecomendacaoPrecificacao.CategoriaEstado.choices)  

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
        [{'label': mapa_competicao.get(v, v), 'classe': None, 'icone': None} for v in filtros['situacoes_competicao']] +
        [{'label': mapa_categoria_estado.get(v, v), 'classe': None, 'icone': None} for v in filtros['categorias_estado']] +
        [{'label': COMPORTAMENTOS.get(v, v), 'classe': None, 'icone': None} for v in filtros['comportamentos']]
    )

    return render(request, 'mercado_livre/estrutura_hub_promocoes.html', {
        'pagina': pagina,
        'arvores': arvores,
        'busca': busca,
        'por_pagina': por_pagina,
        'filtros': filtros,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'total_anuncios_filtrados': total_anuncios_filtrados,
        'contadores': contadores,

        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True)
            .exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'opcoes_status': opcoes_com_badge(BADGES_STATUS),
        'opcoes_tipo_anuncio': opcoes_com_badge(BADGES_TIPO_ANUNCIO),
        'opcoes_logistica': opcoes_com_badge(BADGES_LOGISTICA),
        'opcoes_catalogo': opcoes_com_badge(BADGES_CATALOGO),
        'opcoes_situacao_competicao': CompeticaoCatalogo.StatusCompeticao.choices,
        'opcoes_comportamento': COMPORTAMENTOS,
        'opcoes_categoria_estado': RecomendacaoPrecificacao.CategoriaEstado.choices,
        'badge_flex_ativo': BADGE_FLEX_ATIVO,
        'badge_flex_inativo': BADGE_FLEX_INATIVO,

        'chips_ativos': chips_ativos,
        'querystring_atual': querystring_atual,
    })