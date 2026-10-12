# gestao_ruptura/funcoes_auxiliares/ruptura_grafico.py
#
# Função Objetivo: Calcula a CURVA DE ESTOQUE da tela "Previsão de Ruptura de estoque": uma linha do estoque caindo para CADA ritmo de vendas (3, 7, 15 e 30 dias, mais o período digitado quando
# for outro), as zonas coloridas do fundo (antes do envio / margem de segurança / tempo de envio / depois da ruptura) do ritmo EM DESTAQUE, os marcadores "Enviar até" e "Ruptura", o ponto de pedido
# e os cartões de cada ritmo (ponto de pedido, "enviar até", "enviar já" ou "prazo vencido"). Havendo uma quantidade para enviar (a do Sistema ou a digitada), desenha também a COBERTURA DA REMESSA:
# a linha que SOBE na chegada (hoje + lead time) e volta a cair no mesmo ritmo até a NOVA ruptura, com os marcadores "Chega" e "Nova ruptura". Aqui só se calcula a POSIÇÃO de cada peça e se escrevem os textos; quem desenha é o template (SVG para as
# linhas e as zonas, HTML para os textos) e quem dá vida (ligar/desligar curvas, passar o mouse, zoom) é o script_ruptura.js.
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
from gestao_ruptura.funcoes_auxiliares.ruptura_texto import data as _data_completa, em_dias as _em_dias, plural as _plural, un_dia as _un_dia

HORIZONTE_MINIMO = 14
HORIZONTE_MAXIMO = 730
MARGEM_DO_TOPO = 1.1
PASSOS_DO_EIXO_X = (1, 2, 5, 7, 10, 14, 15, 20, 30, 45, 60, 90, 120, 180, 365)
LINHA_DOS_MARCADORES_PX = 24   # cada marcador ocupa uma "linha" de texto no topo do gráfico (não se sobrepõem)
ZOOM_MINIMO_EM_DIAS = 4        # a menor janela que o zoom aceita
# * [EXPLICAÇÃO] → A COR de cada ritmo é FIXA (a mesma em qualquer produto e a cada visita) e evita verde, laranja e vermelho, que já significam "enviar" e "ruptura". O período digitado que
#                  não é um dos quatro usa a cor neutra "extra". As cores em si moram no CSS (--rup-c3, --rup-c7...).
COR_DO_RITMO = {3: 'c3', 7: 'c7', 15: 'c15', 30: 'c30'}
COR_DO_RITMO_AVULSO = 'extra'
COR_DA_REMESSA = 'sug'   # a linha da cobertura da remessa tem cor própria (verde: o estoque que SOBE com o envio)
ROTULO_DAS_ZONAS = {'antes': 'Antes do envio', 'folga': 'Margem de segurança', 'envio': 'Tempo de envio', 'pos': 'Depois da ruptura'}


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
# o "tempo de envio" (laranja: enviando nesse trecho já não dá tempo; com o prazo vencido começa em hoje); os `folga` dias antes disso são a "margem de segurança" (amarelo: ainda dá tempo, mas a
# remessa chega com menos margem que a desejada: "enviar já"); tudo antes é "antes do envio" (verde: a data recomendada ainda não chegou); "pos" = os dias depois da ruptura.
# Estoque zerado = tudo "pos"; sem ruptura prevista (sem vendas) = tudo "antes".
def _zonas(estoque, lead, folga, t_ruptura, horizonte):
    if estoque <= 0:
        return [('pos', 0.0, float(horizonte), False)]
    if t_ruptura is None:
        return [('antes', 0.0, float(horizonte), False)]
    dia_ruptura = floor(t_ruptura)
    dia_limite = dia_ruptura - lead      # o último dia possível do envio
    dia_envio = dia_limite - folga       # a data recomendada ("Enviar até")
    zonas = []
    if dia_envio > 0:
        zonas.append(('antes', 0.0, float(min(dia_envio, horizonte)), False))
    if folga and dia_envio < horizonte and dia_limite > 0:
        zonas.append(('folga', float(max(0, dia_envio)), float(min(dia_limite, horizonte)), False))
    if lead and dia_limite < horizonte:
        zonas.append(('envio', float(max(0, dia_limite)), float(min(dia_ruptura, horizonte)), dia_limite < 0))
    if dia_ruptura + 1 < horizonte:
        zonas.append(('pos', float(dia_ruptura + 1), float(horizonte), False))
    return [z for z in zonas if z[2] - z[1] > 0]


# Função Objetivo: O cartão de UM ritmo (a linha da legenda que também liga/desliga a curva): nome, ritmo, ponto de pedido e "enviar até" / "prazo vencido", mais o texto completo para o
# "title". Sem dados (nenhum dia completo coletado nessa janela) o cartão fica no mesmo tamanho, dizendo isso.
def _periodo(s, estoque, lead, folga, hoje, foco):
    dias, media = s['dias'], s['media']
    base = {'id': f's{dias}', 'dias': dias, 'curto': _plural(dias, 'dia', 'dias'), 'cor': _cor(dias), 'foco': foco, 'url': s['url'], 'sem_dados': media is None}
    if media is None:
        return {**base, 'ritmo': 'sem dados', 'ritmo_numero': '', 'pedido_numero': '—', 'envio': 'Sem dados do período', 'envio_classe': 'neutro',
                'dica': f'Nenhum dia completo {"do último dia" if dias == 1 else f"dos últimos {dias} dias"} foi coletado: não dá para calcular este ritmo.'}
    pedido = calc.ponto_de_pedido(media, lead, folga)
    projecao = calc.projetar(estoque, media, hoje)
    envio = calc.envio(projecao, lead, hoje, folga)
    dica = [f'Ritmo {"do último dia" if dias == 1 else f"dos últimos {dias} dias"}: {_un_dia(media)} un/dia.']
    if pedido is not None:
        dica.append(f'Ponto de pedido (ritmo × (lead time + margem de segurança)): {_numero(pedido)} un.')
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
                dica.append(f'O prazo para enviar acabou em {_data_completa(envio["ultimo_dia"])}. Enviando hoje, o produto só fica disponível em {_data_completa(envio["chegada"])}'
                            f' e vão faltar {_plural(envio["faltam_dias"], "dia", "dias")} de estoque.')
            elif envio['estado'] == 'ja':
                texto, classe = 'Enviar já', 'atencao'
                dica.append(f'A data recomendada ({_data_completa(envio["enviar_ate"])}) já passou, mas ainda dá tempo: enviando hoje o produto chega em {_data_completa(envio["chegada"])} com '
                            f'{_plural(envio["folga_na_chegada"], "dia", "dias")} de estoque sobrando (a margem de segurança é de {_plural(folga, "dia", "dias")}). O último dia possível é {_data_completa(envio["ultimo_dia"])}.')
            else:
                texto = 'Enviar até hoje' if envio['em_dias'] == 0 else f'Enviar até {_data_curta(envio["enviar_ate"], hoje)}'
                classe = 'atencao' if envio['estado'] == 'hoje' else 'ok'
                dica.append(f'Enviar até {_data_completa(envio["enviar_ate"])} ({_em_dias(envio["em_dias"])}), com margem de segurança de {_plural(folga, "dia", "dias")}.')
    return {**base, 'ritmo': f'{_un_dia(media)} un/dia', 'ritmo_numero': _un_dia(media), 'pedido_numero': _numero(pedido) if pedido is not None else '—',
            'envio': texto, 'envio_classe': classe, 'dica': ' '.join(dica)}


# Função Objetivo: O cartão da COBERTURA DA REMESSA (a linha verde), no mesmo molde dos cartões de ritmo: liga/desliga a linha, diz a quantidade, quando chega e quando vem a nova ruptura. `com` vem de
# ruptura_calculo.com_envio. A cor da última linha acompanha o diagnóstico: vermelho = falta produto antes de chegar; laranja = não atinge a meta do Sistema (folga + cobre).
def _cartao_da_remessa(com, lead, folga, cobre, hoje):
    chegada, nova = hoje + timedelta(days=lead), hoje + timedelta(days=com['dia_nova_ruptura'])
    meta, dias_apos = folga + cobre, floor(com['dias_apos'])
    classe = 'vencido' if com['faltam'] > 0 else ('ok' if dias_apos >= meta else 'atencao')
    dica = [f'Cobertura de estoque da {com.get("fonte", "remessa")}: enviando {_numero(com["qtd"])} un hoje, ela chega em {_data_completa(chegada)} (lead time de {_plural(lead, "dia", "dias")}).',
            f'Nesse dia o estoque terá cerca de {_numero(com["apos"])} un ({_numero(ceil(com["antes"]))} que sobram + {_numero(com["qtd"])} da remessa) e volta a cair no mesmo ritmo até a nova ruptura, em {_data_completa(nova)}.']
    if com['faltam'] > 0:
        dica.append(f'Antes da chegada o estoque acaba: vão faltar cerca de {_plural(com["faltam"], "dia", "dias")}.')
    return {'id': 'sug', 'cor': COR_DA_REMESSA, 'curto': 'Com o envio', 'quantidade': f'{_numero(com["qtd"])}', 'chega': f'Chega {_data_curta(chegada, hoje)}', 'nova': f'Nova ruptura {_data_curta(nova, hoje)}',
            'classe': classe, 'dica': ' '.join(dica)}


# Função Objetivo: O gráfico pronto para o template, ou None quando não há o que desenhar (sem estoque, ou o ritmo em destaque sem dados). `series` = lista de
# {'dias': N, 'media': un/dia ou None, 'url': endereço que põe esse ritmo em destaque}; `destaque` = os dias do ritmo em destaque (o período escolhido na tela); `com` = o que acontece com o estoque
# se a quantidade escolhida for enviada hoje (ruptura_calculo.com_envio; None = sem quantidade, sem linha da remessa); `cobre` = os dias que cada remessa cobre (só para o cartão da remessa).
def montar_grafico(estoque, lead, folga, series, destaque, hoje, com=None, cobre=0):
    series = sorted(series, key=lambda s: s['dias'])
    foco = next((s for s in series if s['dias'] == destaque), None)
    if estoque is None or foco is None or foco['media'] is None:
        return None
    com_ritmo = [s for s in series if s['media'] is not None]

    quedas = [estoque / s['media'] for s in com_ritmo if estoque > 0 and s['media'] > 0]
    base = max(quedas) if quedas else 30
    if lead:
        base = max(base, (lead + folga) * 1.3)
    if com:
        base = max(base, com['t_zero'])   # a nova ruptura (depois da remessa) também precisa caber no gráfico
    horizonte = min(HORIZONTE_MAXIMO, max(HORIZONTE_MINIMO, ceil(base * 1.12)))

    pedidos = {s['dias']: calc.ponto_de_pedido(s['media'], lead, folga) for s in com_ritmo}
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
    t_envio = t_ruptura - lead - folga if (t_ruptura is not None and (lead or folga)) else None   # a data RECOMENDADA (ruptura − lead time − margem de segurança)
    zonas = [{'classe': c, 'inicio': _c(i), 'largura': _c(f - i), 'atrasada': atrasada} for c, i, f, atrasada in _zonas(estoque, lead, folga, t_ruptura, horizonte)]
    dias_da_zona = {'envio': lead, 'folga': folga}
    zonas_legenda = [{'classe': z['classe'], 'rotulo': ROTULO_DAS_ZONAS[z['classe']] + (f' ({_plural(dias_da_zona[z["classe"]], "dia", "dias")})' if dias_da_zona.get(z['classe']) else '')} for z in zonas]

    marcadores = []

    def marcador(dia, classe, rotulo, linha, serie=''):
        # * [EXPLICAÇÃO] → O marcador é a FAIXA da coluna do dia (de `dia` até `dia + 1`); o texto fica ao lado da faixa, do lado onde há espaço (esq = termina na borda esquerda da faixa; dir = começa na direita).
        #                  `serie` = a curva a que o marcador pertence (os da remessa ligam e desligam junto com a linha verde).
        lado = 'esq' if x(dia) > 55 else 'dir'
        marcadores.append({'dia': dia, 'classe': classe, 'rotulo': rotulo, 'topo': linha * LINHA_DOS_MARCADORES_PX + 6, 'lado': lado, 'x': _c(x(dia if lado == 'esq' else dia + 1)), 'serie': serie})

    dia_envio = dia_ruptura = None
    if t_envio is not None and 0 <= t_envio < horizonte:
        dia_envio = floor(t_envio)
        marcador(dia_envio, 'enviar', f'Enviar até {_data_curta(hoje + timedelta(days=dia_envio), hoje)}', 0)
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

    periodos = [_periodo(s, estoque, lead, folga, hoje, s['dias'] == destaque) for s in series]
    cartao_da_remessa = _cartao_da_remessa(com, lead, folga, cobre, hoje) if com else None
    dados = {
        'hoje': hoje.isoformat(), 'horizonte': horizonte, 'estoque': estoque, 'yMax': round(y_max, 4), 'zoomMinimo': ZOOM_MINIMO_EM_DIAS, 'lead': lead, 'foco': f's{destaque}',
        'ruptura': None if t_ruptura is None else round(t_ruptura, 4), 'enviar': None if (t_envio is None or t_envio < 0) else round(t_envio, 4), 'pedido': pedido if pedido else None,
        'rupturaDia': dia_ruptura, 'enviarDia': dia_envio,
        'sug': None if not com else {'id': 'sug', 'rotulo': 'Com o envio', 'cor': COR_DA_REMESSA, 'media': round(media_foco, 6), 'chega': lead, 'antes': round(com['antes'], 4), 'depois': round(com['apos'], 4),
                                     'tZero': round(com['t_zero'], 4), 'diaZero': com['dia_nova_ruptura'], 'qtd': com['qtd']},
        'series': [{'id': f's{s["dias"]}', 'dias': s['dias'], 'rotulo': _plural(s['dias'], 'dia', 'dias'), 'media': round(s['media'], 6), 'cor': _cor(s['dias']),
                    'diaRuptura': floor(estoque / s['media']) if estoque > 0 and s['media'] > 0 else None} for s in com_ritmo],
    }
    descricao = (f'Curvas do estoque de {_numero(estoque)} unidades nos próximos {horizonte} dias, uma para cada ritmo de vendas ({", ".join(str(s["dias"]) for s in com_ritmo)} dias); '
                 f'em destaque, o ritmo de {_plural(destaque, "dia", "dias")}.')
    nota = f'A ruptura no ritmo de {_plural(destaque, "dia", "dias")} fica além do que o gráfico mostra ({horizonte} dias).' if truncado else ''
    return {'linhas': linhas, 'zonas': zonas, 'zonas_legenda': zonas_legenda, 'marcadores': marcadores, 'pontos_de_ruptura': pontos_de_ruptura, 'ponto_de_pedido': ponto_de_pedido,
            'grades_y': grades_y, 'ticks_x': ticks_x, 'periodos': periodos, 'remessa': remessa, 'cartao_da_remessa': cartao_da_remessa, 'n_cartoes': len(periodos) + (1 if com else 0), 'dados': dados, 'descricao': descricao, 'horizonte': horizonte, 'viewbox': f'0 0 {horizonte} 100',
            'truncado': truncado, 'nota': nota}
