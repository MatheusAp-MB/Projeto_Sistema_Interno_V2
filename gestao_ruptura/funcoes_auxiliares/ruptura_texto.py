# gestao_ruptura/funcoes_auxiliares/ruptura_texto.py
#
# Função Objetivo: Os pequenos formatadores de número, data e plural que a lista (ruptura_lista.py) e o detalhe (ruptura_pagina.py) da tela "Previsão de Ruptura de estoque" usam do mesmo jeito.
# Só texto: aqui NÃO há banco, API nem regra de negócio (as contas estão em ruptura_calculo.py). Também mora aqui o texto do que o Mercado Livre recomenda e o do porquê da urgência do Sistema,
# que a lista e o detalhe escrevem do mesmo jeito.

from django.utils import timezone

from gestao_full.funcoes_auxiliares.full_estoque_ml import HORAS_PARA_DESATUALIZADO
from gestao_vendas.funcoes_auxiliares.vendas_ml import FUSO, numero

# * [EXPLICAÇÃO] → AS PALAVRAS DE CADA MUNDO (decisão do Matheus, 12/10/2026): as contas são as mesmas, mas no Full a pessoa ENVIA uma remessa ao Full e fora do Full ela faz um PEDIDO e espera a transportadora
#                  entregar. Aqui moram as palavras que mudam (Enviar até / Pedir até, Quanto enviar / Quanto pedir, Com o envio / Com o pedido...), para a lista, o detalhe e o gráfico escreverem igual.
PALAVRAS_DOS_MUNDOS = {
    'full': {
        'enviar_ate': 'Enviar até', 'enviar_ja': 'Enviar já', 'acao_cartao': 'Enviar', 'quanto': 'Quanto enviar', 'com': 'Com o envio', 'urgencia': 'Urgência de envio', 'verbo': 'enviar', 'gerundio': 'enviando',
        'enviado': 'enviado', 'a_remessa': 'a remessa', 'da_remessa': 'da remessa', 'o_envio': 'o envio', 'do_envio': 'do envio', 'estoque': 'Estoque no Full', 'vendas_de': 'do Full', 'unidade_de_venda': 'o Full',
    },
    'fora': {
        'enviar_ate': 'Pedir até', 'enviar_ja': 'Pedir já', 'acao_cartao': 'Pedir', 'quanto': 'Quanto pedir', 'com': 'Com o pedido', 'urgencia': 'Urgência do pedido', 'verbo': 'pedir', 'gerundio': 'pedindo',
        'enviado': 'pedido', 'a_remessa': 'o pedido', 'da_remessa': 'do pedido', 'o_envio': 'o pedido', 'do_envio': 'do pedido', 'estoque': 'Estoque fora do Full', 'vendas_de': 'de fora do Full', 'unidade_de_venda': 'o estoque de fora',
    },
}


# Função Objetivo: As palavras do mundo ('full' | 'fora'): o dicionário de PALAVRAS_DOS_MUNDOS dele (qualquer outra coisa vale como Full).
def palavras(mundo):
    return PALAVRAS_DOS_MUNDOS.get(mundo, PALAVRAS_DOS_MUNDOS['full'])

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


# Função Objetivo: O número com a palavra no singular ou no plural ("1 dia", "15 dias", "1.214 anúncios"): inteiros a partir de mil saem com ponto de milhar, igual ao resto da tela.
def plural(n, singular, plural_):
    return f'{numero(n) if isinstance(n, int) else n} {singular if n == 1 else plural_}'


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


# Função Objetivo: O FRESCOR dos dados de um item (pedido do Matheus, 13/10/2026: "quão velho é o número que estou vendo?"), escrito do MESMO jeito na lista (coluna "Atualizado") e no detalhe (linha do cabeçalho do item).
# Devolve {vendas, estoque, classe, dica}: `vendas` = "vendas até 13/10 08:12" (a coleta de vendas mais recente que cobre o item; "vendas sem coleta" se nenhuma cobre) e `estoque` = "estoque há 5 h" (a consulta MAIS ANTIGA entre
# os Códigos ML lidos do item; "estoque sem consulta" se nenhum foi lido; "" quando `resumo` é None, no Fora do Full, que não lê estoque). `classe` = "atencao" quando falta dado ou há consulta de estoque com mais de
# HORAS_PARA_DESATUALIZADO horas; senão "". `vendas_ate` = instante da coleta (None = nenhuma); `resumo` = ruptura_estoque.somar_codigos do item (None = o mundo não lê estoque).
# * [EXPLICAÇÃO] → "Ausente não é zero": dado que nunca foi lido aparece como "sem coleta" / "sem consulta", nunca como "agora" nem como zero.
def frescor(vendas_ate, resumo=None):
    atencao = False
    if vendas_ate is None:
        vendas = 'vendas sem coleta'
        dica = 'Nenhuma coleta de vendas cobre este item ainda: o ritmo não tem dado. Abra o item e clique em "Atualizar este item".'
        atencao = True
    else:
        quando = timezone.localtime(vendas_ate, FUSO).strftime('%d/%m %H:%M')
        vendas = f'vendas até {quando}'
        dica = f'A coleta de vendas mais recente que cobre este item terminou em {quando}: o que vendeu depois disso ainda não está nos números.'
    estoque = ''
    if resumo is not None:
        if resumo['estado'] == 'sem_leitura':
            estoque = 'estoque sem consulta'
            dica += ' Nenhum Código ML deste item tem o estoque do Full lido: sem leitura não é estoque zero.'
            atencao = True
        else:
            estoque = f'estoque {resumo["idade"]}'
            dica += f' O estoque do Full vem da consulta mais antiga entre os Códigos ML lidos ({resumo["idade"]}).'
            if resumo['estado'] == 'parcial':
                estoque += f' ({resumo["n_lidos"]} de {resumo["n_codigos"]})'
                dica += f' Só {resumo["n_lidos"]} de {resumo["n_codigos"]} Códigos ML foram lidos.'
                atencao = True
            if resumo['desatualizados']:
                dica += f' Há consulta de estoque com mais de {HORAS_PARA_DESATUALIZADO} h: o número pode ter mudado.'
                atencao = True
    return {'vendas': vendas, 'estoque': estoque, 'classe': 'atencao' if atencao else '', 'dica': dica}


# Função Objetivo: Por que o SISTEMA deu a urgência que deu, em uma frase (balão da célula "Urgência" da lista e texto do cartão do detalhe). `cat` é 'sem_estoque' | 'ruptura' | qualquer outra (há projeção)
# e `envio` o resultado de ruptura_calculo.envio (None se não há data de enviar até). `mundo` escolhe as palavras (enviar x pedir).
def porque_da_urgencia_do_sistema(cat, envio, mundo='full'):
    P = palavras(mundo)
    if cat == 'sem_estoque':
        return 'sem estoque lido (não dá para calcular)'
    if cat == 'ruptura':
        return 'o estoque está zerado'
    if envio is None:
        return 'não há ruptura prevista neste ritmo'
    if envio['estado'] == 'vencido':
        return f'o prazo {P["do_envio"]} acabou em {data(envio["ultimo_dia"])}'
    if envio['estado'] != 'ok':
        return f'a data recomendada para {P["verbo"]} ({data(envio["enviar_ate"])}) {"é hoje" if envio["estado"] == "hoje" else "já passou"}'
    return f'{P["enviar_ate"].lower()} {data(envio["enviar_ate"])}, daqui a {plural(envio["em_dias"], "dia", "dias")} (faixas: até 7 dias = esta semana, até 14 = próxima semana, até 21 = em 2 semanas)'


# Função Objetivo: A sugestão do MERCADO LIVRE como texto: (texto, dica). `ml` é o resultado de ruptura_estoque.resumir_ml. O texto é o número ("120") ou a faixa ("100–150"); None quando o ML não tem número
# (nunca vira zero). "Não repor" do ML vira "0" (o ML disse que não é para enviar). A dica explica de onde vem o número (e que o gráfico e a comparação usam o começo da faixa).
def quantidade_do_ml(ml):
    if ml['sugestao_min'] is None:
        if ml['estado'] == 'sem_dados':
            return None, f'Sem número do Mercado Livre: {ml["motivo"]}. Abra o item e clique em "Atualizar este item" (sem número não é zero).'
        return None, 'O Mercado Livre não mandou uma quantidade sugerida para este item (sem número não é zero).'
    parcial = f' Só {ml["n_com_dados"]} de {ml["n_codigos"]} Códigos ML têm a recomendação do ML: a soma é parcial.' if ml['estado'] == 'parcial' else ''
    if ml['nao_repor']:
        return '0', f'O Mercado Livre recomenda NÃO repor este item (nada a enviar).{parcial}'
    if ml['sugestao_min'] == ml['sugestao_max']:
        return numero(ml['sugestao_min']), f'Sugestão do Mercado Livre: {numero(ml["sugestao_min"])} un (exata).{parcial}'
    return (f'{numero(ml["sugestao_min"])}–{numero(ml["sugestao_max"])}',
            f'Sugestão do Mercado Livre: de {numero(ml["sugestao_min"])} a {numero(ml["sugestao_max"])} un (faixa). O gráfico e a comparação usam o começo da faixa ({numero(ml["sugestao_min"])} un).{parcial}')


# Função Objetivo: A célula "Comparação" das QUANTIDADES (Sistema × Mercado Livre): (texto, classe, balão). `diferenca` é ML − Sistema (ruptura_calculo.diferenca_de_quantidades). O texto diz QUEM sugere mais e quanto ("ML +675 un",
# "Sistema +120 un") ou "Iguais"; sem a quantidade de um dos lados fica "Sem comparação" (nunca vira zero). A classe é `ml` | `sis` | `ig` | `sem`.
def comparacao_das_quantidades(qtd_sistema, qtd_ml, diferenca):
    if diferenca is None:
        return 'Sem comparação', 'sem', 'Sem a quantidade de um dos lados (Sistema ou Mercado Livre) não há o que comparar (sem número não é zero).'
    base = f'Sistema: {numero(qtd_sistema)} un. Mercado Livre: {numero(qtd_ml)} un (numa faixa vale o começo dela).'
    if diferenca == 0:
        return 'Iguais', 'ig', f'O Sistema e o Mercado Livre sugerem a mesma quantidade. {base}'
    if diferenca > 0:
        return f'ML +{numero(diferenca)} un', 'ml', f'O Mercado Livre sugere {numero(diferenca)} un a MAIS que o Sistema. {base}'
    return f'Sistema +{numero(-diferenca)} un', 'sis', f'O Sistema sugere {numero(-diferenca)} un a MAIS que o Mercado Livre. {base}'


# Função Objetivo: O aviso de depósito: quando a quantidade a enviar passa do estoque do ERP (o que há no depósito), devolve (curto, longo): o curto vai no cartão ("só há 80 un no depósito") e o longo na dica.
# Sem quantidade, sem número do ERP ou com depósito suficiente: ('', ''). A tela SEMPRE mostra a quantidade inteira da sugestão; o aviso só diz que não dá para enviar tudo (decisão do Matheus).
def aviso_do_deposito(qtd, deposito):
    if qtd is None or deposito is None or qtd <= deposito:
        return '', ''
    return (f'só há {numero(deposito)} un no depósito',
            f'Atenção: a quantidade a enviar ({numero(qtd)} un) é maior que o estoque do depósito ({numero(deposito)} un, o Estoque do cadastro do Produto no ERP): faltam {numero(qtd - deposito)} un para enviar tudo. '
            f'A tela mostra a quantidade inteira mesmo assim.')
