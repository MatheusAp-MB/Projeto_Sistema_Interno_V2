# agenda_videos/templatetags/agenda_videos_tags.py

# Função Objetivo: Filtros e tags de apresentação usados pelos templates da
# Agenda de Vídeos — cada um traduz 1 valor bruto do banco pra algo exibível,
# sempre reaproveitando a mesma fonte única já usada no resto do sistema
# (nunca reimplementa a tradução aqui).
# Substitui agenda_videos/templatetags/andamento_tags.py — que dependia do
# modelo antigo (AndamentoAgenda) e já está quebrado hoje (importa uma função
# que não existe mais em calculo_datas_fase.py). Ainda não deleto esse
# arquivo — estrutura_parcial_card_produto.html também carrega ele, e só
# reescrevo esse na próxima etapa.

from django import template
from agenda_videos.models import Fase
from agenda_videos.funcoes_auxiliares.badges_agenda import (
    BADGES_STATUS_MANUAL, BADGES_ETAPA, BADGES_STATUS_POSTAGEM, buscar_badge_de,
)

register = template.Library()


@register.filter
def rotulo_fase(valor_bruto):
    if not valor_bruto:
        return '—'
    return Fase(valor_bruto).label


@register.filter
def badge_status_manual(valor_bruto):
    return buscar_badge_de(BADGES_STATUS_MANUAL, valor_bruto)


@register.filter
def badge_etapa(valor_bruto):
    return buscar_badge_de(BADGES_ETAPA, valor_bruto)


@register.filter
def badge_status_postagem(valor_bruto):
    return buscar_badge_de(BADGES_STATUS_POSTAGEM, valor_bruto)


# Função Objetivo: Busca o CicloVideo mais recente de 1 produto — precisa
# funcionar sempre, em qualquer template que renderize o card/cabeçalho, sem
# depender de quem chama ter pré-calculado isso (mesmo motivo do roadmap_tags).
@register.simple_tag
def ciclo_atual_de(produto):
    return produto.ciclos_video.first()