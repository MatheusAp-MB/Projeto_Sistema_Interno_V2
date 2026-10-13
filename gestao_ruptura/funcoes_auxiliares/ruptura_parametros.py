# gestao_ruptura/funcoes_auxiliares/ruptura_parametros.py
#
# Função Objetivo: Lê da query string os parâmetros que a LISTA e o DETALHE da tela "Previsão de Ruptura de estoque" dividem e devolve o dicionário `comuns`, que as duas partes da tela recebem. Também monta
# de volta os mesmos parâmetros para os ENDEREÇOS (links e formulários), sempre OMITINDO o que está no valor padrão: assim cada link leva só o que a pessoa mudou. Nada daqui é guardado: tudo fica no endereço.
#
# OS DOIS MUNDOS (decisão do Matheus, 12/10/2026): a tela tem dois mundos ISOLADOS, cada um com as suas regras: ENVIOS FULL (`mundo` ausente do endereço) e FORA DO FULL (`mundo=fora`). Cada mundo tem os
# SEUS campos: dias (o ritmo dos últimos N dias), lead (prazo até vender), ante (chegar N dias antes da ruptura), folga (dias de estoque que o envio acrescenta) e, no detalhe, estoque digitado. O Full usa os nomes
# simples (dias, lead, ante, folga, estoque); o Fora do Full usa os mesmos com o sufixo `_f` (dias_f, lead_f, ante_f, folga_f, estoque_f). O endereço leva os dois conjuntos: trocar de mundo não perde o que foi
# digitado no outro. Só o Full tem "Contar o que está a caminho" (caminho) e "Quem recomenda" (ref_urg, ref_qtd, qtd): o Mercado Livre só recomenda para o Full.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O ANTE (chegar antes da ruptura) padrão é de 3 dias nos dois mundos: o envio tem que chegar até 3 dias antes da ruptura total ("para nunca ficarmos sem venda, mas também para não mandar envios muito antes
#     e sobrecarregar o estoque"). Editável.
#   - A FOLGA ainda NÃO foi definida (depende do retorno do responsável pelo Full): sem digitar, vale o prazo (lead time) e a tela avisa "provisório".
#   - O PRAZO sem digitar é o padrão provisório de ruptura_calculo.LEAD_TIME_PADRAO.
#   - QUANTO ENVIAR (decisão do Matheus, 12/10/2026): no Full a pessoa escolhe a referência da quantidade (`ref_qtd`: sistema | ml | manual) e, na referência "Minha quantidade", digita o número (`qtd`). Digitar uma
#     quantidade sem escolher a referência já vale como "manual". A quantidade digitada só vale no DETALHE de um item (a lista não tem uma quantidade digitada por linha: lá "manual" vira "sistema"). Fora do Full a
#     quantidade é sempre a sugestão do Sistema.
#   - REFERÊNCIA DE URGÊNCIA (`ref_urg`: ml | sistema): de quem é a urgência que manda na tela (a ordem "Mais urgentes primeiro" e o selo grande); a outra aparece pequena ao lado. O padrão é o SISTEMA (a regra
#     da própria tela, que funciona mesmo sem consulta de reposição salva); trocar o padrão é mudar REFERENCIA_DE_URGENCIA_PADRAO aqui. Fora do Full só existe o Sistema.
#   - OS FILTROS DO HUB (decisão do Matheus, 12/10/2026: "trazer esses filtros para a tela de previsão de ruptura"): a tela tem o MESMO painel "Filtros" do Hub de Anúncios, com os mesmos nomes no endereço (marca, status,
#     tipo_anuncio, logistica, catalogo, flex, desconto, conexao_erp, score, competicao). Quem os define e lê é mercado_livre/funcoes_auxiliares/filtros_do_hub.py (um dono só); aqui eles só viajam com o resto. São
#     COMUNS aos dois mundos (marca, situação, tipo... são do anúncio, não de um mundo): trocar de mundo não os perde. Duas exceções, e só duas: (1) "estoque" NÃO existe nesta tela (FILTROS_QUE_ESTA_TELA_IGNORA): o
#     parâmetro `estoque` daqui já é o estoque digitado no detalhe, e "estoque" no Hub é outra coisa (a quantidade do anúncio); (2) "logistica" só vale no Fora do Full (no Envios Full todo anúncio é FULL): lá o
#     cartão some do painel e o filtro NÃO é aplicado, mas continua no endereço para voltar a valer quando a pessoa olhar o Fora do Full.
#
# * [EXPLICAÇÃO] → Este arquivo só LÊ e DEVOLVE valores (nada de banco, API ou tela). Um parâmetro novo que valha para a lista e para o detalhe nasce aqui, e não repetido em dois lugares.

from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import inteiro
from integracao_mercado_livre.servicos.cobertura_vendas_ml import primeiro_dia_do_ml
from mercado_livre.funcoes_auxiliares.filtros_do_hub import CHAVES_DO_FILTRO, PARAMETROS_DO_FILTRO, ler_filtros
from mercado_livre.funcoes_auxiliares.filtros_do_hub import para_url as filtros_para_url


MUNDOS = ('full', 'fora')
MUNDO_PADRAO = 'full'
SUFIXO_DO_MUNDO = {'full': '', 'fora': '_f'}
CAMPOS_DO_MUNDO = ('dias', 'lead', 'ante', 'folga', 'estoque')
CAMPOS_SO_DO_FULL = ('caminho', 'ref_urg', 'ref_qtd', 'qtd')
REFERENCIAS_DE_QTD = ('sistema', 'ml', 'manual')
REFERENCIAS_DE_URGENCIA = ('ml', 'sistema')   # a ordem em que os botões aparecem na tela
REFERENCIA_DE_URGENCIA_PADRAO = 'sistema'
QTD_MAXIMA = 1_000_000
ESTOQUE_MAXIMO = 10_000_000
FILTROS_QUE_ESTA_TELA_IGNORA = ('estoque',)   # chaves de filtros_do_hub: ver "OS FILTROS DO HUB" no cabeçalho
FILTRO_DE_LOGISTICA = 'tipos_logisticos'      # só vale no Fora do Full


# Função Objetivo: O nome de um campo do formulário em cada mundo: "dias" no Full e "dias_f" no Fora do Full.
def nome_do_campo(campo, mundo):
    return campo + SUFIXO_DO_MUNDO[mundo]


# Função Objetivo: Os nomes dos campos do mundo escolhido, do jeito que o template os usa: {dias, lead, ante, folga, estoque} → nome no endereço.
def nomes_do_mundo(mundo):
    return {campo: nome_do_campo(campo, mundo) for campo in CAMPOS_DO_MUNDO}


# Função Objetivo: Os parâmetros de UM mundo, já validados (valor inválido volta ao padrão): dias (o ritmo dos últimos N dias, no máximo o que o Mercado Livre guarda), lead (prazo até vender), ante (chegar
# N dias antes da ruptura), folga (dias de estoque que o envio acrescenta; sem digitar vale o prazo) e o estoque digitado (None se vazio). `*_digitado` é None quando a pessoa não digitou: o endereço então não
# leva o parâmetro.
def _ler_do_mundo(parametros, mundo, maximo):
    def bruto(campo):
        return parametros.get(nome_do_campo(campo, mundo))

    pedido = inteiro(bruto('dias'), 1, 3650)
    lead_digitado = inteiro(bruto('lead'), 0, 365)
    lead = calc.LEAD_TIME_PADRAO if lead_digitado is None else lead_digitado
    ante_digitado = inteiro(bruto('ante'), 0, calc.ANTECEDENCIA_MAXIMA)
    folga_digitada = inteiro(bruto('folga'), 0, calc.FOLGA_MAXIMA_DIAS)
    return {
        'dias': min(pedido or calc.DIAS_PADRAO, maximo), 'dias_pedidos': pedido, 'lead': lead, 'lead_digitado': lead_digitado,
        'ante': calc.ANTECEDENCIA_PADRAO if ante_digitado is None else ante_digitado, 'ante_digitado': ante_digitado,
        'folga': lead if folga_digitada is None else folga_digitada, 'folga_digitada': folga_digitada,
        'estoque': inteiro(bruto('estoque'), 0, ESTOQUE_MAXIMO),
    }


# Função Objetivo: Os filtros do Hub que NÃO aparecem (nem valem) no mundo escolhido: os que a tela ignora e, no Envios Full, a logística. Quem desenha o painel e quem decide os campos escondidos usa esta lista.
def filtros_escondidos(mundo):
    return tuple(chave for chave in CHAVES_DO_FILTRO if chave in FILTROS_QUE_ESTA_TELA_IGNORA or (chave == FILTRO_DE_LOGISTICA and mundo == 'full'))


# Função Objetivo: Os parâmetros comuns da tela, já validados. Devolve os campos do MUNDO ESCOLHIDO "achatados" (dias, lead, ante, folga, estoque e os `*_digitado`), o `mundo` ('full' | 'fora'), `por_mundo`
# (os mesmos campos de cada mundo, para montar os endereços dos dois), `filtros` (os do painel do Hub, como estão no endereço) e `filtros_do_mundo` (só os que valem no mundo da tela), `recente`, `maximo` e as escolhas que só existem no Full: caminho, ref_qtd (sistema | ml | manual), qtd (digitada; None se não digitou) e
# ref_urg (ml | sistema). Fora do Full essas escolhas valem como "sem caminho, Sistema, sem quantidade digitada" (o Mercado Livre só recomenda para o Full); as do Full continuam guardadas em `extras_full`,
# para o endereço não perdê-las enquanto a pessoa olha o Fora do Full.
def ler_comuns(parametros, hoje):
    maximo = (hoje - primeiro_dia_do_ml(hoje)).days   # o Mercado Livre guarda ~12 meses de pedidos
    mundo = 'fora' if (parametros.get('mundo') or '').strip() == 'fora' else MUNDO_PADRAO
    por_mundo = {m: _ler_do_mundo(parametros, m, maximo) for m in MUNDOS}
    caminho = (parametros.get('caminho') or '').strip() == '1'   # "Contar o que está a caminho" (checkbox; desmarcado por padrão)
    qtd = inteiro(parametros.get('qtd'), 0, QTD_MAXIMA)
    ref_qtd = (parametros.get('ref_qtd') or '').strip()
    if ref_qtd not in REFERENCIAS_DE_QTD:
        ref_qtd = 'manual' if qtd is not None else 'sistema'
    ref_urg = (parametros.get('ref_urg') or '').strip()
    if ref_urg not in REFERENCIAS_DE_URGENCIA:
        ref_urg = REFERENCIA_DE_URGENCIA_PADRAO
    extras_full = {'caminho': caminho, 'ref_qtd': ref_qtd, 'qtd': qtd, 'ref_urg': ref_urg}
    efetivos = extras_full if mundo == 'full' else {'caminho': False, 'ref_qtd': 'sistema', 'qtd': None, 'ref_urg': REFERENCIA_DE_URGENCIA_PADRAO}
    filtros = ler_filtros(parametros, ignorar=FILTROS_QUE_ESTA_TELA_IGNORA)
    escondidos = filtros_escondidos(mundo)
    filtros_do_mundo = {chave: ([] if chave in escondidos else valores) for chave, valores in filtros.items()}
    return {**por_mundo[mundo], 'mundo': mundo, 'por_mundo': por_mundo, 'filtros': filtros, 'filtros_do_mundo': filtros_do_mundo, 'recente': min(calc.DIAS_DO_RITMO_RECENTE, maximo), 'maximo': maximo,
            'extras_full': extras_full, **efetivos}


# Função Objetivo: Os parâmetros comuns no formato dos endereços (para url_da_tela): cada um só aparece quando é diferente do padrão (None = fica de fora do endereço). Leva os campos dos DOIS mundos (o do
# Fora do Full com o sufixo `_f`), o `mundo` quando é o Fora do Full e os filtros do Hub marcados (listas: um parâmetro repetido por valor; o endereço leva também a logística escolhida no Fora do Full enquanto se olha o Full). `dias` pode ser trocado (os atalhos de ritmo do gráfico levam outro período; vale para o mundo que está na tela). A referência de urgência e a
# de quanto enviar vão sempre que não são o padrão; `detalhe=True` leva também o estoque DIGITADO de cada mundo e a quantidade DIGITADA (só valem no detalhe de um item: na lista, "Minha quantidade" não existe
# e vira "Sistema").
def para_url(comuns, dias=None, detalhe=False):
    extras = comuns['extras_full']
    manual = detalhe and extras['ref_qtd'] == 'manual'
    ref_qtd = extras['ref_qtd'] if (detalhe or extras['ref_qtd'] != 'manual') else 'sistema'
    saida = {'mundo': None if comuns['mundo'] == MUNDO_PADRAO else comuns['mundo']}
    for mundo in MUNDOS:
        valores = comuns['por_mundo'][mundo]
        dias_do_mundo = dias if (dias is not None and mundo == comuns['mundo']) else valores['dias']
        saida.update({
            nome_do_campo('dias', mundo): None if dias_do_mundo == calc.DIAS_PADRAO else dias_do_mundo,
            nome_do_campo('lead', mundo): None if valores['lead'] == calc.LEAD_TIME_PADRAO else valores['lead'],
            nome_do_campo('ante', mundo): None if valores['ante'] == calc.ANTECEDENCIA_PADRAO else valores['ante'],
            nome_do_campo('folga', mundo): valores['folga_digitada'],
            nome_do_campo('estoque', mundo): valores['estoque'] if detalhe else None,
        })
    saida.update({
        'caminho': 1 if extras['caminho'] else None,
        'ref_qtd': None if ref_qtd == 'sistema' else ref_qtd,
        'qtd': extras['qtd'] if manual else None,
        'ref_urg': None if extras['ref_urg'] == REFERENCIA_DE_URGENCIA_PADRAO else extras['ref_urg'],
    })
    saida.update(filtros_para_url(comuns['filtros']))
    return saida


# Função Objetivo: Os campos ESCONDIDOS do formulário da tela: tudo o que vai no endereço e que NÃO é um campo visível do mundo que está na tela (o `mundo`, os campos do outro mundo e, no Fora do Full, as escolhas
# do Full). Assim, aplicar o formulário de um mundo não apaga o que foi digitado no outro. `detalhe=True` no detalhe de um item (os estoques e a quantidade digitados também são campos do formulário).
# Devolve [{nome, valor}] só do que tem valor (um por valor, nos filtros de vários valores).
# * [EXPLICAÇÃO] → No Full, a LISTA só tem o campo visível "a caminho" entre as escolhas do Full: o cartão "Quem recomenda" (ref_urg, ref_qtd e a quantidade digitada) só existe no DETALHE de um item (13/10/2026: na lista o Sistema é
#                  a base e o Mercado Livre é a chave "Comparar com o Mercado Livre"). Na lista essas escolhas viajam escondidas, para a pessoa levá-las ao abrir um item.
# * [EXPLICAÇÃO] → Os filtros do Hub são campos VISÍVEIS da lista (o painel "Filtros" fica dentro do mesmo formulário), menos a logística no Envios Full (o cartão não existe lá: ela viaja escondida para
#                  não se perder). No detalhe o painel não aparece: todos os filtros viajam escondidos.
def campos_escondidos(comuns, detalhe=False):
    visiveis = {nome_do_campo(c, 'full') for c in CAMPOS_DO_MUNDO} | (set(CAMPOS_SO_DO_FULL) if detalhe else {'caminho'}) if comuns['mundo'] == 'full' else {nome_do_campo(c, 'fora') for c in CAMPOS_DO_MUNDO}
    if not detalhe:
        sem_cartao = filtros_escondidos(comuns['mundo'])
        visiveis |= {parametro for chave, parametro in PARAMETROS_DO_FILTRO if chave not in sem_cartao}
    escondidos = []
    for nome, valor in para_url(comuns, detalhe=detalhe).items():
        if nome in visiveis:
            continue
        escondidos += [{'nome': nome, 'valor': v} for v in (valor if isinstance(valor, list) else [valor]) if v not in (None, '')]
    return escondidos
