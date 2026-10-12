# gestao_ruptura/funcoes_auxiliares/ruptura_texto.py
#
# Função Objetivo: Os pequenos formatadores de número, data e plural que a lista (ruptura_lista.py) e o detalhe (ruptura_pagina.py) da tela "Ruptura de estoque" usam do mesmo jeito.
# Só texto: aqui NÃO há banco, API nem regra de negócio (as contas estão em ruptura_calculo.py).

# Função Objetivo: O número inteiro digitado (aceita "1.200"), preso entre o mínimo e o máximo. None se vazio ou inválido.
def inteiro(valor, minimo, maximo):
    texto = str(valor if valor is not None else '').strip().replace('.', '').replace(' ', '')
    if not texto:
        return None
    try:
        numero_digitado = int(texto)
    except ValueError:
        return None
    return max(minimo, min(maximo, numero_digitado))


# Função Objetivo: O ritmo em "un/dia" com vírgula (duas casas abaixo de 1, uma casa de 1 em diante): 0,35 · 4,0 · 12,5.
def un_dia(media):
    return f'{media:.{2 if media < 1 else 1}f}'.replace('.', ',')


def data(dia):
    return f'{dia:%d/%m/%Y}'


# Função Objetivo: A data curta da lista (dd/mm; com o ano de 2 dígitos só quando não é o ano de hoje).
def data_curta(dia, hoje):
    return f'{dia:%d/%m}' if dia.year == hoje.year else f'{dia:%d/%m/%y}'


def plural(n, singular, plural_):
    return f'{n} {singular if n == 1 else plural_}'


def em_dias(n):
    return 'hoje' if n == 0 else f'em {plural(n, "dia", "dias")}'


def pct(valor):
    return f'{valor:+.0f}%'.replace('-', '−')


# Função Objetivo: O valor em reais sem centavos, com ponto de milhar: R$ 1.234.
def reais(valor):
    return 'R$ ' + f'{valor:,.0f}'.replace(',', '.')
