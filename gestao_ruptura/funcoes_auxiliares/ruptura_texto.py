# gestao_ruptura/funcoes_auxiliares/ruptura_texto.py
#
# Função Objetivo: Os pequenos formatadores de número, data e plural que a lista (ruptura_lista.py) e o detalhe (ruptura_pagina.py) da tela "Previsão de Ruptura de estoque" usam do mesmo jeito.
# Só texto: aqui NÃO há banco, API nem regra de negócio (as contas estão em ruptura_calculo.py). Também mora aqui o texto do que o Mercado Livre recomenda e o do porquê da urgência do Sistema,
# que a lista e o detalhe escrevem do mesmo jeito.

from gestao_vendas.funcoes_auxiliares.vendas_ml import numero

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


# Função Objetivo: A data "AAAA-MM-DD" que o Mercado Livre manda (prazo para repor) como "dd/mm/aaaa"; o que não tiver esse formato volta como veio.
def data_do_ml(texto):
    partes = str(texto)[:10].split('-')
    return f'{partes[2]}/{partes[1]}/{partes[0]}' if len(partes) == 3 and all(p.isdigit() for p in partes) else str(texto)


# Função Objetivo: Por que o SISTEMA deu a urgência que deu, em uma frase (balão da célula "Urgência" da lista e texto do cartão do detalhe). `cat` é 'sem_estoque' | 'ruptura' | qualquer outra (há projeção)
# e `envio` o resultado de ruptura_calculo.envio (None se não há data de enviar até).
def porque_da_urgencia_do_sistema(cat, envio):
    if cat == 'sem_estoque':
        return 'sem estoque lido (não dá para calcular)'
    if cat == 'ruptura':
        return 'o estoque está zerado'
    if envio is None:
        return 'não há ruptura prevista neste ritmo'
    if envio['estado'] == 'vencido':
        return f'o prazo de envio acabou em {data(envio["ultimo_dia"])}'
    if envio['estado'] != 'ok':
        return f'a data recomendada para enviar ({data(envio["enviar_ate"])}) {"é hoje" if envio["estado"] == "hoje" else "já passou"}'
    return f'enviar até {data(envio["enviar_ate"])}, daqui a {plural(envio["em_dias"], "dia", "dias")} (faixas: até 7 dias = esta semana, até 14 = próxima semana, até 21 = em 2 semanas)'


# Função Objetivo: A sugestão do MERCADO LIVRE como texto: (texto, dica). `ml` é o resultado de ruptura_estoque.resumir_ml. O texto é o número ("120") ou a faixa ("100–150"); None quando o ML não tem número
# (nunca vira zero). "Não repor" do ML vira "0" (o ML disse que não é para enviar). A dica explica de onde vem o número (e que o gráfico e a comparação usam o começo da faixa).
def quantidade_do_ml(ml):
    if ml['sugestao_min'] is None:
        if ml['estado'] == 'sem_dados':
            return None, f'Sem número do Mercado Livre: {ml["motivo"]}. Abra o item e clique em "Consultar no Mercado Livre" (sem número não é zero).'
        return None, 'O Mercado Livre não mandou uma quantidade sugerida para este item (sem número não é zero).'
    parcial = f' Só {ml["n_com_dados"]} de {ml["n_codigos"]} Códigos ML têm a recomendação do ML: a soma é parcial.' if ml['estado'] == 'parcial' else ''
    if ml['nao_repor']:
        return '0', f'O Mercado Livre recomenda NÃO repor este item (nada a enviar).{parcial}'
    if ml['sugestao_min'] == ml['sugestao_max']:
        return numero(ml['sugestao_min']), f'Sugestão do Mercado Livre: {numero(ml["sugestao_min"])} un (exata).{parcial}'
    return (f'{numero(ml["sugestao_min"])}–{numero(ml["sugestao_max"])}',
            f'Sugestão do Mercado Livre: de {numero(ml["sugestao_min"])} a {numero(ml["sugestao_max"])} un (faixa). O gráfico e a comparação usam o começo da faixa ({numero(ml["sugestao_min"])} un).{parcial}')


# Função Objetivo: O aviso de depósito: quando a quantidade a enviar passa do estoque do ERP (o que há no depósito), devolve (curto, longo): o curto vai no cartão ("só há 80 un no depósito") e o longo na dica.
# Sem quantidade, sem número do ERP ou com depósito suficiente: ('', ''). A tela SEMPRE mostra a quantidade inteira da sugestão; o aviso só diz que não dá para enviar tudo (decisão do Matheus).
def aviso_do_deposito(qtd, deposito):
    if qtd is None or deposito is None or qtd <= deposito:
        return '', ''
    return (f'só há {numero(deposito)} un no depósito',
            f'Atenção: a quantidade a enviar ({numero(qtd)} un) é maior que o estoque do depósito ({numero(deposito)} un, o Estoque do cadastro do Produto no ERP): faltam {numero(qtd - deposito)} un para enviar tudo. '
            f'A tela mostra a quantidade inteira mesmo assim.')
