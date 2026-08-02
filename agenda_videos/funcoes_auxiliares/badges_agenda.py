# agenda_videos/funcoes_auxiliares/badges_agenda.py

# Função Objetivo: Registro único de badges de apresentação (label + classe
# CSS + ícone) pras telas da Agenda de Vídeos. Mesmo padrão de
# mercado_livre/badges.py (não compartilhado — cada app tem seu próprio
# registro, nunca duplicar as definições dentro deste app).
# Reestruturação completa (30/07) — BADGES_STATUS_VIDEO (Simples/Base) e os
# badges de "insuficiente" saem (conceitos retirados). BADGES_ETAPA é novo —
# cobre as 7 etapas que CicloVideo.etapa_atual() pode devolver.

from dataclasses import asdict, dataclass

from agenda_videos.models import StatusManualAgenda, StatusPostagem


@dataclass(frozen=True)
class Badge:
    label: str
    classe: str | None = None
    icone: str | None = None


@dataclass(frozen=True)
class OpcaoComBadge:
    valor: str
    label: str
    classe: str | None = None
    icone: str | None = None


BADGES_STATUS_MANUAL = {
    StatusManualAgenda.ATIVO:         Badge(label='Ativo',         classe='status-ativo',         icone='fa-circle-check'),
    StatusManualAgenda.PAUSADO:       Badge(label='Pausado',       classe='status-pausado',        icone='fa-pause'),
    StatusManualAgenda.DESCONTINUADO: Badge(label='Descontinuado', classe='status-descontinuado',  icone='fa-circle-xmark'),
}

BADGES_STATUS_POSTAGEM = {
    StatusPostagem.AGUARDANDO_APROVACAO: Badge(label='Aguardando aprovação', classe='postagem-aguardando', icone='fa-hourglass-half'),
    StatusPostagem.APROVADO:             Badge(label='Aprovado',             classe='postagem-aprovado',   icone='fa-circle-check'),
    StatusPostagem.RECUSADO:             Badge(label='Recusado',             classe='postagem-recusado',   icone='fa-circle-xmark'),
    StatusPostagem.REPLICADO:            Badge(label='Replicado',            classe='postagem-replicado',  icone='fa-copy'),
}

# * [EXPLICAÇÃO] → Cobre CicloVideo.etapa_atual(). Classes CSS ainda não
#                  existem (Frente 4) — nomes já escolhidos aqui pra ficarem
#                  estáveis quando o CSS for escrito.
BADGES_ETAPA = {
    'base':                 Badge(label='Base',                          classe='etapa-base',          icone='fa-video'),
    'roteiro':              Badge(label='Roteiro',                       classe='etapa-roteiro',       icone='fa-pen'),
    'completo':             Badge(label='Completo',                      classe='etapa-completo',      icone='fa-film'),
    'postar':               Badge(label='Aguardando Postar',             classe='etapa-postar',        icone='fa-upload'),
    'aguardando_aprovacao': Badge(label='Aguardando aprovação',          classe='postagem-aguardando', icone='fa-hourglass-half'),
    'replicar':             Badge(label='Aprovado, aguardando replicar', classe='postagem-aprovado',   icone='fa-copy'),
    'concluido':            Badge(label='Concluído',                     classe='etapa-concluido',     icone='fa-circle-check'),
}

BADGE_URGENTE_ATIVO = Badge(label='Urgente', classe='badge-conta-propria', icone='fa-triangle-exclamation')

BADGE_PADRAO = Badge(label='—', classe='badge-papel', icone=None)


# Função Objetivo: Busca o badge a partir do valor bruto vindo do banco. Se
# não for reconhecido, cai no badge neutro padrão.
def buscar_badge_de(mapa: dict, valor_bruto: str) -> Badge:
    return mapa.get(valor_bruto, BADGE_PADRAO)


# Função Objetivo: Monta a lista de opções pronta pra um painel de filtro
# (checkbox), na ordem em que o dict foi declarado.
def montar_opcoes_com_badge(mapa: dict) -> list[OpcaoComBadge]:
    return [OpcaoComBadge(valor=valor, **asdict(badge)) for valor, badge in mapa.items()]