# gestao_ruptura/funcoes_auxiliares/ruptura_parametros.py
#
# Função Objetivo: Lê da query string os parâmetros que a LISTA e o DETALHE da tela "Previsão de Ruptura de estoque" dividem (ritmo, lead time, margem de segurança, quantos dias cada remessa cobre
# e a opção "Considerar as unidades a caminho") e devolve o dicionário `comuns`, que as duas partes da tela recebem. Também monta de volta os mesmos parâmetros para os ENDEREÇOS (links e formulários),
# sempre OMITINDO o que está no valor padrão: assim cada link leva só o que a pessoa mudou. Nada daqui é guardado: tudo fica no endereço da página.
#
# REGRAS DO MATHEUS que moram aqui:
#   - A MARGEM DE SEGURANÇA padrão é 100% do lead time (lead de 15 dias → a remessa deve chegar com 15 dias de estoque sobrando, ou seja, a ruptura precisa estar a 30 dias do envio). Editável na tela.
#   - "Quantos dias cada remessa cobre" ainda NÃO foi definido (depende do retorno do responsável pelo Full): sem digitar, vale o lead time e a tela avisa "padrão provisório".
#   - O lead time sem digitar é o padrão provisório de ruptura_calculo.LEAD_TIME_PADRAO.
#   - QUANTO ENVIAR (decisão do Matheus, 12/10/2026): a pessoa escolhe a referência da quantidade (`ref_qtd`: sistema | ml | manual) e, na referência "Minha quantidade", digita o número (`qtd`). Digitar uma
#     quantidade sem escolher a referência já vale como "manual". A quantidade digitada só vale no DETALHE de um item (a lista não tem uma quantidade digitada por linha: lá "manual" vira "sistema").
#   - REFERÊNCIA DE URGÊNCIA (`ref_urg`: ml | sistema): de quem é a urgência que manda na tela (a ordem "Mais urgentes primeiro" e o selo grande); a outra aparece pequena ao lado. O padrão é o SISTEMA (a regra
#     da própria tela, que funciona mesmo sem consulta de reposição salva); trocar o padrão é mudar REFERENCIA_DE_URGENCIA_PADRAO aqui.
#
# * [EXPLICAÇÃO] → Este arquivo só LÊ e DEVOLVE valores (nada de banco, API ou tela). Um parâmetro novo que valha para a lista e para o detalhe nasce aqui, e não repetido em dois lugares.

from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import inteiro
from integracao_mercado_livre.servicos.cobertura_vendas_ml import primeiro_dia_do_ml


REFERENCIAS_DE_QTD = ('sistema', 'ml', 'manual')
REFERENCIAS_DE_URGENCIA = ('ml', 'sistema')   # a ordem em que os botões aparecem na tela
REFERENCIA_DE_URGENCIA_PADRAO = 'sistema'
QTD_MAXIMA = 1_000_000


# Função Objetivo: Os parâmetros comuns da tela, já validados (valor inválido volta ao padrão): dias (o ritmo dos últimos N dias, no máximo o que o Mercado Livre guarda), lead, margem (% do lead time),
# folga (a margem em dias), cobre (dias que cada remessa cobre), `*_digitado` (None quando a pessoa não digitou: o endereço então não leva o parâmetro), caminho, recente e maximo, mais a referência
# de quanto enviar (ref_qtd: sistema | ml | manual), a quantidade digitada (qtd; None se não digitou) e a referência de urgência (ref_urg: ml | sistema).
def ler_comuns(parametros, hoje):
    maximo = (hoje - primeiro_dia_do_ml(hoje)).days   # o Mercado Livre guarda ~12 meses de pedidos
    pedido = inteiro(parametros.get('dias'), 1, 3650)
    dias = min(pedido or calc.DIAS_PADRAO, maximo)
    lead_digitado = inteiro(parametros.get('lead'), 0, 365)
    lead = calc.LEAD_TIME_PADRAO if lead_digitado is None else lead_digitado
    margem_digitada = inteiro(parametros.get('margem'), 0, calc.MARGEM_MAXIMA_PCT)
    margem = calc.MARGEM_PADRAO_PCT if margem_digitada is None else margem_digitada
    cobre_digitado = inteiro(parametros.get('cobre'), 0, calc.COBRE_MAXIMO_DIAS)
    cobre = lead if cobre_digitado is None else cobre_digitado
    caminho = (parametros.get('caminho') or '').strip() == '1'   # "Considerar as unidades a caminho" (checkbox; desmarcado por padrão)
    qtd = inteiro(parametros.get('qtd'), 0, QTD_MAXIMA)
    ref_qtd = (parametros.get('ref_qtd') or '').strip()
    if ref_qtd not in REFERENCIAS_DE_QTD:
        ref_qtd = 'manual' if qtd is not None else 'sistema'
    ref_urg = (parametros.get('ref_urg') or '').strip()
    if ref_urg not in REFERENCIAS_DE_URGENCIA:
        ref_urg = REFERENCIA_DE_URGENCIA_PADRAO
    return {
        'dias': dias, 'dias_pedidos': pedido, 'lead': lead, 'lead_digitado': lead_digitado, 'margem': margem, 'folga': calc.folga_em_dias(lead, margem),
        'cobre': cobre, 'cobre_digitado': cobre_digitado, 'recente': min(calc.DIAS_DO_RITMO_RECENTE, maximo), 'maximo': maximo, 'caminho': caminho, 'ref_qtd': ref_qtd, 'qtd': qtd, 'ref_urg': ref_urg,
    }


# Função Objetivo: Os parâmetros comuns no formato dos endereços (para url_da_tela): cada um só aparece quando é diferente do padrão (None = fica de fora do endereço). `dias` pode ser trocado
# (os atalhos de ritmo do gráfico levam outro período). A referência de urgência e a de quanto enviar vão sempre que não são o padrão; `detalhe=True` leva também a quantidade DIGITADA (só vale no detalhe
# de um item: na lista, "Minha quantidade" não existe e vira "Do Sistema").
def para_url(comuns, dias=None, detalhe=False):
    dias = comuns['dias'] if dias is None else dias
    manual = detalhe and comuns['ref_qtd'] == 'manual'
    ref_qtd = comuns['ref_qtd'] if (detalhe or comuns['ref_qtd'] != 'manual') else 'sistema'
    return {
        'dias': None if dias == calc.DIAS_PADRAO else dias,
        'lead': None if comuns['lead'] == calc.LEAD_TIME_PADRAO else comuns['lead'],
        'margem': None if comuns['margem'] == calc.MARGEM_PADRAO_PCT else comuns['margem'],
        'cobre': comuns['cobre_digitado'],
        'caminho': 1 if comuns['caminho'] else None,
        'ref_qtd': None if ref_qtd == 'sistema' else ref_qtd,
        'qtd': comuns['qtd'] if manual else None,
        'ref_urg': None if comuns['ref_urg'] == REFERENCIA_DE_URGENCIA_PADRAO else comuns['ref_urg'],
    }
