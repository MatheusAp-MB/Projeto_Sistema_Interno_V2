# * [RESUMO] → Registro único de badges de apresentação (label + classe
#              CSS + ícone) por categoria de atributo do anúncio. Usado
#              por qualquer tela que precise mostrar Status, Tipo de
#              Anúncio, Logística, Flex ou Situação do Catálogo com o
#              mesmo visual (Resumo de Critérios, e futuramente o Hub).
#              Nunca duplicar essas definições em outro lugar — se uma
#              cor mudar, muda aqui, e toda tela reflete igual.

BADGES_STATUS = {
    'active':           {'label': 'Ativo',              'classe': 'status-ativo',               'icone': 'fa-circle-check'},
    'paused':           {'label': 'Pausado',             'classe': 'status-pausado',             'icone': 'fa-pause'},
    'closed':           {'label': 'Encerrado',           'classe': 'status-encerrado',           'icone': 'fa-circle-xmark'},
    'under_review':     {'label': 'Em revisão',          'classe': 'status-em-revisao',          'icone': 'fa-magnifying-glass'},
    'payment_required': {'label': 'Débito pendente',     'classe': 'status-debito-pendente',     'icone': 'fa-triangle-exclamation'},
    'not_yet_active':   {'label': 'Aguardando ativação', 'classe': 'status-aguardando-ativacao', 'icone': 'fa-hourglass-half'},
}

BADGES_TIPO_ANUNCIO = {
    'gold_special': {'label': 'Clássico', 'classe': 'badge-classico', 'icone': None},
    'gold_pro':     {'label': 'Premium',  'classe': 'badge-premium',  'icone': 'fa-coins'},
}

BADGES_LOGISTICA = {
    'fulfillment':   {'label': 'FULL',            'classe': 'badge-full',          'icone': 'fa-bolt'},
    'cross_docking': {'label': 'Coleta',          'classe': 'badge-coleta',        'icone': 'fa-truck'},
    'xd_drop_off':   {'label': 'Agência',         'classe': 'badge-agencia',       'icone': 'fa-building'},
    'self_service':  {'label': 'Flex Puro',       'classe': 'badge-flex-puro',     'icone': 'fa-motorcycle'},
    'not_specified': {'label': 'Legado',          'classe': 'badge-legado',        'icone': 'fa-clock-rotate-left'},
    'drop_off':      {'label': 'Correios',        'classe': 'badge-correios',      'icone': 'fa-envelope'},
    'custom':        {'label': 'Por nossa conta', 'classe': 'badge-conta-propria', 'icone': 'fa-hand-holding-dollar'},
}

BADGES_CATALOGO = {
    'simples':  {'label': 'Simples',             'classe': 'badge-papel', 'icone': None},
    'base':     {'label': 'Base de Catálogo',    'classe': 'badge-papel', 'icone': None},
    'catalogo': {'label': 'Anúncio de Catálogo', 'classe': 'badge-papel', 'icone': 'fa-book-open'},
}

BADGE_FLEX_ATIVO   = {'label': 'Com Flex', 'classe': 'badge-flex-ativo',   'icone': 'fa-bolt'}
BADGE_FLEX_INATIVO = {'label': 'Sem Flex', 'classe': 'badge-flex-inativo', 'icone': None}

BADGE_PADRAO = {'label': '—', 'classe': 'badge-papel', 'icone': None}


def badge_de(mapa, valor_bruto):
    """Busca o badge (label+classe+ícone) a partir do valor bruto vindo
    da API/banco. Se o valor não for reconhecido, cai no badge neutro
    padrão em vez de quebrar."""
    return mapa.get(valor_bruto, BADGE_PADRAO)


def badge_flex(ativo):
    return BADGE_FLEX_ATIVO if ativo else BADGE_FLEX_INATIVO


def opcoes_com_badge(mapa):
    """Monta a lista de opções pronta pra um painel de filtro (checkbox),
    na ordem em que o dict foi declarado."""
    return [
        {'valor': valor, **dados}
        for valor, dados in mapa.items()
    ]