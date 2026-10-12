# gestao_ruptura/funcoes_auxiliares/ruptura_pagina.py
#
# Função Objetivo: Monta tudo o que a tela "Ruptura de estoque" mostra, a partir da query string.
#   - SEM sku: a LISTA por urgência, por Produto (SKU), Anúncio (MLB) ou Código ML (ruptura_lista.py; gran, q, nivel, ord, por, pag).
#   - COM sku: o DETALHE de um item, com a curva, os cartões e o diagnóstico: o próprio SKU, ou um MLB / Código ML dele (gran=mlb|codigo + item). Parâmetros: sku, gran, item,
#     visao (full | fora | produto), estoque (digitado, opcional).
#   - Em qualquer um: dias (o ritmo dos últimos N dias), lead (lead time em dias; sem digitar vale o padrão provisório de ruptura_calculo.LEAD_TIME_PADRAO) e caminho (=1: a opção
#     "Considerar as unidades a caminho", que soma o "a caminho" ao estoque lido do Full; desmarcada por padrão).
# LÊ SÓ DO BANCO (as vendas já coletadas pela tela de Vendas e a última consulta salva do estoque do Full) e NUNCA chama a API do Mercado Livre nem a do ERP. Nada do que a pessoa
# digita é guardado: fica só no endereço da página.
#
# REGRAS DO MATHEUS que moram aqui:
#   - O ritmo vem das vendas reais, com as MESMAS regras da tela de Vendas (vendas_ml.unidades_por_dia): só dias completos, venda cancelada não conta, "ausente não é zero".
#     Quem decide No Full / Fora do Full é a regra única de origem (vendas_ml.classificar_origem).
#   - O estoque do Full vem da última consulta salva de cada Código ML (ruptura_estoque.py: estoque considerado = disponível + em transferência + em processo interno; regra provisória).
#     Fora do Full a API de estoque ainda precisa ser corrigida: lá o estoque continua DIGITADO. Em qualquer visão, o que for digitado vale no lugar do lido (para simular).
#   - O "a caminho" só entra no estoque quando a opção "Considerar as unidades a caminho" está marcada (ruptura_estoque.estoque_para_cobertura): como se já estivesse no Full hoje. Estoque
#     DIGITADO nunca recebe o a caminho: o que a pessoa digitou vale como está.
#   - O ritmo "dos últimos N dias" segue a regra do período da tela de Vendas: N dias completos + o dia de hoje (parcial, que fica fora da média).
#
# * [EXPLICAÇÃO] → Cada peça mora no seu arquivo: ruptura_calculo.py (contas), ruptura_estoque.py (estoque do Full), ruptura_grafico.py (curva), ruptura_lista.py (lista) e ruptura_texto.py
#                  (formatadores). Este só LIGA tudo e escreve os textos do detalhe.
# * [EXPLICAÇÃO] → Os textos já saem prontos para o template (strings), e a tela é rígida na vertical: cada cartão tem 1 linha de valor e 1 de apoio (o resto vai no "title" do cartão), então
#                  nada muda de altura conforme o texto.
# * [EXPLICAÇÃO] → O ritmo do DETALHE usa a cobertura do PRÓPRIO produto (como a tela de Vendas do produto) e o da LISTA usa a cobertura da conta toda (como a lista de Vendas). Se um produto foi
#                  atualizado sozinho além do que a conta toda coletou, os dois podem diferir um pouco: é a mesma diferença que já existe entre a lista e o calendário de Vendas.

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.urls import reverse

from gestao_full.funcoes_auxiliares.full_estoque_ml import a_caminho_dos_codigos, estoque_full_dos_codigos
from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares import ruptura_estoque as full
from gestao_ruptura.funcoes_auxiliares.ruptura_grafico import montar_grafico
from gestao_ruptura.funcoes_auxiliares.ruptura_lista import montar_lista
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import data as _data, inteiro as _inteiro, pct as _pct, plural as _plural, un_dia as _un_dia
from gestao_vendas.funcoes_auxiliares.vendas_ml import numero, unidades_por_dia, url_da_tela
from integracao_mercado_livre.servicos.cobertura_vendas_ml import primeiro_dia_do_ml

FUSO = ZoneInfo('America/Sao_Paulo')
ATALHOS_DE_DIAS = (7, 15, 30, 60, 90, 120)   # + "1 ano" (o máximo do Mercado Livre), montado em montar_pagina
VISOES = (
    ('full', 'No Full', 'Só as vendas cujo estoque saiu de um centro do Full. O estoque é o do Full (lido da última consulta salva, ou digitado).'),
    ('fora', 'Fora do Full', 'Só as vendas do estoque próprio (coleta, agência, Flex). O estoque é o do seu estoque: digite o valor (a API de estoque ainda será corrigida).'),
    ('produto', 'Produto (tudo)', 'Todas as vendas, Full e fora do Full. O estoque é a soma dos dois: digite o valor.'),
)
ROTULO_DO_ESTOQUE = {'full': 'Estoque no Full', 'fora': 'Estoque fora do Full', 'produto': 'Estoque total'}
GRANULARIDADES_DO_DETALHE = ('sku', 'mlb', 'codigo')


def _em_dias(n):
    return 'ainda hoje' if n == 0 else f'em {_plural(n, "dia", "dias")}'


# ==================================================== cartões ====================================================

# Função Objetivo: Um cartão "Ruptura · ritmo de N dias": a data em que o estoque acaba nesse ritmo, em quantos dias, o ritmo e o nível. Sem estoque ou sem ritmo, o cartão
# fica com "—" e diz o que falta (mesmo tamanho: a tela não muda de altura).
def _cartao_de_ruptura(rotulo, explicacao, ritmo, estoque, lead, hoje, destaque=False):
    cartao = {'rotulo': rotulo, 'destaque': destaque, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': '—', 'sub': ''}
    media = ritmo['media']
    if media is None:
        cartao['sub'] = 'sem dias completos coletados'
    elif estoque is None:
        cartao['sub'] = f'{_un_dia(media)} un/dia · informe o estoque'
    else:
        projecao = calc.projetar(estoque, media, hoje)
        nivel = calc.nivel_do_estoque(projecao, lead)
        ritmo_texto = f'{_un_dia(media)} un/dia'
        if projecao['situacao'] == 'zerado':
            cartao['valor'], cartao['sub'] = 'Em ruptura', f'estoque zerado · {ritmo_texto}'
        elif projecao['situacao'] == 'sem_vendas':
            cartao['valor'], cartao['sub'] = 'Sem previsão', 'nenhuma venda nos dias completos'
        elif projecao['situacao'] == 'longe':
            cartao['valor'], cartao['sub'] = 'Sem previsão', f'dura mais de {numero(calc.DIAS_MAXIMOS_DA_PROJECAO)} dias · {ritmo_texto}'
        else:
            cartao['valor'], cartao['sub'] = _data(projecao['data']), f'{_em_dias(projecao["dias"])} · {ritmo_texto}'
        if nivel:
            cartao['nivel'], cartao['nivel_rotulo'], cartao['nivel_titulo'] = nivel, calc.NIVEIS_CURTOS[nivel], calc.NIVEIS[nivel]
    cartao['dica'] = f'{explicacao} {cartao["sub"]}.'
    return cartao


# ==================================================== diagnóstico ====================================================

def _item(classe, icone, texto):
    return {'classe': classe, 'icone': icone, 'texto': texto}


# Função Objetivo: O texto do diagnóstico, em português simples: o que o estoque faz no ritmo do período, quando preparar o envio, o ponto de pedido e se o ritmo
# acelerou ou caiu nos últimos dias. O nível mostrado é o do ritmo do período escolhido.
def _diagnostico(estoque, lead, dias, recente, ritmo_p, ritmo_r, mesmo_ritmo, hoje, a_caminho_somado=0):
    media = ritmo_p['media']
    sem = {'nivel': None, 'nivel_rotulo': '', 'itens': []}
    if media is None:
        return {**sem, 'resumo': f'Nenhum dia completo dos últimos {dias} foi coletado para este recorte: sem isso não dá para calcular o ritmo de vendas.'}
    ritmo_texto = f'{_un_dia(media)} un/dia'
    if estoque is None:
        return {**sem, 'resumo': f'O ritmo dos últimos {dias} dias é de {ritmo_texto}. Informe o estoque atual (e o lead time) para ver a projeção.'}

    projecao = calc.projetar(estoque, media, hoje)
    situacao = projecao['situacao']
    nivel = calc.nivel_do_estoque(projecao, lead)
    itens = []
    if situacao == 'zerado':
        resumo = 'O estoque está zerado: o produto já está em ruptura.'
    elif situacao == 'sem_vendas':
        resumo = f'Nos últimos {dias} dias completos não houve nenhuma venda: com {numero(estoque)} un em estoque não há ruptura prevista neste ritmo.'
    elif situacao == 'longe':
        resumo = f'Com {ritmo_texto}, o estoque de {numero(estoque)} un dura mais de {numero(calc.DIAS_MAXIMOS_DA_PROJECAO)} dias.'
    else:
        resumo = f'Com {ritmo_texto} (ritmo dos últimos {dias} dias), o estoque de {numero(estoque)} un dura cerca de {_plural(projecao["dias"], "dia", "dias")}.'
        itens.append(_item('alerta' if nivel in ('critico', 'ruptura') else 'info', 'fa-calendar-xmark', f'Ruptura prevista em {_data(projecao["data"])} ({_em_dias(projecao["dias"])}).'))
    if a_caminho_somado:
        itens.append(_item('info', 'fa-truck', f'O estoque de {numero(estoque)} un inclui {numero(a_caminho_somado)} un a caminho (enviadas ao Full e ainda não recebidas): a conta trata essas unidades como se já estivessem lá hoje.'))

    # ---- o envio e o ponto de pedido (dependem do lead time) ----
    if lead is None:
        itens.append(_item('info', 'fa-circle-info', 'Informe o lead time para ver a data limite do envio e o nível do estoque.'))
    elif situacao == 'zerado':
        quando = 'assim que for enviado' if lead == 0 else f'{_plural(lead, "dia", "dias")} depois do envio'
        itens.append(_item('alerta', 'fa-truck-fast', f'Com lead time de {_plural(lead, "dia", "dias")}, o produto só volta a ficar disponível {quando}: envie o quanto antes.'))
    elif situacao == 'normal':
        envio = calc.envio(projecao, lead, hoje)
        if envio['atrasado']:
            itens.append(_item('alerta', 'fa-triangle-exclamation',
                               f'O prazo de envio já passou: com lead time de {_plural(lead, "dia", "dias")}, mesmo enviando hoje o produto só fica disponível em {_data(envio["chegada"])} '
                               f'e vão faltar cerca de {_plural(envio["faltam_dias"], "dia", "dias")} de estoque.'))
        else:
            quando = 'hoje' if envio['em_dias'] == 0 else f'daqui a {_plural(envio["em_dias"], "dia", "dias")}'
            itens.append(_item('ok', 'fa-truck-fast', f'Prepare o envio até {_data(envio["enviar_ate"])} ({quando}). Com lead time de {_plural(lead, "dia", "dias")}, '
                                                      f'o produto fica disponível quando o estoque acabar.'))
        pedido = calc.ponto_de_pedido(media, lead)
        abaixo = estoque < media * lead
        itens.append(_item('info', 'fa-gauge-high', f'Ponto de pedido: {numero(pedido)} un (ritmo × lead time). O estoque atual {"já está abaixo" if abaixo else "ainda está acima"} dele.'))
    else:
        itens.append(_item('info', 'fa-circle-info', 'Sem ruptura prevista neste ritmo: não há data limite de envio.'))

    # ---- o ritmo recente contra o do período ----
    comparacao = None if mesmo_ritmo or estoque <= 0 else calc.comparar_ritmos(ritmo_r['media'], media)
    if comparacao and media <= 0 and not ritmo_r['media']:
        comparacao = None   # nenhuma venda nos dois ritmos: não há o que comparar
    if comparacao:
        mr = ritmo_r['media']
        proj_r = calc.projetar(estoque, mr, hoje)
        pct = comparacao['pct']
        recente_texto = f'nos últimos {recente} dias foram {_un_dia(mr)} un/dia, contra {ritmo_texto} no período'
        if comparacao['sentido'] == 'acelerou':
            texto = f'O ritmo acelerou: {recente_texto}{f" ({_pct(pct)})" if pct is not None else ""}.'
            if proj_r['situacao'] == 'normal':
                antes = projecao['dias'] - proj_r['dias'] if situacao == 'normal' else 0
                complemento = f', {_plural(antes, "dia", "dias")} antes' if antes > 0 else ''
                texto += f' Nesse ritmo a ruptura vem em {_data(proj_r["data"])} ({_em_dias(proj_r["dias"])}){complemento}.'
            itens.append(_item('alerta', 'fa-gauge-simple-high', texto))
        elif comparacao['sentido'] == 'caiu':
            texto = f'O ritmo caiu: {recente_texto} ({_pct(pct)}).'
            if proj_r['situacao'] == 'normal':
                texto += f' Nesse ritmo o estoque dura até {_data(proj_r["data"])}.'
            itens.append(_item('info', 'fa-gauge-simple', texto))
        else:
            itens.append(_item('ok', 'fa-circle-check', f'Ritmo estável: {recente_texto}.'))
    return {'nivel': nivel, 'nivel_rotulo': calc.NIVEIS.get(nivel, ''), 'resumo': resumo, 'itens': itens}


# ==================================================== o detalhe de um item ====================================================

def _escolher(parametros, nome, validos, padrao):
    valor = (parametros.get(nome) or '').strip()
    return valor if valor in validos else padrao


# Função Objetivo: Os números de uma soma de estoque (ruptura_estoque.somar_codigos) já como texto para a tabela do detalhe; "—" quando nenhum Código foi lido ("ausente não é zero").
def _numeros_da_tabela(r):
    if r['estado'] == 'sem_leitura':
        return {k: '—' for k in ('total', 'disponivel', 'transferencia', 'processo', 'nao_conta', 'considerado', 'a_caminho')}
    return {'total': numero(r['total']), 'disponivel': numero(r['disponivel']), 'transferencia': numero(r['transferencia']), 'processo': numero(r['processo']),
            'nao_conta': numero(r['nao_conta']), 'considerado': numero(r['considerado']),
            'a_caminho': '—' if r['a_caminho'] is None else numero(r['a_caminho']) + ('*' if r['a_caminho_parcial'] else '')}


# Função Objetivo: A tabela "Estoque no Full por Código ML" do detalhe (o detalhamento do estoque do Full): para cada Código do item, o total, o disponível, o que está em transferência e em
# processo interno, o que fica fora da conta, o estoque considerado (a conta da regra provisória) e o a caminho; e a linha da soma, que é o número que a tela usa quando o estoque não é digitado.
def _tabela_de_codigos(codigos, cartoes, mlbs_do_codigo, soma, caminho=False):
    linhas = []
    for codigo in sorted(codigos):
        r = full.somar_codigos([codigo], cartoes)
        full.preencher_a_caminho(r, [codigo], cartoes)
        lido = r['estado'] == 'ok'
        if lido:
            consulta = r['idade'] + (' · consulta antiga' if r['desatualizados'] else '')
        else:
            consulta = 'erro na última consulta' if r['com_erro'] else 'sem consulta salva'
        linhas.append({'codigo': codigo, 'mlbs': ', '.join(mlbs_do_codigo.get(codigo, [])), 'consulta': consulta, 'atencao': (not lido) or bool(r['desatualizados']), **_numeros_da_tabela(r)})
    return {'linhas': linhas, 'soma': _numeros_da_tabela(soma), 'soma_parcial': soma['estado'] == 'parcial', 'conta': full.texto_da_conta(soma, numero, caminho)}


# Função Objetivo: A linha de apoio sob o campo de estoque do detalhe: diz DE ONDE vem o estoque usado (lido do Full ou digitado) e o que fazer. Sempre uma linha só (a tela é rígida na vertical).
def _dica_do_estoque(visao, digitado, lido, resumo, rotulo, caminho=False):
    parcial = f' Atenção: o lido é parcial ({resumo["n_lidos"]} de {resumo["n_codigos"]} Códigos).' if resumo['estado'] == 'parcial' and visao == 'full' else ''
    if digitado is not None:
        if lido is not None:
            aviso_caminho = ' O "a caminho" não é somado ao valor digitado.' if caminho else ''
            return {'texto': f'Usando o estoque DIGITADO: {numero(digitado)} un. O lido do Full é {numero(lido)} un: apague o campo para voltar ao lido.{aviso_caminho}', 'classe': 'atencao'}
        return {'texto': f'Usando o estoque DIGITADO: {numero(digitado)} un.', 'classe': 'atencao'}
    if visao != 'full':
        return {'texto': f'{rotulo}: digite o valor (só o estoque do Full é lido; a API de estoque do ERP ainda será corrigida).', 'classe': 'atencao'}
    if lido is None:
        return {'texto': 'O estoque do Full deste item não foi lido (sem consulta salva). Digite o estoque para ver a projeção ou faça a consulta na tela "Estoque no Full".', 'classe': 'atencao'}
    if caminho and resumo['a_caminho']:
        return {'texto': f'Usando o estoque lido do Full: {numero(resumo["considerado"])} un + {numero(resumo["a_caminho"])} a caminho = {numero(lido)} un.{parcial} Digite um valor para simular outro estoque.',
                'classe': 'atencao' if parcial else ''}
    sem_caminho = ' Sem o número de "a caminho" para este item: só o estoque do Full entra.' if caminho and resumo['a_caminho'] is None else ''
    return {'texto': f'Usando o estoque lido do Full: {numero(lido)} un (da última consulta salva).{sem_caminho}{parcial} Digite um valor para simular outro estoque.', 'classe': 'atencao' if parcial or sem_caminho else ''}


# Função Objetivo: Preenche `pagina` com o detalhe de UM item (o SKU, ou um MLB / Código ML dele): quem é, o estoque (lido do Full ou digitado), o ritmo, os 4 cartões, a curva, o diagnóstico e a
# tabela de estoque por Código ML. Item que não existe vira um aviso de erro (estado "erro"), nunca uma tela quebrada.
def _montar_detalhe(parametros, base_url, hoje, comuns, pagina, sku):
    dias, lead, recente, caminho = comuns['dias'], comuns['lead'], comuns['recente'], comuns['caminho']
    gran = _escolher(parametros, 'gran', GRANULARIDADES_DO_DETALHE, 'sku')
    item = sku if gran == 'sku' else (parametros.get('item') or '').strip().upper()
    visao = _escolher(parametros, 'visao', ('full',) if gran == 'codigo' else tuple(v[0] for v in VISOES), 'full')
    estoque_digitado = _inteiro(parametros.get('estoque'), 0, 10_000_000)
    # * [EXPLICAÇÃO] → O recorte das vendas: no SKU é a visão escolhida; no MLB é aquele anúncio (e, se a visão é Full ou Fora, só essa origem dele); no Código ML é aquele código só no Full
    #                  (o Código ML é o estoque do Full: venda do mesmo anúncio que saiu de outro lugar não é dele).
    nivel, origem = {'sku': (visao, ''), 'mlb': ('mlb', visao if visao in ('full', 'fora') else ''), 'codigo': ('codigo', 'full')}[gran]
    rotulo_do_estoque = ROTULO_DO_ESTOQUE[visao]
    pagina.update({
        'estado': 'erro', 'sku': sku, 'gran': gran, 'item': item, 'visao': visao, 'rotulo_do_estoque': rotulo_do_estoque, 'mostra_visoes': gran != 'codigo',
        'visoes': [{'chave': chave, 'rotulo': rotulo, 'dica': dica, 'ativo': chave == visao} for chave, rotulo, dica in VISOES],
        'estoque_valor': '' if estoque_digitado is None else str(estoque_digitado), 'estoque_placeholder': 'unidades',
        'ocultos': [{'nome': 'sku', 'valor': sku}] + ([{'nome': 'gran', 'valor': gran}, {'nome': 'item', 'valor': item}] if gran != 'sku' else []),
        'url_lista': url_da_tela(base_url, gran=gran if gran != 'sku' else None, dias=dias if dias != calc.DIAS_PADRAO else None, lead=lead if lead != calc.LEAD_TIME_PADRAO else None,
                                 caminho=1 if caminho else None),
        'cartoes': [], 'grafico': None, 'diagnostico': None, 'alvo': None, 'tabela_de_codigos': None, 'dica_do_estoque': {'texto': '', 'classe': ''},
    })

    de = hoje - timedelta(days=max(dias, recente))
    dados = unidades_por_dia(sku, nivel, de, hoje, '' if gran == 'sku' else item, origem)
    cadastro = dados['cadastro']
    if cadastro is None:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'O SKU "{sku}" não está no cadastro de Produto. Confira o código: ele precisa ser igual ao da tela de Vendas.'})
        return
    mlbs_cad = cadastro['mlbs']
    codigos_do_sku = {c for m in mlbs_cad.values() for _, c in m['variacoes'] if c}
    if gran == 'mlb' and item not in mlbs_cad:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'O anúncio "{item}" não está entre os anúncios do SKU {sku}.'})
        return
    if gran == 'codigo' and item not in codigos_do_sku:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'O Código ML "{item}" não está entre os Códigos ML do SKU {sku}.'})
        return
    codigos = codigos_do_sku if gran == 'sku' else ({c for _, c in mlbs_cad[item]['variacoes'] if c} if gran == 'mlb' else {item})
    mlbs_do_codigo = {c: sorted(m for m, info in mlbs_cad.items() if any(cc == c for _, cc in info['variacoes'])) for c in codigos}

    # ---- o estoque: lido do Full (só na visão "No Full") ou digitado ----
    cartoes = estoque_full_dos_codigos(sorted(codigos)) if codigos else {}
    a_caminho_dos_codigos(cartoes)
    resumo = full.somar_codigos(codigos, cartoes)
    full.preencher_a_caminho(resumo, codigos, cartoes)
    lido = full.estoque_para_cobertura(resumo, caminho) if visao == 'full' else None   # com a opção marcada, já inclui o a caminho
    a_caminho_somado = (resumo['a_caminho'] or 0) if (caminho and lido is not None) else 0
    estoque = estoque_digitado if estoque_digitado is not None else lido
    a_caminho_somado = a_caminho_somado if estoque_digitado is None else 0   # o valor digitado vale como está: o a caminho não é somado a ele
    origem_do_estoque = 'digitado' if estoque_digitado is not None else (('lido do Full' + (' + a caminho' if a_caminho_somado else '')) if lido is not None else '')
    pagina['estoque_placeholder'] = numero(lido) if lido is not None else 'unidades'
    pagina['dica_do_estoque'] = _dica_do_estoque(visao, estoque_digitado, lido, resumo, rotulo_do_estoque, caminho)
    if codigos:
        pagina['tabela_de_codigos'] = _tabela_de_codigos(codigos, cartoes, mlbs_do_codigo, resumo, caminho)

    def janela(n):   # n dias completos para trás + hoje
        return [hoje - timedelta(days=i) for i in range(n, -1, -1)]

    ritmo_p = calc.ritmo_da_janela(janela(dias), dados['por_dia'], dados['estados'])
    ritmo_r = calc.ritmo_da_janela(janela(recente), dados['por_dia'], dados['estados'])
    mesmo_ritmo = dias <= recente
    media = ritmo_p['media']
    n_ok = ritmo_p['n_completos']
    pagina['estado'] = 'ok'

    nivel_vendas = {'sku': visao if visao != 'produto' else None, 'mlb': 'mlb', 'codigo': 'codigo'}[gran]
    url_vendas = url_da_tela(reverse('gestao_vendas_principal'), sku=sku, nivel=nivel_vendas, item=item if gran != 'sku' else None)
    coletado_em = dados['coletado_em']
    atualizado = coletado_em.astimezone(FUSO).strftime('%d/%m %H:%M') if coletado_em else ''
    marca = cadastro['marca']
    if gran == 'sku':
        alvo = {'tipo': 'Produto (SKU)', 'titulo': cadastro['titulo'] or sku, 'imagem': cadastro['imagem'],
                'meta': [('SKU', sku), ('Marca', marca), ('', _plural(len(mlbs_cad), 'anúncio (MLB)', 'anúncios (MLB)')), ('', _plural(len(codigos), 'Código ML', 'Códigos ML'))]}
    elif gran == 'mlb':
        anuncio = mlbs_cad[item]
        alvo = {'tipo': 'Anúncio (MLB)', 'titulo': anuncio['titulo'] or cadastro['titulo'] or item, 'imagem': anuncio['imagem'] or cadastro['imagem'],
                'meta': [('MLB', item), ('SKU', sku), ('Marca', marca), ('', _plural(len(codigos), 'Código ML', 'Códigos ML') if codigos else 'sem Código ML')]}
    else:
        usados = mlbs_do_codigo.get(item, [])
        foto = next((mlbs_cad[m]['imagem'] for m in usados if mlbs_cad[m]['imagem']), '') or cadastro['imagem']
        alvo = {'tipo': 'Código ML', 'titulo': f'{item} — {cadastro["titulo"] or sku}', 'imagem': foto,
                'meta': [('Código ML', item), ('SKU', sku), ('', _plural(len(usados), 'anúncio (MLB)', 'anúncios (MLB)'))]}
    alvo['meta'] = [{'rotulo': rotulo, 'valor': valor} for rotulo, valor in alvo['meta'] if valor]
    alvo.update({'url_vendas': url_vendas, 'atualizado': atualizado})
    pagina['alvo'] = alvo
    if n_ok == 0:
        pagina['avisos'].append({'classe': 'erro', 'texto': f'Nenhum dia completo dos últimos {dias} foi coletado para este recorte, então não dá para calcular o ritmo.',
                                 'link': url_vendas, 'link_texto': 'Atualizar na tela de Vendas'})
    elif n_ok < dias:
        pagina['avisos'].append({'classe': 'aviso', 'texto': f'Faltam dados de {dias - n_ok} dos últimos {dias} dias: a média usa só os {n_ok} dias completos que foram coletados.',
                                 'link': url_vendas, 'link_texto': 'Atualizar na tela de Vendas'})

    # ---- os 4 cartões ----
    de_periodo = hoje - timedelta(days=dias)
    explicacao_periodo = f'Média dos últimos {dias} dias (de {_data(de_periodo)} até ontem). Só dias completos entram: hoje (parcial) e dias sem coleta ficam de fora; venda cancelada não conta.'
    explicacao_recente = f'Média dos últimos {recente} dias completos: mostra se o ritmo mudou há pouco tempo.'
    cartao_vendas = {'rotulo': f'Vendas nos últimos {dias} dias', 'destaque': False, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': f'{numero(ritmo_p["unidades"])} un',
                     'sub': f'média {_un_dia(media)} un/dia · {n_ok}/{dias} dias' if media is not None else 'nenhum dia completo coletado'}
    cartao_vendas['dica'] = f'{explicacao_periodo} Entraram {n_ok} dos {dias} dias; {cartao_vendas["sub"]}.'
    sub_estoque = f'{origem_do_estoque} · lead time de {_plural(lead, "dia", "dias")}' if estoque is not None else 'informe o estoque'
    cartao_estoque = {'rotulo': 'Estoque e lead time', 'destaque': False, 'nivel': None, 'nivel_rotulo': '', 'nivel_titulo': '', 'valor': '—' if estoque is None else f'{numero(estoque)} un',
                      'sub': sub_estoque}
    cartao_estoque['dica'] = (f'{rotulo_do_estoque} ({origem_do_estoque or "não informado"}) e lead time (dias até o produto ficar disponível para venda). '
                              f'{"Estoque do Full = " + full.texto_da_conta(resumo, numero, caminho) if lido is not None else ""}')
    pagina['cartoes'] = [
        _cartao_de_ruptura(f'Ruptura · ritmo de {recente} dias', explicacao_recente, ritmo_r, estoque, lead, hoje),
        _cartao_de_ruptura(f'Ruptura · ritmo de {dias} dias', explicacao_periodo, ritmo_p, estoque, lead, hoje, destaque=True),
        cartao_vendas,
        cartao_estoque,
    ]

    # ---- a curva e o diagnóstico ----
    series = [{'classe': 'periodo', 'media': media, 'rotulo': f'Ritmo de {dias} dias'}]
    if not mesmo_ritmo and ritmo_r['media'] is not None and media is not None and abs(ritmo_r['media'] - media) > 1e-9:
        series.append({'classe': 'recente', 'media': ritmo_r['media'], 'rotulo': f'Ritmo de {recente} dias'})
    pagina['grafico'] = montar_grafico(estoque, lead, series, hoje)
    pagina['diagnostico'] = _diagnostico(estoque, lead, dias, recente, ritmo_p, ritmo_r, mesmo_ritmo, hoje, a_caminho_somado)


# ==================================================== a página ====================================================

# Função Objetivo: Junta os avisos da página e os da lista num só conjunto e diz como mostrar: com 2 ou mais avisos (e nenhum de erro) eles vão AGRUPADOS numa caixa recolhida de uma linha
# ("N avisos sobre os dados"), para não empurrar os cartões e a tabela para baixo; erro nunca fica escondido (aí cada aviso continua sendo uma faixa).
def _organizar_avisos(pagina):
    todos = list(pagina['avisos']) + (list(pagina['lista']['avisos']) if pagina['lista'] else [])
    pagina['avisos_todos'] = todos
    pagina['avisos_agrupar'] = len(todos) > 1 and not any(a['classe'] == 'erro' for a in todos)
    pagina['avisos_tem_atencao'] = any(a['classe'] == 'aviso' for a in todos)


# Função Objetivo: Tudo da tela a partir da query string. Sem SKU: a LISTA (ruptura_lista.montar_lista). Com SKU: o DETALHE de um item (_montar_detalhe). O ritmo (dias) e o lead time valem
# para os dois; o lead time sem digitar é o padrão provisório (calc.LEAD_TIME_PADRAO) e a tela avisa isso ao lado do campo.
def montar_pagina(parametros, base_url, hoje=None):
    hoje = hoje or datetime.now(FUSO).date()
    sku = (parametros.get('sku') or '').strip()
    maximo = (hoje - primeiro_dia_do_ml(hoje)).days   # o Mercado Livre guarda ~12 meses de pedidos
    pedido = _inteiro(parametros.get('dias'), 1, 3650)
    dias = min(pedido or calc.DIAS_PADRAO, maximo)
    lead_digitado = _inteiro(parametros.get('lead'), 0, 365)
    lead = calc.LEAD_TIME_PADRAO if lead_digitado is None else lead_digitado
    caminho = (parametros.get('caminho') or '').strip() == '1'   # "Considerar as unidades a caminho" (checkbox; desmarcado por padrão)
    comuns = {'dias': dias, 'lead': lead, 'recente': min(calc.DIAS_DO_RITMO_RECENTE, maximo), 'maximo': maximo, 'caminho': caminho}
    pagina = {
        'modo': 'detalhe' if sku else 'lista', 'url_ruptura': base_url, 'hoje': hoje, 'dias_valor': str(dias), 'lead_valor': str(lead), 'caminho': caminho,
        'lead_e_padrao': lead_digitado is None or lead_digitado == calc.LEAD_TIME_PADRAO,   # o formulário reenvia o "7" já preenchido: continua sendo o padrão provisório
        'avisos': [], 'lista': None, 'estado': 'lista',
        'atalhos': [{'dias': d, 'rotulo': str(d), 'ativo': d == dias} for d in ATALHOS_DE_DIAS] + [{'dias': maximo, 'rotulo': '1 ano', 'ativo': dias == maximo}],
        'maximo_de_dias': maximo,
    }
    if pedido and pedido > maximo:
        pagina['avisos'].append({'classe': 'info', 'texto': f'O Mercado Livre guarda cerca de 12 meses de pedidos: o ritmo usa {dias} dias (o máximo disponível).'})
    if sku:
        _montar_detalhe(parametros, base_url, hoje, comuns, pagina, sku)
    else:
        pagina['lista'] = montar_lista(parametros, base_url, hoje, comuns)
    _organizar_avisos(pagina)
    return pagina
