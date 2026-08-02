# agenda_videos/templatetags/roadmap_tags.py

# Função Objetivo: Template tag que renderiza o roadmap de 1 produto — reaproveitável
# em qualquer tela, sem a view precisar lembrar de calcular/passar isso no contexto.

from django import template
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_roadmap_produto

register = template.Library()


@register.inclusion_tag('agenda_videos/parciais/estrutura_parcial_roadmap_produto.html')
def roadmap_produto(produto):
    return {'roadmap': calcular_roadmap_produto(produto), 'produto': produto}