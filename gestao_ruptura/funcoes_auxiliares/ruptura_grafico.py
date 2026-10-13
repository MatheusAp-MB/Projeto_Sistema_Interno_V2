# gestao_ruptura/funcoes_auxiliares/ruptura_grafico.py
#
# Função Objetivo: Calcula a CURVA DE ESTOQUE da tela "Previsão de Ruptura de estoque": uma linha do estoque caindo para CADA ritmo de vendas (3, 7, 15 e 30 dias, mais o período digitado quando
# for outro), as zonas coloridas do fundo (antes do envio / chegar antes da ruptura / prazo até vender / depois da ruptura) do ritmo EM DESTAQUE, os marcadores "Enviar até" e "Ruptura", o ponto de pedido
# e os cartões de cada ritmo (ponto de pedido, "enviar até", "enviar já" ou "prazo vencido"). Serve aos dois mundos da tela (Envios Full e Fora do Full): só as palavras mudam (Enviar até x Pedir até, Com o envio
# x Com o pedido; ruptura_texto.palavras). Havendo uma quantidade para enviar (a do Sistema ou a digitada), desenha também a COBERTURA DA REMESSA:
# a linha que SOBE na chegada (hoje + lead time) e volta a cair no mesmo ritmo até a NOVA ruptura, com os marcadores "Chega" e "Nova ruptura". Aqui só se calcula a POSIÇÃO de cada peça e se escrevem os textos
# (inclusive a LEGENDA DIDÁTICA "Como ler este gráfico"); quem desenha é o template (SVG para as linhas e as zonas, HTML para os textos) e quem dá vida (ligar/desligar curvas, passar o mouse, zoom) é o script_ruptura.js.
#
# * [EXPLICAÇÃO] → POR QUE SVG "esticado" (preserveAspectRatio="none"): o layout da tela é "fluido na horizontal, rígido na vertical" (regra do Matheus, 12/10/2026): o gráfico tem ALTURA
#                  FIXA e usa a largura toda, abrindo ou fechando a barra lateral. As linhas acompanham a largura; os textos ficam em HTML por cima (se fossem SVG esticado, as letras
#                  sairiam deformadas).
# * [EXPLICAÇÃO] → O eixo horizontal do SVG é medido em DIAS a partir de hoje (viewBox "0 0 {horizonte} 100"): o zoom e o arrastar do script só trocam o viewBox, sem recalcular nenhuma linha.
#                  O eixo vertical é em % da altura e é FIXO: não muda ao ocultar curvas, trocar o destaque ou dar zoom (a escala olha para o estoque e para os pontos de pedido de TODOS
#                  os ritmos, não só do que está em destaque).
# * [EXPLICAÇÃO] → Os números dos textos saem daqui já como TEXTO ("12.34"): o Django formata número decimal com vírgula (pt-BR), e "x=12,34" quebraria o SVG. Os dados que o script usa vão
#                  em JSON (json_script), que sempre usa o ponto.
# * [EXPLICAÇÃO] → A linha é reta (o ritmo é uma média por dia, então o estoque cai em linha reta). As contas de ruptura, envio e ponto de pedido são as de ruptura_calculo.py, as mesmas
#                  dos cartões da tela: o gráfico não tem regra própria.
# * [EXPLICAÇÃO] → O DIA É UMA COLUNA (regra visual do Matheus, 12/10/2026: "o usuário olha e entende perfeitamente: vai acabar dia X"). O eixo horizontal é contínuo (a linha cruza o zero no meio
#                  de um dia, ex.: 10,8 dias), mas cada DATA ocupa a coluna que vai da meia-noite dela (número inteiro) até a meia-noite seguinte. O dia da ruptura é hoje + floor(dias de estoque) (a regra
#                  de ruptura_calculo.py), então a linha SEMPRE cruza o zero dentro da coluna da data da ruptura. Por isso o "Enviar até" e a "Ruptura" são FAIXAS da coluna do dia (e não um traço
#                  solto na posição exata), as divisas das zonas caem na meia-noite, e o nome de cada data do eixo fica CENTRADO na coluna dela.

from datetime import timedelta
from math import ceil, floor, log10

from gestao_ruptura.funcoes_auxiliares import ruptura_calculo as calc
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import data as _data_completa, em_dias as _em_dias, palavras, plural as _plural, un_dia as _un_dia

HORIZONTE_MINIMO = 14
HORIZONTE_MAXIMO = 730
MARGEM_DO_TOPO = 1.1
PASSOS_DO_EIXO_X = (1, 2, 5, 7, 10, 14, 15, 20, 30, 45, 60, 90, 120, 180, 365)
LINHA_DOS_MARCADORES_PX = 24   # cada marcador ocupa uma "linha" de texto no topo do gráfico (não se sobrepõem)
ZOOM_MINIMO_EM_DIAS = 4        # a menor janela que o zoom aceita
# * [EXPLICAÇÃO] → A COR de cada ritmo é FIXA (a mesma em qualquer produto e a cada visita) e evita as cores que já têm dono no gráfico (regra do Matheus, 13/10/2026: "cada elemento representa 1 única coisa"):
#                  verde = o cenário "enviando hoje" (linha da remessa, "Chega", "Nova ruptura"), vermelho = a ruptura, laranja e amarelo = as zonas do fundo, azul-marinho = o "Enviar até". O período digitado que
#                  não é um dos quatro usa a cor neutra "extra". As cores em si moram no CSS (--rup-c3, --rup-c7...).
COR_DO_RITMO = {3: 'c3', 7: 'c7', 15: 'c15', 30: 'c30'}
COR_DO_RITMO_AVULSO = 'extra'
COR_DA_REMESSA = 'sug'   # a linha da cobertura da remessa tem cor própria (verde: o cenário "enviando hoje", o estoque que SOBE com o envio)
ROTULO_DAS_ZONAS = {'antes': 'Antes d{do_envio}', 'ante': 'Chegar antes da ruptura', 'envio': 'Prazo até vender', 'pos': 'Depois da ruptura'}   # "{do_envio}" vira "o envio" ou "o pedido" (ruptura_texto.palavras)


def _c(valor):
    return f'{valor:.2f}'


def _numero(n):
    return f'{int(round(n)):,}'.replace(',', '.')


def _data_curta(dia, hoje):
    return dia.strftime('%d/%m' if dia.year == hoje.year else '%d/%m/%Y')


def _cor(dias):
    return COR_DO_RITMO.get(dias, COR_DO_RITMO_AVULSO)


def _passo_do_eixo_y(maximo):
    bruto = maximo / 4
    base = 10 ** floor(log10(bruto))
    for multiplo in (1, 2, 2.5, 5, 10):
        if multiplo * base >= bruto:
            return multiplo * base
    return 10 * base


# Função Objetivo: As zonas do fundo, em dias a partir de hoje, para o ritmo em destaque: [(classe, inicio, fim, atrasada)]. Todas as divisas caem na meia-noite de um dia (número inteiro), porque
# ruptura e "enviar até" são DIAS. Lendo de trás para a frente a partir da ruptura: o DIA da ruptura fica de fora das zonas (ganha a faixa vermelha própria, o marcador); os `lead` dias antes dele são
# o "prazo até vender" (laranja: enviando nesse trecho já não dá tempo; com o prazo vencido começa em hoje); os `ante` dias antes disso são o "chegar antes da ruptura" (amarelo: ainda dá tempo, mas a
# remessa chega menos de `ante` dias antes da ruptura: "enviar já"); tudo antes é "antes do envio" (sem cor: a data recomendada ainda não chegou); "pos" = os dias depois da ruptura (cinza).
# Estoque zerado = tudo "pos"; sem ruptura prevista (sem vendas) = tudo "antes".
def _zonas(estoque, lead, ante, t_ruptura, horizonte):
    if estoque <= 0:
        return [('pos', 0.0, float(horizonte), False)]
    if t_ruptura is None:
        return [('antes', 0.0, float(horizonte), False)]
    dia_ruptura = floor(t_ruptura)
    dia_limite = dia_ruptura - lead      # o último dia possível do envio
    dia_envio = dia_limite - ante        # a data recomendada ("Enviar até")
    zonas = []
    if dia_envio > 0:
        zonas.append(('antes', 0.0, float(min(dia_envio, horizonte)), False))
    if ante and dia_envio < horizonte and dia_limite > 0:
        zonas.append(('ante', float(max(0, dia_envio)), float(min(dia_limite, horizonte)), False))
    if lead and dia_limite < horizonte:
        zonas.append(('envio', float(max(0, dia_limite)), float(min(dia_ruptura, horizonte)), dia_limite < 0))
    if dia_ruptura + 1 < horizonte:
        zonas.append(('pos', float(dia_ruptura + 1), float(horizonte), False))
    return [z for z in zonas if z[2] - z[1] > 0]


# Função Objetivo: O cartão de UM ritmo (a linha da legenda que também liga/desliga a curva): nome, ritmo, ponto de pedido e "enviar até" / "prazo vencido", mais o texto completo para o
# "title". Sem dados (nenhum dia completo coletado nessa janela) o cartão fica no mesmo tamanho, dizendo isso.
def _periodo(s, estoque, lead, ante, hoje, foco, P):
    dias, media = s['dias'], s['media']
    base = {'id': f's{dias}', 'dias': dias, 'curto': _plural(dias, 'dia', 'dias'), 'cor': _cor(dias), 'foco': foco, 'url': s['url'], 'sem_dados': media is None}
    if media is None:
        return {**base, 'ritmo': 'sem dados', 'ritmo_numero': '', 'pedido_numero': '—', 'envio': 'Sem dados do período', 'envio_classe': 'neutro',
                'dica': f'Nenhum dia completo {"do último dia" if dias == 1 else f"dos últimos {dias} dias"} foi coletado: não dá para calcular este ritmo.'}
    pedido = calc.ponto_de_pedido(media, lead, ante)
    projecao = calc.projetar(estoque, media, hoje)
    envio = calc.envio(projecao, lead, hoje, ante)
    dica = [f'Ritmo {"do último dia" if dias == 1 else f"dos últimos {dias} dias"}: {_un_dia(media)} un/dia.']
    if pedido is not None:
        dica.append(f'Ponto de pedido (ritmo × (prazo + chegar antes)): {_numero(pedido)} un.')
    texto, classe = 'Informe o estoque', 'neutro'
    if projecao is not None:
        if projecao['situacao'] == 'zerado':
            texto, classe = 'Estoque zerado', 'vencido'
            dica.append('O estoque está zerado.')
        elif projecao['situacao'] == 'sem_vendas':
            texto = 'Sem vendas: não acaba'
            dica.append('Sem vendas nos dias completos desse período: nesse ritmo o estoque não acaba.')
        elif projecao['situacao'] == 'longe':
            texto, classe = 'Ruptura muito distante', 'ok'
            dica.append('Nesse ritmo o estoque dura mais de 10 anos.')
        else:
            dica.append(f'O estoque de {_numero(estoque)} un dura {_plural(projecao["dias"], "dia", "dias")}: ruptura em {_data_completa(projecao["data"])}.')
            if envio is None:
                texto = f'Ruptura {_data_curta(projecao["data"], hoje)}'
            elif envio['estado'] == 'vencido':
                texto, classe = 'Prazo vencido', 'vencido'
                dica.append(f'O prazo {P["do_envio"]} acabou em {_data_completa(envio["ultimo_dia"])}. {P["gerundio"].capitalize()} hoje, o produto só fica disponível em {_data_completa(envio["chegada"])}'
                            f' e vão faltar {_plural(envio["faltam_dias"], "dia", "dias")} de estoque.')
            elif envio['estado'] == 'ja':
                texto, classe = P['enviar_ja'], 'atencao'
                sobra = envio['sobra_na_chegada']
                dica.append(f'A data recomendada ({_data_completa(envio["enviar_ate"])}) já passou, mas ainda dá tempo: {P["gerundio"]} hoje o produto chega em {_data_completa(envio["chegada"])}, '
                            f'{"no próprio dia da ruptura" if sobra == 0 else _plural(sobra, "dia", "dias") + " antes da ruptura"} (o desejado é chegar {_plural(ante, "dia", "dias")} antes). O último dia possível é {_data_completa(envio["ultimo_dia"])}.')
            else:
                texto = f'{P["enviar_ate"]} hoje' if envio['em_dias'] == 0 else f'{P["enviar_ate"]} {_data_curta(envio["enviar_ate"], hoje)}'
                classe = 'atencao' if envio['estado'] == 'hoje' else 'ok'
                dica.append(f'{P["enviar_ate"]} {_data_completa(envio["enviar_ate"])} ({_em_dias(envio["em_dias"])}), para chegar {_plural(ante, "dia", "dias")} antes da ruptura.')
    return {**base, 'ritmo': f'{_un_dia(media)} un/dia', 'ritmo_numero': _un_dia(media), 'pedido_numero': _numero(pedido) if pedido is not None else '—',
            'envio': texto, 'envio_classe': classe, 'dica': ' '.join(dica)}


# Função Objetivo: O cartão da COBERTURA DA REMESSA (a linha verde), no mesmo molde dos cartões de ritmo: liga/desliga a linha, diz a quantidade, quando chega e quando vem a nova ruptura. `com` vem de
# ruptura_calculo.com_envio. A cor da última linha acompanha o diagnóstico: vermelho = falta produto antes de chegar; laranja = a quantidade acrescenta menos que a folga desejada.
def _cartao_da_remessa(com, lead, folga, hoje, P):
    chegada, nova = hoje + timedelta(days=lead), hoje + timedelta(days=com['dia_nova_ruptura'])
    dada = floor(round(com['folga_dada'], 6))
    classe = 'vencido' if com['faltam'] > 0 else ('ok' if dada >= folga else 'atencao')
    dica = [f'Cobertura de estoque {P["da_remessa"]} ({com.get("fonte", "quantidade")}): {P["gerundio"]} {_numero(com["qtd"])} un hoje, {P["a_remessa"]} chega em {_data_completa(chegada)} (prazo de {_plural(lead, "dia", "dias")}).',
            f'Nesse dia o estoque terá cerca de {_numero(com["apos"])} un ({_numero(ceil(com["antes"]))} que sobram + {_numero(com["qtd"])} {P["da_remessa"]}) e volta a cair no mesmo ritmo até a nova ruptura, em {_data_completa(nova)}.',
            f'A quantidade acrescenta {_plural(dada, "dia", "dias")} de estoque (a folga desejada é de {_plural(folga, "dia", "dias")}).']
    if com['faltam'] > 0:
        dica.append(f'Antes da chegada o estoque acaba: vão faltar cerca de {_plural(com["faltam"], "dia", "dias")}.')
    return {'id': 'sug', 'cor': COR_DA_REMESSA, 'curto': P['com'], 'quantidade': f'{_numero(com["qtd"])}', 'chega': f'Chega {_data_curta(chegada, hoje)}', 'nova': f'Nova ruptura {_data_curta(nova, hoje)}',
            'classe': classe, 'dica': ' '.join(dica)}


# Função Objetivo: O nome de uma zona do fundo, com os dias entre parênteses quando ela tem ("Prazo até vender (15 dias)"). Serve à legenda; "{do_envio}" vira "o envio" ou "o pedido" (ruptura_texto.palavras).
def _rotulo_da_zona(classe, P, lead, ante):
    dias = {'envio': lead, 'ante': ante}.get(classe)
    return ROTULO_DAS_ZONAS[classe].format(do_envio=P['o_envio']) + (f' ({_plural(dias, "dia", "dias")})' if dias else '')


# Função Objetivo: A LEGENDA DIDÁTICA do gráfico (o painel "Como ler este gráfico"): para cada peça DESENHADA agora, uma amostra (a mesma cor ou linha do gráfico) e uma explicação em linguagem simples, com os
# números DESTE produto (datas, dias, quantidades). Só entra o que está no desenho: uma zona sem dias, uma data fora do horizonte ou a linha da remessa sem quantidade não aparecem. Três grupos: o FUNDO (as fases, contadas
# de trás para a frente a partir da ruptura), as DATAS (uma coluna por dia) e as LINHAS (os ritmos, a remessa e o ponto de pedido). As cores em si moram no CSS (as amostras usam as mesmas variáveis do desenho).
# * [EXPLICAÇÃO] → Os textos NÃO citam o nome da cor ("o azul", "o verde"): quem mostra a cor é a amostra. Assim, trocar uma cor no CSS não deixa a legenda mentindo.
def _legenda(P, hoje, estoque, lead, ante, destaque, media_foco, t_ruptura, zonas, marcadores, outros, ponto_de_pedido, pedido, com, folga):
    def d(dia):
        return _data_curta(hoje + timedelta(days=dia), hoje)

    verbo, gerundio, a_remessa = P['verbo'], P['gerundio'], P['a_remessa']
    ritmo = f'{_un_dia(media_foco)} un/dia'
    foco_txt = _plural(destaque, 'dia', 'dias')
    lead_txt, ante_txt = _plural(lead, 'dia', 'dias'), _plural(ante, 'dia', 'dias')
    classes = {z['classe']: z for z in zonas}
    marc = {m['classe']: m for m in marcadores}
    dia_rup = floor(t_ruptura) if t_ruptura is not None else None
    dia_limite = dia_rup - lead if dia_rup is not None else None      # o último dia possível do envio
    dia_recomendado = dia_limite - ante if dia_limite is not None else None
    estoque_txt = _numero(estoque)

    def item(amostra, titulo, texto, cor=''):
        return {'amostra': amostra, 'titulo': titulo, 'texto': texto, 'cor': cor}

    # ---- o fundo ----
    fundo = []
    if 'antes' in classes:
        fundo.append(item('zona-antes', _rotulo_da_zona('antes', P, lead, ante),
                          f'Sem cor: ainda não é hora de {verbo}. Todos os dias daqui vêm antes da data recomendada ({P["enviar_ate"]} {d(dia_recomendado)}).' if dia_recomendado is not None
                          else f'Neste ritmo o estoque não acaba, então não há data para {verbo}: o gráfico inteiro fica sem cor.'))
    if 'ante' in classes:
        if dia_recomendado is not None and dia_recomendado < 0:
            texto = (f'A folga de segurança ({ante_txt} antes da ruptura). A data recomendada ({d(dia_recomendado)}) já passou: {gerundio} hoje, {a_remessa} ainda chega antes da ruptura, mas com menos folga.')
        else:
            texto = (f'A folga de segurança: o ideal é {a_remessa} chegar {ante_txt} antes da ruptura. {gerundio.capitalize()} no começo desta faixa ({d(dia_recomendado)}) você garante essa folga; mais tarde ela vai encolhendo.')
        fundo.append(item('zona-ante', _rotulo_da_zona('ante', P, lead, ante), texto))
    if 'envio' in classes:
        if classes['envio']['atrasada']:
            texto = f'O tempo que o produto leva para chegar ({lead_txt}). Cor mais forte: você já está nela. {gerundio.capitalize()} hoje, {a_remessa} chega depois da ruptura e vai faltar estoque.'
        else:
            texto = (f'O tempo que o produto leva para chegar ({lead_txt}). {gerundio.capitalize()} no começo desta faixa ({d(dia_limite)}, o último dia possível), {a_remessa} chega no dia da ruptura; depois disso, chega tarde.')
        fundo.append(item('zona-envio', _rotulo_da_zona('envio', P, lead, ante), texto))
    if 'pos' in classes:
        fundo.append(item('zona-pos', _rotulo_da_zona('pos', P, lead, ante),
                          'O estoque está zerado: todo o gráfico fica nesta faixa.' if estoque <= 0
                          else f'O estoque já acabou (no ritmo de {foco_txt}): sem produto para vender, a menos que {a_remessa} chegue antes.'))

    # ---- as datas ----
    datas = []
    if 'enviar' in marc:
        dia = marc['enviar']['dia']
        partes = ([f'prazo ({lead_txt})'] if lead else []) + ([f'chegar antes ({ante_txt})'] if ante else [])
        conta = f'ruptura ({d(dia_rup)}) − ' + ' − '.join(partes)
        chegada = f'{ante_txt} antes de o estoque acabar' if ante else 'a tempo, no dia em que o estoque acabaria'
        datas.append(item('dia-enviar', f'{P["enviar_ate"]} {d(dia)}' + (' (hoje)' if dia == 0 else ''),
                          f'A data recomendada para {verbo}: {conta}. {gerundio.capitalize()} até aqui, {a_remessa} chega {chegada}.'))
    if 'ruptura' in marc:
        dia = marc['ruptura']['dia']
        datas.append(item('dia-ruptura', f'Ruptura {d(dia)}',
                          f'O dia em que o estoque de {estoque_txt} un acaba: a {ritmo} (ritmo de {foco_txt}) ele dura {_plural(dia, "dia inteiro", "dias inteiros")}. A linha do estoque chega a zero nesta coluna.'))
    if com and 'chega' in marc:
        datas.append(item('dia-chega', f'Chega {d(marc["chega"]["dia"])}',
                          f'Se você {verbo} {_numero(com["qtd"])} un HOJE, {a_remessa} chega nesta data (hoje + {lead_txt} de prazo) e o estoque sobe.'))
    if com and 'nova' in marc:
        dada = floor(round(com['folga_dada'], 6))
        datas.append(item('dia-nova', f'Nova ruptura {d(marc["nova"]["dia"])}',
                          f'{a_remessa.capitalize()} acrescenta {_plural(dada, "dia", "dias")} de estoque, e ele volta a acabar nesta data.' + (f' A folga desejada é de {_plural(folga, "dia", "dias")}.' if folga else '')))
    sub_datas = 'Cada data é uma coluna inteira (o dia vai da linha da esquerda até a da direita).'
    if com:
        sub_datas += f' “Chega” e “Nova ruptura” têm a cor da linha “{P["com"]}”: são o mesmo cenário, o de {verbo} hoje.'

    # ---- as linhas ----
    linhas = [item('linha', f'Linha grossa · ritmo de {foco_txt}',
                   f'O estoque de hoje ({estoque_txt} un) caindo {ritmo}: é o ritmo em destaque, o que define o fundo, as datas e o ponto de pedido. Para trocar, clique no cartão de outro ritmo.', _cor(destaque))]
    if outros:
        linhas.append(item('linha-fina', 'Linhas finas e tracejadas · outros ritmos',
                           'Cada um na cor do seu cartão (embaixo do gráfico, onde também se liga e desliga). O ponto marca onde a linha chega a zero.', _cor(outros[0]['dias'])))
    if com:
        linhas.append(item('linha', P['com'],
                           f'O que acontece se você {verbo} {_numero(com["qtd"])} un hoje: o estoque sobe quando {a_remessa} chega e volta a cair até a nova ruptura. Liga e desliga no cartão “{P["com"]}”.', COR_DA_REMESSA))
    if ponto_de_pedido and pedido:
        linhas.append(item('pedido', f'Ponto de pedido · {_numero(pedido)} un',
                           f'O estoque em que chegou a hora de {verbo}: ritmo × (prazo + chegar antes) = {_un_dia(media_foco)} × ({lead} + {ante}). Quando a linha do estoque cai até ele, é a hora.'))

    intro = (f'Leia da esquerda para a direita: HOJE é a primeira coluna e, a cada dia, o estoque cai conforme você vende (cada coluna é um dia). Regra deste gráfico: cada cor e cada linha significa uma única coisa. '
             f'O fundo, as datas e a linha grossa valem para o ritmo em destaque ({foco_txt}, {ritmo}).')
    grupos = [{'titulo': 'O fundo: as fases até a ruptura', 'sub': f'Contadas de trás para a frente, a partir do dia da ruptura, no ritmo de {foco_txt}.', 'itens': fundo},
              {'titulo': 'As datas: uma coluna por dia', 'sub': sub_datas, 'itens': datas},
              {'titulo': 'As linhas e o ponto de pedido', 'sub': 'A altura é o estoque em unidades (escala à esquerda); a linha cai porque você vende todo dia.', 'itens': linhas}]
    return {'intro': intro, 'grupos': [g for g in grupos if g['itens']]}


# Função Objetivo: O gráfico pronto para o template, ou None quando não há o que desenhar (sem estoque, ou o ritmo em destaque sem dados). `series` = lista de
# {'dias': N, 'media': un/dia ou None, 'url': endereço que põe esse ritmo em destaque}; `destaque` = os dias do ritmo em destaque (o período escolhido na tela); `com` = o que acontece com o estoque
# se a quantidade escolhida for enviada hoje (ruptura_calculo.com_envio; None = sem quantidade, sem linha da remessa); `ante` = quantos dias antes da ruptura o envio deve chegar (a zona amarela e o "Enviar até");
# `folga` = os dias de estoque que o envio deve acrescentar (só para a cor do cartão da remessa); `mundo` = 'full' | 'fora' (só as palavras mudam).
def montar_grafico(estoque, lead, ante, series, destaque, hoje, com=None, folga=0, mundo='full'):
    P = palavras(mundo)
    series = sorted(series, key=lambda s: s['dias'])
    foco = next((s for s in series if s['dias'] == destaque), None)
    if estoque is None or foco is None or foco['media'] is None:
        return None
    com_ritmo = [s for s in series if s['media'] is not None]

    quedas = [estoque / s['media'] for s in com_ritmo if estoque > 0 and s['media'] > 0]
    base = max(quedas) if quedas else 30
    if lead:
        base = max(base, (lead + ante) * 1.3)
    if com:
        base = max(base, com['t_zero'])   # a nova ruptura (depois da remessa) também precisa caber no gráfico
    horizonte = min(HORIZONTE_MAXIMO, max(HORIZONTE_MINIMO, ceil(base * 1.12)))

    pedidos = {s['dias']: calc.ponto_de_pedido(s['media'], lead, ante) for s in com_ritmo}
    y_max = max(estoque, max((p for p in pedidos.values() if p), default=0), com['apos'] if com else 0, 10) * MARGEM_DO_TOPO

    def x(t):
        return t / horizonte * 100

    def y(valor):
        return 100 - valor / y_max * 100

    # ---- as linhas do estoque (uma por ritmo; a do destaque por último, para ficar por cima das outras) ----
    linhas = []
    for s in com_ritmo:
        media = s['media']
        pontos = [(0.0, estoque)]
        if estoque > 0 and media > 0:
            t0 = estoque / media
            pontos += [(t0, 0), (float(horizonte), 0)] if t0 < horizonte else [(float(horizonte), estoque - media * horizonte)]
        else:
            pontos.append((float(horizonte), max(estoque, 0)))
        linhas.append({'id': f's{s["dias"]}', 'cor': _cor(s['dias']), 'foco': s['dias'] == destaque, 'pontos': ' '.join(f'{_c(t)},{_c(y(v))}' for t, v in pontos)})
    linhas.sort(key=lambda linha: linha['foco'])

    # ---- o ritmo em destaque: zonas, "Enviar até" e "Ruptura" ----
    media_foco = foco['media']
    t_ruptura = estoque / media_foco if estoque > 0 and media_foco > 0 else None
    t_envio = t_ruptura - lead - ante if (t_ruptura is not None and (lead or ante)) else None   # a data RECOMENDADA (ruptura − prazo − chegar antes)
    zonas = [{'classe': c, 'inicio': _c(i), 'largura': _c(f - i), 'atrasada': atrasada} for c, i, f, atrasada in _zonas(estoque, lead, ante, t_ruptura, horizonte)]

    marcadores = []

    def marcador(dia, classe, rotulo, linha, serie=''):
        # * [EXPLICAÇÃO] → O marcador é a FAIXA da coluna do dia (de `dia` até `dia + 1`); o texto fica ao lado da faixa, do lado onde há espaço (esq = termina na borda esquerda da faixa; dir = começa na direita).
        #                  `serie` = a curva a que o marcador pertence (os da remessa ligam e desligam junto com a linha verde).
        lado = 'esq' if x(dia) > 55 else 'dir'
        marcadores.append({'dia': dia, 'classe': classe, 'rotulo': rotulo, 'topo': linha * LINHA_DOS_MARCADORES_PX + 6, 'lado': lado, 'x': _c(x(dia if lado == 'esq' else dia + 1)), 'serie': serie})

    dia_envio = dia_ruptura = None
    if t_envio is not None and 0 <= t_envio < horizonte:
        dia_envio = floor(t_envio)
        marcador(dia_envio, 'enviar', f'{P["enviar_ate"]} {_data_curta(hoje + timedelta(days=dia_envio), hoje)}', 0)
    if t_ruptura is not None and t_ruptura < horizonte:
        dia_ruptura = floor(t_ruptura)
        marcador(dia_ruptura, 'ruptura', f'Ruptura {_data_curta(hoje + timedelta(days=dia_ruptura), hoje)}', 1)
    truncado = t_ruptura is not None and t_ruptura >= horizonte

    # ---- a cobertura da remessa (a linha que SOBE na chegada): só havendo quantidade. Antes da chegada ela é igual à curva do ritmo em destaque (por isso só se desenha daqui em diante) ----
    remessa = None
    if com:
        chegada = float(lead)
        pontos_r = [(chegada, com['antes']), (chegada, com['apos'])]
        if com['t_zero'] < horizonte:
            pontos_r += [(com['t_zero'], 0), (float(horizonte), 0)]
        else:
            pontos_r.append((float(horizonte), com['apos'] - media_foco * (horizonte - chegada)))
        remessa = {'id': 'sug', 'cor': COR_DA_REMESSA, 'pontos': ' '.join(f'{_c(t)},{_c(y(v))}' for t, v in pontos_r)}
        if lead < horizonte:
            marcador(lead, 'chega', f'Chega {_data_curta(hoje + timedelta(days=lead), hoje)}', 2, 'sug')
        if com['t_zero'] < horizonte:
            marcador(com['dia_nova_ruptura'], 'nova', f'Nova ruptura {_data_curta(hoje + timedelta(days=com["dia_nova_ruptura"]), hoje)}', 3, 'sug')

    # ---- os outros ritmos: só um pontinho onde a linha encosta no zero (o detalhe vem no passar do mouse e no cartão do ritmo) ----
    pontos_de_ruptura = []
    for s in com_ritmo:
        if s['dias'] == destaque or not (estoque > 0 and s['media'] > 0):
            continue
        t = estoque / s['media']
        if t < horizonte:
            pontos_de_ruptura.append({'id': f's{s["dias"]}', 'cor': _cor(s['dias']), 't': _c(t), 'x': _c(x(t)),
                                      'rotulo': f'Ruptura {_data_curta(hoje + timedelta(days=floor(t)), hoje)} no ritmo de {_plural(s["dias"], "dia", "dias")}'})

    ponto_de_pedido = None
    pedido = pedidos.get(destaque)
    if pedido and 0 < pedido <= y_max:
        # * [EXPLICAÇÃO] → O rótulo fica no canto DIREITO (o esquerdo é onde caem os marcadores "Enviar até"/"Ruptura"); em cima da linha, ou embaixo dela quando a linha está no topo do gráfico.
        ponto_de_pedido = {'y': _c(y(pedido)), 'rotulo': f'Ponto de pedido: {_numero(pedido)} un', 'abaixo': y(pedido) < 30}

    # ---- os eixos ----
    passo_y = _passo_do_eixo_y(y_max)
    grades_y, valor = [], 0.0
    while valor <= y_max:
        grades_y.append({'y': _c(y(valor)), 'rotulo': _numero(valor)})
        valor += passo_y
    passo_x = next((p for p in PASSOS_DO_EIXO_X if horizonte / p <= 8), 365)
    ticks_x = [{'t': t, 'x_meio': _c(x(t + 0.5)), 'hoje': t == 0, 'rotulo': 'HOJE' if t == 0 else _data_curta(hoje + timedelta(days=t), hoje)} for t in range(0, horizonte, passo_x)]

    # ---- a legenda didática ("Como ler este gráfico"): só o que está desenhado ----
    legenda = _legenda(P, hoje, estoque, lead, ante, destaque, media_foco, t_ruptura, zonas, marcadores, [s for s in com_ritmo if s['dias'] != destaque], ponto_de_pedido, pedido, com, folga)

    periodos = [_periodo(s, estoque, lead, ante, hoje, s['dias'] == destaque, P) for s in series]
    cartao_da_remessa = _cartao_da_remessa(com, lead, folga, hoje, P) if com else None
    dados = {
        'hoje': hoje.isoformat(), 'horizonte': horizonte, 'estoque': estoque, 'yMax': round(y_max, 4), 'zoomMinimo': ZOOM_MINIMO_EM_DIAS, 'lead': lead, 'foco': f's{destaque}',
        'ruptura': None if t_ruptura is None else round(t_ruptura, 4), 'enviar': None if (t_envio is None or t_envio < 0) else round(t_envio, 4), 'pedido': pedido if pedido else None,
        'rupturaDia': dia_ruptura, 'enviarDia': dia_envio,
        'sug': None if not com else {'id': 'sug', 'rotulo': P['com'], 'cor': COR_DA_REMESSA, 'media': round(media_foco, 6), 'chega': lead, 'antes': round(com['antes'], 4), 'depois': round(com['apos'], 4),
                                     'tZero': round(com['t_zero'], 4), 'diaZero': com['dia_nova_ruptura'], 'qtd': com['qtd']},
        'series': [{'id': f's{s["dias"]}', 'dias': s['dias'], 'rotulo': _plural(s['dias'], 'dia', 'dias'), 'media': round(s['media'], 6), 'cor': _cor(s['dias']),
                    'diaRuptura': floor(estoque / s['media']) if estoque > 0 and s['media'] > 0 else None} for s in com_ritmo],
    }
    descricao = (f'Curvas do estoque de {_numero(estoque)} unidades nos próximos {horizonte} dias, uma para cada ritmo de vendas ({", ".join(str(s["dias"]) for s in com_ritmo)} dias); '
                 f'em destaque, o ritmo de {_plural(destaque, "dia", "dias")}.')
    nota = f'A ruptura no ritmo de {_plural(destaque, "dia", "dias")} fica além do que o gráfico mostra ({horizonte} dias).' if truncado else ''
    return {'linhas': linhas, 'zonas': zonas, 'legenda': legenda, 'marcadores': marcadores, 'pontos_de_ruptura': pontos_de_ruptura, 'ponto_de_pedido': ponto_de_pedido,
            'grades_y': grades_y, 'ticks_x': ticks_x, 'periodos': periodos, 'remessa': remessa, 'cartao_da_remessa': cartao_da_remessa, 'n_cartoes': len(periodos) + (1 if com else 0), 'dados': dados, 'descricao': descricao, 'horizonte': horizonte, 'viewbox': f'0 0 {horizonte} 100',
            'truncado': truncado, 'nota': nota}
