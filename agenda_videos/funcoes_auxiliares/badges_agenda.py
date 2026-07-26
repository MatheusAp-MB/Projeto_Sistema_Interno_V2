# agenda_videos/funcoes_auxiliares/badges_agenda.py

# * [RESUMO] → Registro único de badges de apresentação (label + classe CSS + ícone) pra
#              telas da Agenda de Vídeos. Mesmo padrão de mercado_livre/badges.py — nunca
#              duplicar essas definições em outro lugar.

from agenda_videos.models import StatusManualAgenda, StatusPostagem, StatusVideo

# * [EXPLICAÇÃO] → Classes reaproveitadas de core/static/base_compartilhada/css/
#                  layout_badges.css (regra do projeto: cor vive só nesse arquivo).
#                  status-ativo/status-pausado/badge-papel/badge-conta-propria/
#                  badge-listed já existiam (usados pelo Hub de Anúncios) e batem
#                  semanticamente — reaproveitados em vez de duplicados. Só as
#                  genuinamente novas (status-descontinuado, postagem-*, video-*)
#                  foram adicionadas ao arquivo compartilhado.
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

BADGES_STATUS_VIDEO = {
    StatusVideo.NAO_GERADO: {'label': 'Não gerado', 'classe': 'video-nao-gerado', 'icone': None},
    StatusVideo.GERADO:     {'label': 'Gerado',      'classe': 'video-gerado',     'icone': 'fa-circle-check'},
}

BADGE_URGENTE_ATIVO          = {'label': 'Urgente',                       'classe': 'badge-conta-propria',     'icone': 'fa-triangle-exclamation'}
# * [EXPLICAÇÃO] → Corrigido (26/07) — usava badge-listed (âmbar), que já é a
#                  cor de "Risco de Atraso" no mesmo card; colidiria (prazo vs
#                  conteúdo são coisas diferentes). Agora usa badge-pool-
#                  insuficiente, cor nova, sem overlap com nada existente.
BADGE_ROTEIROS_INSUFICIENTES  = {'label': 'Roteiros insuficientes',         'classe': 'badge-pool-insuficiente', 'icone': 'fa-triangle-exclamation'}
BADGE_COMPLETOS_INSUFICIENTES = {'label': 'Vídeos completos insuficientes', 'classe': 'badge-pool-insuficiente', 'icone': 'fa-triangle-exclamation'}

BADGE_PADRAO = {'label': '—', 'classe': 'badge-papel', 'icone': None}


def badge_de(mapa, valor_bruto):
    """Busca o badge (label+classe+ícone) a partir do valor bruto vindo
    do banco. Se o valor não for reconhecido, cai no badge neutro padrão."""
    return mapa.get(valor_bruto, BADGE_PADRAO)


def opcoes_com_badge(mapa):
    """Monta a lista de opções pronta pra um painel de filtro (checkbox),
    na ordem em que o dict foi declarado."""
    return [{'valor': valor, **dados} for valor, dados in mapa.items()]