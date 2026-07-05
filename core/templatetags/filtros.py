# * [RESUMO] → Template tags customizadas, compartilhadas por todo o sistema.
#              get_item resolve o problema de acessar um dicionário com
#              chave dinâmica dentro de um template — o Django só suporta
#              chave fixa nativamente (dicionario.chave_literal).

from django import template

register = template.Library()


@register.filter
def get_item(dicionario, chave):
    # * [EXPLICAÇÃO] → Usa .get() em vez de dicionario[chave] para não
    #                  quebrar quando a chave não existir — retorna None,
    #                  que o template trata como "falso" no {% if %}.
    if not dicionario:
        return None
    return dicionario.get(chave)