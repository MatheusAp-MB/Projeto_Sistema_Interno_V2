# agenda_videos/templatetags/andamento_tags.py

# Função Objetivo: Calcula a janela (início/fim) da OCORRÊNCIA ATUAL — não da fase
# inteira. Vira template tag (25/07) pelo mesmo motivo do roadmap: precisa funcionar
# sempre, em qualquer view que renderize o card, sem depender de alguém lembrar de
# calcular isso manualmente antes (já esquecemos 2x nesta sessão com outros campos
# parecidos — aqui, virando tag, não tem como esquecer).

from django import template
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia

register = template.Library()


@register.simple_tag
def janela_ocorrencia_atual(produto):
    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento is None:
        return None
    return calcular_janela_ocorrencia(
        andamento.fase_atual.fase, andamento.inicio_fase, andamento.ocorrencia_atual,
    )