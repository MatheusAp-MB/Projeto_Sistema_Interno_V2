# agenda_videos/funcoes_auxiliares/badges_agenda.py

# * [RESUMO] → Registro único de badges de apresentação (label + classe CSS + ícone) pra
#              telas da Agenda de Vídeos. Mesmo padrão de mercado_livre/badges.py — nunca
#              duplicar essas definições em outro lugar.
# Reestruturação completa (30/07) — BADGES_STATUS_VIDEO (Simples/Base) e os
# badges de "insuficiente" saem (conceitos retirados). BADGES_ETAPA é novo —
# cobre as 7 etapas que CicloVideo.etapa_atual() pode devolver.

from agenda_videos.models import StatusManualAgenda, StatusPostagem

BADGES_STATUS_MANUAL = {
    StatusManualAgenda.ATIVO:         {'label': 'Ativo',         'classe': 'status-ativo',         'icone': 'fa-circle-check'},
    StatusManualAgenda.PAUSADO:       {'label': 'Pausado',       'classe': 'status-pausado',       'icone': 'fa-pause'},
    StatusManualAgenda.DESCONTINUADO: {'label': 'Descontinuado', 'classe': 'status-descontinuado', 'icone': 'fa-circle-xmark'},
}

BADGES_STATUS_POSTAGEM = {
    StatusPostagem.AGUARDANDO_APROVACAO: {'label': 'Aguardando aprovação', 'classe': 'postagem-aguardando', 'icone': 'fa-hourglass-half'},
    StatusPostagem.APROVADO:             {'label': 'Aprovado',             'classe': 'postagem-aprovado',   'icone': 'fa-circle-check'},
    StatusPostagem.RECUSADO:             {'label': 'Recusado',             'classe': 'postagem-recusado',   'icone': 'fa-circle-xmark'},
    StatusPostagem.REPLICADO:            {'label': 'Replicado',            'classe': 'postagem-replicado',  'icone': 'fa-copy'},
}

# * [EXPLICAÇÃO] → Nova (30/07) — cobre CicloVideo.etapa_atual(). Classes CSS
#                  ainda não existem (Frente 4) — nomes já escolhidos aqui
#                  pra ficarem estáveis quando o CSS for escrito.
BADGES_ETAPA = {
    'base':                 {'label': 'Base',                          'classe': 'etapa-base',          'icone': 'fa-video'},
    'roteiro':               {'label': 'Roteiro',                       'classe': 'etapa-roteiro',       'icone': 'fa-pen'},
    'completo':              {'label': 'Completo',                      'classe': 'etapa-completo',      'icone': 'fa-film'},
    'postar':                {'label': 'Aguardando Postar',             'classe': 'etapa-postar',        'icone': 'fa-upload'},
    'aguardando_aprovacao':  {'label': 'Aguardando aprovação',          'classe': 'postagem-aguardando', 'icone': 'fa-hourglass-half'},
    'replicar':              {'label': 'Aprovado, aguardando replicar', 'classe': 'postagem-aprovado',   'icone': 'fa-copy'},
    'concluido':             {'label': 'Concluído',                     'classe': 'etapa-concluido',     'icone': 'fa-circle-check'},
}

BADGE_URGENTE_ATIVO = {'label': 'Urgente', 'classe': 'badge-conta-propria', 'icone': 'fa-triangle-exclamation'}

BADGE_PADRAO = {'label': '—', 'classe': 'badge-papel', 'icone': None}


def badge_de(mapa, valor_bruto):
    """Busca o badge (label+classe+ícone) a partir do valor bruto vindo
    do banco. Se o valor não for reconhecido, cai no badge neutro padrão."""
    return mapa.get(valor_bruto, BADGE_PADRAO)


def opcoes_com_badge(mapa):
    """Monta a lista de opções pronta pra um painel de filtro (checkbox),
    na ordem em que o dict foi declarado."""
    return [{'valor': valor, **dados} for valor, dados in mapa.items()]