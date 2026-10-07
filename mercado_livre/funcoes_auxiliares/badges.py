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


# * [EXPLICAÇÃO] → Tela "Full — Planejamento de envios" (06/10/2026). Os selos abaixo vivem aqui, e as cores em
#                  layout_badges.css, pelo mesmo motivo de todos os outros: uma cor muda num lugar só.
# Situação de conferência de um dado do Full — o registro que a equipe preenche na ficha de debug
# (CampoFullMercadoLivre.Situacao). As chaves são as MESMAS do model; só o texto muda: na tela final
# "A validar" aparece como "Não conferido", que é como o chefe lê.
BADGES_CONFERENCIA_FULL = {
    'valido':    {'label': 'Conferido',     'classe': 'badge-conferencia-valido',    'icone': 'fa-circle-check'},
    'hipotese':  {'label': 'Hipótese',      'classe': 'badge-conferencia-hipotese',  'icone': 'fa-lightbulb'},
    'a_validar': {'label': 'Não conferido', 'classe': 'badge-conferencia-a-validar', 'icone': 'fa-circle-question'},
    'invalido':  {'label': 'Inválido',      'classe': 'badge-conferencia-invalido',  'icone': 'fa-circle-xmark'},
}

# Urgência de envio (REPOS stock.shipping_urgency). As chaves são os valores exatos que a API manda.
BADGES_URGENCIA_FULL = {
    'URGENT':       {'label': 'Urgente',        'classe': 'badge-envio-urgente',        'icone': 'fa-fire'},
    'THIS_WEEK':    {'label': 'Esta semana',    'classe': 'badge-envio-esta-semana',    'icone': 'fa-calendar-day'},
    'NEXT_WEEK':    {'label': 'Próxima semana', 'classe': 'badge-envio-proxima-semana', 'icone': 'fa-calendar-week'},
    'IN_TWO_WEEKS': {'label': 'Em 2 semanas',   'classe': 'badge-envio-em-2-semanas',   'icone': 'fa-calendar'},
    'NO_URGENCY':   {'label': 'Sem urgência',   'classe': 'badge-envio-sem-urgencia',   'icone': 'fa-circle-check'},
    'EXCEDENT':     {'label': 'Excedente',      'classe': 'badge-envio-excedente',      'icone': 'fa-boxes-stacked'},
}

BADGE_ESTRELA_FULL = {'label': 'Estrela', 'classe': 'badge-estrela', 'icone': 'fa-star'}

# * [EXPLICAÇÃO] → Tela "Full — Estoque no Full" (07/10/2026). Situação da CONSULTA de um produto (ou de um Código ML):
#                  não é "o estoque está bom/ruim", é "o número que você está vendo é confiável hoje?". As chaves são as
#                  mesmas que gestao_full/funcoes_auxiliares/full_estoque_ml.py devolve em produto['status'].
BADGES_ESTOQUE_FULL = {
    'atualizado':   {'label': 'Atualizado',       'classe': 'badge-estoque-atualizado',   'icone': 'fa-circle-check'},
    'desatualizado': {'label': 'Desatualizado',   'classe': 'badge-estoque-desatualizado', 'icone': 'fa-clock'},
    'parcial':      {'label': 'Parcial',          'classe': 'badge-estoque-parcial',      'icone': 'fa-circle-half-stroke'},
    'sem_consulta': {'label': 'Sem consulta',     'classe': 'badge-estoque-sem-consulta', 'icone': 'fa-hourglass-empty'},
    'erro':         {'label': 'Erro na consulta', 'classe': 'badge-estoque-erro',         'icone': 'fa-triangle-exclamation'},
}
