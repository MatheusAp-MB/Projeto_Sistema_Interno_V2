# gestao_ruptura/funcoes_auxiliares/ruptura_grafico.py
#
# Função Objetivo: Calcula a CURVA DE ESTOQUE da tela "Ruptura de estoque": a linha do estoque caindo de hoje até zerar, a faixa do lead time, os marcadores
# ("Enviar até", "Ruptura") e o ponto de pedido. Aqui só se calcula a POSIÇÃO de cada peça (em % da área do gráfico); quem desenha é o template (SVG para as linhas
# e HTML para os textos).
#
# * [EXPLICAÇÃO] → POR QUE em porcentagem e com SVG "esticado" (preserveAspectRatio="none"): o layout da tela é "fluido na horizontal, rígido na vertical" (regra do
#                  Matheus, 12/10/2026): o gráfico tem ALTURA FIXA e usa a largura toda, abrindo ou fechando a barra lateral. Em % as linhas acompanham a largura; os
#                  textos ficam em HTML por cima (se fossem SVG esticado, as letras sairiam deformadas).
# * [EXPLICAÇÃO] → TODOS os números saem daqui já como TEXTO ("12.34"): o Django formata número decimal com vírgula (pt-BR), e "x=12,34" quebraria o SVG.
# * [EXPLICAÇÃO] → A linha é reta (o ritmo é uma média por dia, então o estoque cai em linha reta). A linha do período escolhido manda na faixa do lead time, nos
#                  marcadores e no ponto de pedido; a do ritmo recente (tracejada) só mostra onde a ruptura cairia se o ritmo recente continuasse.

from datetime import timedelta
from math import ceil, floor, log10

HORIZONTE_MINIMO = 14
HORIZONTE_MAXIMO = 730
MARGEM_DO_TOPO = 1.1
PASSOS_DO_EIXO_X = (1, 2, 5, 7, 10, 14, 15, 20, 30, 45, 60, 90, 120, 180, 365)
LINHA_DOS_MARCADORES_PX = 24   # cada marcador ocupa uma "linha" de texto no topo do gráfico (não se sobrepõem)


def _c(valor):
    return f'{valor:.2f}'


def _numero(n):
    return f'{int(round(n)):,}'.replace(',', '.')


def _data_curta(dia, hoje):
    return dia.strftime('%d/%m' if dia.year == hoje.year else '%d/%m/%Y')


def _passo_do_eixo_y(maximo):
    bruto = maximo / 4
    base = 10 ** floor(log10(bruto))
    for multiplo in (1, 2, 2.5, 5, 10):
        if multiplo * base >= bruto:
            return multiplo * base
    return 10 * base


# Função Objetivo: O gráfico pronto para o template, ou None quando não há o que desenhar (sem estoque ou sem ritmo). `series` = lista de
# {'classe': 'periodo'|'recente', 'media': un/dia ou None, 'rotulo': texto da legenda}; a PRIMEIRA é a do período escolhido.
def montar_grafico(estoque, lead, series, hoje):
    series = [s for s in series if s['media'] is not None]
    if estoque is None or not series or series[0]['classe'] != 'periodo':
        return None
    principal = series[0]['media']

    quedas = [estoque / s['media'] for s in series if estoque > 0 and s['media'] > 0]
    base = max(quedas) if quedas else 30
    if lead:
        base = max(base, lead * 1.3)
    horizonte = min(HORIZONTE_MAXIMO, max(HORIZONTE_MINIMO, ceil(base * 1.12)))

    pedido = ceil(principal * lead) if lead is not None and principal > 0 else None
    y_max = max(estoque, pedido or 0, 10) * MARGEM_DO_TOPO

    def x(t):
        return t / horizonte * 100

    def y(valor):
        return 100 - valor / y_max * 100

    # ---- as linhas do estoque (uma por ritmo) ----
    linhas = []
    for s in series:
        media = s['media']
        pontos = [(0, estoque)]
        if estoque > 0 and media > 0:
            t0 = estoque / media
            pontos += [(t0, 0), (horizonte, 0)] if t0 < horizonte else [(horizonte, estoque - media * horizonte)]
        else:
            pontos.append((horizonte, estoque))
        texto = ' '.join(f'{_c(x(t))},{_c(y(v))}' for t, v in pontos)
        linhas.append({'classe': s['classe'], 'pontos': texto, 'area': f'{texto} 100.00,100.00 0.00,100.00' if s['classe'] == 'periodo' else ''})

    # ---- a faixa do lead time e os marcadores (todos pelo ritmo do período) ----
    faixa, marcadores, truncado = None, [], False

    def marcador(t, classe, rotulo, linha):
        marcadores.append({'x': _c(x(t)), 'classe': classe, 'rotulo': rotulo, 'topo': linha * LINHA_DOS_MARCADORES_PX + 6, 'lado': 'esq' if x(t) > 55 else 'dir'})

    if estoque > 0 and principal > 0:
        t_ruptura = estoque / principal
        if t_ruptura >= horizonte:
            truncado = True
        else:
            if lead:
                inicio = max(0.0, t_ruptura - lead)
                faixa = {'x': _c(x(inicio)), 'largura': _c(x(t_ruptura) - x(inicio)), 'centro': _c((x(inicio) + x(t_ruptura)) / 2),
                         'atrasada': t_ruptura - lead < 0, 'rotulo': f'Lead time: {lead} dias'}
                if t_ruptura - lead >= 0:
                    marcador(t_ruptura - lead, 'enviar', f'Enviar até {_data_curta(hoje + timedelta(days=floor(t_ruptura - lead)), hoje)}', 0)
            marcador(t_ruptura, 'ruptura', f'Ruptura {_data_curta(hoje + timedelta(days=floor(t_ruptura)), hoje)}', 1)
        for s in series[1:]:
            if s['media'] > 0 and estoque / s['media'] < horizonte:
                t_recente = estoque / s['media']
                marcador(t_recente, 'recente', f'Ruptura pelo ritmo recente {_data_curta(hoje + timedelta(days=floor(t_recente)), hoje)}', 2)

    ponto_de_pedido = None
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
    ticks_x = [{'x': _c(x(t)), 'hoje': t == 0, 'rotulo': 'HOJE' if t == 0 else _data_curta(hoje + timedelta(days=t), hoje)} for t in range(0, horizonte + 1, passo_x)]

    legenda = [{'tipo': s['classe'], 'rotulo': s['rotulo']} for s in series]
    if faixa:
        legenda.append({'tipo': 'faixa', 'rotulo': 'Lead time'})
    if ponto_de_pedido:
        legenda.append({'tipo': 'pedido', 'rotulo': 'Ponto de pedido'})
    descricao = f'Curva do estoque de {_numero(estoque)} unidades nos próximos {horizonte} dias, caindo no ritmo de vendas escolhido.'
    return {'linhas': linhas, 'faixa': faixa, 'marcadores': marcadores, 'ponto_de_pedido': ponto_de_pedido, 'grades_y': grades_y, 'ticks_x': ticks_x,
            'legenda': legenda, 'descricao': descricao, 'horizonte': horizonte, 'truncado': truncado}
