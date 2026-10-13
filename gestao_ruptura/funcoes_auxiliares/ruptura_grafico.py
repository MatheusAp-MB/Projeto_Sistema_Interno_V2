# gestao_ruptura/funcoes_auxiliares/ruptura_grafico.py
#
# Função Objetivo: Calcula a CURVA DE ESTOQUE da tela "Previsão de Ruptura de estoque": uma linha do estoque caindo para CADA ritmo de vendas (3, 7, 15 e 30 dias, mais o período digitado quando
# for outro), as três zonas do fundo (antes do prazo / prazo crítico de reposição / após a ruptura) do ritmo EM DESTAQUE, a RÉGUA de chips que nomeia cada zona, as linhas de data "Enviar até" e "Ruptura"
# e os cartões de cada ritmo (ponto de pedido, "enviar até", "enviar já" ou "prazo vencido"). O ponto de pedido NÃO é desenhado no gráfico (decisão do Matheus, 13/10/2026): a curva cruza esse nível exatamente na linha
# "Enviar até", que já diz a mesma coisa em data; o valor fica nos cartões de cada ritmo e no diagnóstico. Serve aos dois mundos da tela (Envios Full e Fora do Full): só as palavras mudam (Enviar até x Pedir até, Com o envio
# x Com o pedido; ruptura_texto.palavras). Havendo uma quantidade para enviar (a do Sistema ou a digitada) E uma DATA IDEAL de envio, desenha também a SIMULAÇÃO DE REPOSIÇÃO: a linha que SOBE na chegada ideal
# (data ideal + prazo) e volta a cair no mesmo ritmo até a NOVA ruptura, com as linhas "Chegada ideal" e "Nova ruptura". NÃO existe "hoje" no gráfico (regra do Matheus, 13/10/2026: a data real do envio depende de quando o
# Mercado Livre liberar o agendamento; o que o gráfico mostra é a data IDEAL). Aqui só se calcula a POSIÇÃO de cada peça e se escrevem os textos (inclusive a LEGENDA DIDÁTICA "Como ler este gráfico"); quem desenha
# é o template (SVG para as linhas e as zonas, HTML para os textos e a régua) e quem dá vida (ligar/desligar curvas, passar o mouse, zoom) é o script_ruptura.js.
#
# * [EXPLICAÇÃO] → POR QUE SVG "esticado" (preserveAspectRatio="none"): o layout da tela é "fluido na horizontal, rígido na vertical" (regra do Matheus, 12/10/2026): o gráfico tem ALTURA
#                  FIXA e usa a largura toda, abrindo ou fechando a barra lateral. As linhas acompanham a largura; os textos ficam em HTML por cima (se fossem SVG esticado, as letras
#                  sairiam deformadas).
# * [EXPLICAÇÃO] → O eixo horizontal do SVG é medido em DIAS a partir de hoje (viewBox "0 0 {horizonte} 100"): o zoom e o arrastar do script só trocam o viewBox, sem recalcular nenhuma linha.
#                  O eixo vertical é em % da altura e é FIXO: não muda ao ocultar curvas, trocar o destaque ou dar zoom (a escala olha para o estoque e para o topo da simulação de reposição).
# * [EXPLICAÇÃO] → Os números dos textos saem daqui já como TEXTO ("12.34"): o Django formata número decimal com vírgula (pt-BR), e "x=12,34" quebraria o SVG. Os dados que o script usa vão
#                  em JSON (json_script), que sempre usa o ponto.
# * [EXPLICAÇÃO] → A linha é reta (o ritmo é uma média por dia, então o estoque cai em linha reta). As contas de ruptura, envio e ponto de pedido são as de ruptura_calculo.py, as mesmas
#                  dos cartões da tela: o gráfico não tem regra própria.
# * [EXPLICAÇÃO] → O DIA É UMA COLUNA (regra visual do Matheus, 12/10/2026: "o usuário olha e entende perfeitamente: vai acabar dia X"). O eixo horizontal é contínuo (a linha cruza o zero no meio
#                  de um dia, ex.: 10,8 dias), mas cada DATA ocupa a coluna que vai da meia-noite dela (número inteiro) até a meia-noite seguinte. O dia da ruptura é o dia da leitura + floor(dias de estoque) (a regra
#                  de ruptura_calculo.py), então a linha SEMPRE cruza o zero dentro da coluna da data da ruptura. Por isso as divisas das zonas caem na meia-noite, o nome de cada data do eixo fica CENTRADO na coluna dela
#                  e as linhas de data ("Enviar até", "Ruptura", "Nova ruptura") ficam no MEIO da coluna do dia.

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
#                  verde = a simulação de reposição (linha da remessa, "Chegada ideal", "Nova ruptura"), vermelho = a ruptura, verde/laranja/vermelho clarinhos = as zonas do fundo, azul-marinho = o "Enviar até". O período digitado que
#                  não é um dos quatro usa a cor neutra "extra". As cores em si moram no CSS (--rup-c3, --rup-c7...).
COR_DO_RITMO = {3: 'c3', 7: 'c7', 15: 'c15', 30: 'c30'}
COR_DO_RITMO_AVULSO = 'extra'
COR_DA_REMESSA = 'sug'   # a linha da simulação tem cor própria (verde: a reposição na data ideal, o estoque que SOBE com o envio)
ROTULO_DAS_ZONAS = {'antes': 'Antes do prazo', 'critico': 'Prazo crítico de reposição', 'pos': 'Após ruptura {sem}'}   # "{sem}" vira "sem envio" ou "sem pedido" (ruptura_texto.palavras)
ROTULO_BREVE_DAS_ZONAS = {'critico': 'Prazo crítico', 'pos': 'Após ruptura'}   # o nome que o chip da régua usa quando o espaço não comporta o nome inteiro (a zona de poucos dias, ou o zoom)


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


# Função Objetivo: As zonas do fundo, em dias a partir do dia da leitura do estoque, para o ritmo em destaque: [(classe, inicio, fim, atrasada)]. São TRÊS, como um semáforo bem clarinho: "antes" (verde: ainda não é hora de
# enviar, vai da leitura até a data ideal), "critico" (laranja: do "Enviar até" até a ruptura; mais forte quando até o último dia possível já passou) e "pos" (vermelha: do dia da ruptura em diante, sem produto). Todas as
# divisas caem na meia-noite de um dia (número inteiro), porque ruptura e "enviar até" são DIAS. Estoque zerado = tudo "pos"; sem ruptura prevista (sem vendas) = tudo "antes".
def _zonas(estoque, lead, ante, t_ruptura, horizonte):
    if estoque <= 0:
        return [('pos', 0.0, float(horizonte), False)]
    if t_ruptura is None:
        return [('antes', 0.0, float(horizonte), False)]
    dia_ruptura = floor(t_ruptura)
    dia_limite = dia_ruptura - lead      # o último dia possível do envio
    dia_envio = dia_limite - ante        # a data ideal ("Enviar até")
    zonas = []
    if dia_envio > 0:
        zonas.append(('antes', 0.0, float(min(dia_envio, horizonte)), False))
    if dia_envio < horizonte and dia_ruptura > 0:
        zonas.append(('critico', float(max(0, dia_envio)), float(min(dia_ruptura, horizonte)), dia_limite < 0))
    if dia_ruptura < horizonte:
        zonas.append(('pos', float(dia_ruptura), float(horizonte), False))
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
                dica.append(f'O prazo {P["do_envio"]} acabou em {_data_completa(envio["ultimo_dia"])}: com prazo de {_plural(lead, "dia", "dias")}, {P["a_remessa"]} chega depois da ruptura e vão faltar pelo menos '
                            f'{_plural(envio["faltam_dias"], "dia", "dias")} de estoque (quanto mais tarde {P["verbo"]}, mais falta).')
            elif envio['estado'] == 'ja':
                texto, classe = P['enviar_ja'], 'atencao'
                dica.append(f'A data ideal ({_data_completa(envio["enviar_ate"])}) já passou, mas ainda dá tempo: o último dia possível é {_data_completa(envio["ultimo_dia"])}, quando {P["a_remessa"]} chega no próprio dia da ruptura. '
                            f'Quanto mais tarde {P["verbo"]}, menos folga (o ideal é chegar {_plural(ante, "dia", "dias")} antes).')
            else:
                texto = f'{P["enviar_ate"]} {_data_curta(envio["enviar_ate"], hoje)}'
                classe = 'atencao' if envio['estado'] == 'hoje' else 'ok'
                quando = f' ({_em_dias(envio["em_dias"])})' if envio['em_dias'] else ''
                dica.append(f'{P["enviar_ate"]} {_data_completa(envio["enviar_ate"])}{quando}, para chegar {_plural(ante, "dia", "dias")} antes da ruptura.')
    return {**base, 'ritmo': f'{_un_dia(media)} un/dia', 'ritmo_numero': _un_dia(media), 'pedido_numero': _numero(pedido) if pedido is not None else '—',
            'envio': texto, 'envio_classe': classe, 'dica': ' '.join(dica)}


# Função Objetivo: O cartão da SIMULAÇÃO DE REPOSIÇÃO (a linha verde), no mesmo molde dos cartões de ritmo: liga/desliga a linha, diz a quantidade, a chegada ideal e a nova ruptura. `com` vem de
# ruptura_calculo.com_envio (a remessa sai na DATA IDEAL: não existe "hoje" nesta conta). A cor da última linha acompanha o diagnóstico: verde = a quantidade acrescenta pelo menos a folga desejada; laranja = acrescenta menos.
def _cartao_da_remessa(com, lead, folga, hoje, P):
    saida, chegada, nova = hoje + timedelta(days=com['dia_do_envio']), hoje + timedelta(days=com['chegada']), hoje + timedelta(days=com['dia_nova_ruptura'])
    dada = floor(round(com['folga_dada'], 6))
    classe = 'ok' if dada >= folga else 'atencao'
    dica = [f'Simulação de reposição ({com.get("fonte", "quantidade")}): {P["gerundio"]} {_numero(com["qtd"])} un na data ideal ({_data_completa(saida)}), {P["a_remessa"]} chega em {_data_completa(chegada)} (prazo de {_plural(lead, "dia", "dias")}).',
            f'Nesse dia o estoque terá cerca de {_numero(com["apos"])} un ({_numero(ceil(com["antes"]))} que sobram + {_numero(com["qtd"])} {P["da_remessa"]}) e volta a cair no mesmo ritmo até a nova ruptura, em {_data_completa(nova)}.',
            f'A quantidade acrescenta {_plural(dada, "dia", "dias")} de estoque (a folga desejada é de {_plural(folga, "dia", "dias")}).']
    return {'id': 'sug', 'cor': COR_DA_REMESSA, 'curto': P['com'], 'quantidade': f'{_numero(com["qtd"])}', 'chega': f'Chegada ideal {_data_curta(chegada, hoje)}', 'nova': f'Nova ruptura {_data_curta(nova, hoje)}',
            'classe': classe, 'dica': ' '.join(dica), 'sem_data': False, 'envio_ideal': _data_curta(saida, hoje)}


# Função Objetivo: O cartão da simulação quando NÃO existe data ideal (ela já passou, o estoque está zerado ou não há ruptura prevista): a linha verde não é desenhada, porque a chegada depende de quando o Mercado Livre
# liberar o envio. `sem` = {qtd, fonte, motivo ('ja' | 'vencido' | 'zerado' | 'sem_ruptura'), dia_limite, nova}; `nova` = a nova ruptura quando a remessa chegar até o dia da ruptura (só no motivo 'ja').
def _cartao_sem_data(sem, hoje, P):
    motivo, qtd = sem['motivo'], _numero(sem['qtd'])
    chega, classe = {'ja': ('Data ideal já passou', 'atencao'), 'vencido': ('Prazo vencido', 'vencido'), 'zerado': ('Estoque zerado', 'vencido'), 'sem_ruptura': ('Sem ruptura prevista', 'neutro')}[motivo]
    dica = f'Simulação de reposição ({sem.get("fonte", "quantidade")}: {qtd} un). {porque_sem_data(sem, hoje, P)}'
    return {'id': 'sug', 'cor': COR_DA_REMESSA, 'curto': P['com'], 'quantidade': qtd, 'chega': chega, 'nova': 'Chegada: data do ML' if motivo != 'sem_ruptura' else 'Sem data ideal', 'classe': classe,
            'dica': dica, 'sem_data': True, 'envio_ideal': ''}


# Função Objetivo: A frase que explica POR QUE não há data ideal (e por isso a linha verde não é desenhada). Serve ao cartão do gráfico e ao do diagnóstico.
def porque_sem_data(sem, hoje, P):
    motivo = sem['motivo']
    if motivo == 'ja':
        limite = hoje + timedelta(days=sem['dia_limite'])
        nova = f' Se {P["a_remessa"]} chegar até {_data_completa(limite)} (o dia da ruptura), a nova ruptura vem em {_data_completa(hoje + timedelta(days=sem["nova"]))}: quanto mais tarde chegar, menos folga.' if sem.get('nova') is not None else ''
        return f'A data ideal já passou e a data de chegada só existe quando o Mercado Livre liberar o envio: sem ela não dá para desenhar a linha.{nova}'
    if motivo == 'vencido':
        return f'O prazo {P["do_envio"]} já acabou: {P["a_remessa"]} vai chegar depois da ruptura, e a nova ruptura depende de quando o Mercado Livre liberar a data (chegada + folga).'
    if motivo == 'zerado':
        return f'Com o estoque zerado não existe data ideal: {P["verbo"]} o quanto antes. A chegada depende de quando o Mercado Livre liberar a data.'
    return 'Sem ruptura prevista neste ritmo não há data ideal para repor.'


# Função Objetivo: O nome de uma zona do fundo ("Antes do prazo", "Prazo crítico de reposição", "Após ruptura sem envio"). Serve à régua, à legenda e ao "title"; "{sem}" vira "sem envio" ou "sem pedido" (ruptura_texto.palavras).
def _rotulo_da_zona(classe, P):
    return ROTULO_DAS_ZONAS[classe].format(sem=P['sem'])


# Função Objetivo: A LEGENDA DIDÁTICA do gráfico (o painel "Como ler este gráfico", que nasce FECHADO: o gráfico já se explica sozinho pela régua e pelos nomes ao lado de cada linha): para cada peça DESENHADA agora, uma
# amostra (a mesma cor ou linha do gráfico) e uma explicação curta, com os números DESTE produto (datas, dias, quantidades). Só entra o que está no desenho: uma zona sem dias, uma data fora do horizonte ou a linha da
# simulação sem quantidade não aparecem. Três grupos: o FUNDO (as faixas), as DATAS (uma linha vertical por data) e as LINHAS (os ritmos e a simulação). As cores em si moram no CSS.
# * [EXPLICAÇÃO] → Os textos NÃO citam o nome da cor ("o azul", "o verde"): quem mostra a cor é a amostra. Assim, trocar uma cor no CSS não deixa a legenda mentindo.
# * [EXPLICAÇÃO] → Nenhum texto fala em "hoje": o dia 0 do gráfico é o dia da LEITURA do estoque, e a data real do envio só existe quando o Mercado Livre libera o agendamento. O que o gráfico mostra é a DATA IDEAL.
def _legenda(P, hoje, estoque, lead, ante, destaque, media_foco, t_ruptura, zonas, marcadores, outros, com, folga):
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
    dia_ideal = dia_limite - ante if dia_limite is not None else None
    estoque_txt = _numero(estoque)

    def item(amostra, titulo, texto, cor=''):
        return {'amostra': amostra, 'titulo': titulo, 'texto': texto, 'cor': cor}

    # ---- o fundo ----
    fundo = []
    if 'antes' in classes:
        fundo.append(item('zona-antes', _rotulo_da_zona('antes', P),
                          f'Ainda não é hora de {verbo}: todos os dias daqui vêm antes da data ideal ({P["enviar_ate"]} {d(dia_ideal)}).' if dia_ideal is not None
                          else f'Neste ritmo o estoque não acaba, então não há data para {verbo}: o gráfico inteiro fica nesta faixa.'))
    if 'critico' in classes:
        if classes['critico']['atrasada']:
            texto = f'Do começo até a ruptura ({d(dia_rup)}). A data ideal ({d(dia_ideal)}) e o último dia possível ({d(dia_limite)}) já passaram: {a_remessa} chega depois da ruptura e vai faltar estoque. Cor mais forte: você já está nela.'
        elif dia_ideal < 0:
            texto = f'Do começo até a ruptura ({d(dia_rup)}). A data ideal ({d(dia_ideal)}) já passou: cada dia a mais tira folga de {a_remessa}, e depois de {d(dia_limite)} ela chega depois da ruptura.'
        else:
            texto = (f'Da data ideal ({d(dia_ideal)}) até a ruptura ({d(dia_rup)}). {gerundio.capitalize()} na data ideal, {a_remessa} chega {ante_txt} antes da ruptura; até {d(dia_limite)} ainda chega a tempo, mas sem folga; depois disso chega tarde.')
        fundo.append(item('zona-critico', _rotulo_da_zona('critico', P), texto))
    if 'pos' in classes:
        fundo.append(item('zona-pos', _rotulo_da_zona('pos', P),
                          'O estoque está zerado: todo o gráfico fica nesta faixa.' if estoque <= 0
                          else f'O estoque já acabou (no ritmo de {foco_txt}): sem produto para vender, a menos que {a_remessa} chegue antes.'))

    # ---- as datas ----
    datas = []
    if 'enviar' in marc:
        dia = marc['enviar']['dia']
        partes = ([f'prazo ({lead_txt})'] if lead else []) + ([f'chegar antes ({ante_txt})'] if ante else [])
        conta = f'ruptura ({d(dia_rup)}) − ' + ' − '.join(partes)
        chegada = f'{ante_txt} antes de o estoque acabar' if ante else 'a tempo, no dia em que o estoque acabaria'
        datas.append(item('dia-enviar', f'{P["enviar_ate"]} {d(dia)}',
                          f'A data ideal para {verbo}: {conta}. {gerundio.capitalize()} até aqui, {a_remessa} chega {chegada}. O último dia possível (sem margem) é {d(dia_limite)}.'))
    if 'ruptura' in marc:
        dia = marc['ruptura']['dia']
        datas.append(item('dia-ruptura', f'Ruptura {P["sem"]} {d(dia)}',
                          f'O dia em que o estoque de {estoque_txt} un acaba se nada novo chegar: a {ritmo} (ritmo de {foco_txt}) ele dura {_plural(dia, "dia inteiro", "dias inteiros")}. A linha do estoque chega a zero nesta coluna.'))
    if com and 'chega' in marc:
        datas.append(item('dia-chega', f'Chegada ideal {d(marc["chega"]["dia"])}',
                          f'Se você {verbo} {_numero(com["qtd"])} un na data ideal ({d(com["dia_do_envio"])}), {a_remessa} chega nesta data (data ideal + {lead_txt} de prazo) e o estoque sobe.'))
    if com and 'nova' in marc:
        dada = floor(round(com['folga_dada'], 6))
        datas.append(item('dia-nova', f'Nova ruptura {P["com_min"]} {d(marc["nova"]["dia"])}',
                          f'{a_remessa.capitalize()} acrescenta {_plural(dada, "dia", "dias")} de estoque, e ele volta a acabar nesta data.' + (f' A folga desejada é de {_plural(folga, "dia", "dias")}.' if folga else '')))
    sub_datas = 'Cada data é uma coluna inteira (o dia vai da linha da esquerda até a da direita); a linha da data fica no meio dela (a da chegada, no começo, onde o estoque sobe).'

    # ---- as linhas ----
    linhas = [item('linha', f'Linha grossa · ritmo de {foco_txt}',
                   f'O estoque lido ({estoque_txt} un) caindo {ritmo}: é o ritmo em destaque, o que define o fundo e as datas. Para trocar, clique no cartão de outro ritmo.', _cor(destaque))]
    if outros:
        linhas.append(item('linha-fina', 'Linhas finas e tracejadas · outros ritmos',
                           'Cada um na cor do seu cartão (embaixo do gráfico, onde também se liga e desliga). O ponto marca onde a linha chega a zero.', _cor(outros[0]['dias'])))
    if com:
        linhas.append(item('linha', f'Simulação de reposição · {P["com"]}',
                           f'O que acontece se você {verbo} {_numero(com["qtd"])} un na data ideal: o estoque sobe quando {a_remessa} chega e volta a cair até a nova ruptura. Liga e desliga no cartão “{P["com"]}”.', COR_DA_REMESSA))

    intro = (f'O estoque cai conforme você vende. Cada dia é uma coluna do desenho; as datas do eixo marcam só algumas delas (com o zoom, chegam a uma por dia) e a distância entre elas é proporcional ao tempo. '
             f'O fundo, as datas e a linha grossa valem para o ritmo em destaque ({foco_txt}, {ritmo}), sem novo envio; a linha verde é a simulação de reposição. Cada cor e cada linha significam uma única coisa.')
    grupos = [{'titulo': 'O fundo: as faixas', 'sub': f'Do dia da leitura do estoque em diante, no ritmo de {foco_txt}.', 'itens': fundo},
              {'titulo': 'As datas: uma linha por dia', 'sub': sub_datas, 'itens': datas},
              {'titulo': 'As linhas', 'sub': 'A altura é o estoque em unidades (escala à esquerda).', 'itens': linhas}]
    return {'intro': intro, 'grupos': [g for g in grupos if g['itens']]}


# Função Objetivo: O gráfico pronto para o template, ou None quando não há o que desenhar (sem estoque, ou o ritmo em destaque sem dados). `series` = lista de
# {'dias': N, 'media': un/dia ou None, 'url': endereço que põe esse ritmo em destaque}; `destaque` = os dias do ritmo em destaque (o período escolhido na tela); `com` = o que acontece com o estoque
# se a quantidade escolhida for enviada NA DATA IDEAL (ruptura_calculo.com_envio; None = sem quantidade ou sem data ideal, sem linha da simulação); `sem_data` = quando há quantidade mas NÃO há data ideal (ela
# já passou, estoque zerado...): {qtd, fonte, motivo, dia_limite, nova}, só para o cartão dizer por que a linha verde não aparece; `ante` = quantos dias antes da ruptura o envio deve chegar (define o "Enviar até");
# `folga` = os dias de estoque que o envio deve acrescentar (só para a cor do cartão da simulação); `mundo` = 'full' | 'fora' (só as palavras mudam).
# * [EXPLICAÇÃO] → A RÉGUA (duas faixas de chips acima do desenho, pedido do Matheus em 13/10/2026): na de cima, as três zonas do fundo (cada chip tem a mesma cor, o mesmo começo e o mesmo fim da zona que ele nomeia);
#                  na de baixo, a simulação (da chegada ideal até a nova ruptura). Os chips são HTML (texto não deforma) e o script_ruptura.js os reposiciona a cada zoom.
# * [EXPLICAÇÃO] → Onde cada LINHA DE DATA fica: no MEIO da coluna do dia (o mesmo lugar do nome da data no eixo) para "Enviar até", "Ruptura" e "Nova ruptura"; e no COMEÇO da coluna da "Chegada ideal", porque é ali
#                  que a linha do estoque dá o salto para cima (a remessa chega no começo do dia).
def montar_grafico(estoque, lead, ante, series, destaque, hoje, com=None, folga=0, mundo='full', sem_data=None):
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

    y_max = max(estoque, com['apos'] if com else 0, 10) * MARGEM_DO_TOPO   # a escala cabe o estoque lido e o topo da simulação (a remessa que chega); nada mais é desenhado acima disso

    def x(t):
        return t / horizonte * 100

    def y(valor):
        return 100 - valor / y_max * 100

    def d(dia):
        return _data_curta(hoje + timedelta(days=dia), hoje)

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
    t_envio = t_ruptura - lead - ante if (t_ruptura is not None and (lead or ante)) else None   # a data IDEAL (ruptura − prazo − chegar antes)
    zonas_cruas = _zonas(estoque, lead, ante, t_ruptura, horizonte)
    zonas = [{'classe': c, 'inicio': _c(i), 'largura': _c(f - i), 'atrasada': atrasada} for c, i, f, atrasada in zonas_cruas]

    marcadores = []

    def marcador(dia, classe, rotulo, linha, serie='', ancora=0.5, lado='dir'):
        # * [EXPLICAÇÃO] → O marcador é uma LINHA FINA na posição `dia + ancora` (o meio da coluna do dia; ancora 0 = o começo dela). O texto fica ao lado da linha, do lado preferido (`lado`: a chegada fica à esquerda
        #                  da linha dela, as outras datas à direita), e inverte quando a linha está colada na borda. `serie` = a curva a que o marcador pertence (os da simulação ligam e desligam junto com a linha verde).
        posicao = dia + ancora
        if (lado == 'dir' and x(posicao) > 72) or (lado == 'esq' and x(posicao) < 28):
            lado = 'esq' if lado == 'dir' else 'dir'
        marcadores.append({'dia': dia, 'classe': classe, 'rotulo': rotulo, 'topo': linha * LINHA_DOS_MARCADORES_PX + 6, 'lado': lado, 'posicao': _c(posicao), 'x': _c(x(posicao)), 'serie': serie})

    dia_envio = dia_ruptura = None
    if t_envio is not None and 0 <= t_envio < horizonte:
        dia_envio = floor(t_envio)
        marcador(dia_envio, 'enviar', f'{P["enviar_ate"]} {d(dia_envio)}', 0)
    if t_ruptura is not None and t_ruptura < horizonte:
        dia_ruptura = floor(t_ruptura)
        marcador(dia_ruptura, 'ruptura', f'Ruptura {P["sem"]} {d(dia_ruptura)}', 1)
    truncado = t_ruptura is not None and t_ruptura >= horizonte

    # ---- a simulação (a linha que SOBE na chegada ideal): só havendo quantidade E data ideal. Antes da chegada ela é igual à curva do ritmo em destaque (por isso só se desenha daqui em diante) ----
    remessa = None
    if com:
        chegada = float(com['chegada'])
        pontos_r = [(chegada, com['antes']), (chegada, com['apos'])]
        if com['t_zero'] < horizonte:
            pontos_r += [(com['t_zero'], 0), (float(horizonte), 0)]
        else:
            pontos_r.append((float(horizonte), com['apos'] - media_foco * (horizonte - chegada)))
        remessa = {'id': 'sug', 'cor': COR_DA_REMESSA, 'pontos': ' '.join(f'{_c(t)},{_c(y(v))}' for t, v in pontos_r)}
        if com['chegada'] < horizonte:
            marcador(com['chegada'], 'chega', f'Chegada ideal {d(com["chegada"])}', 2, 'sug', ancora=0.0, lado='esq')
        if com['t_zero'] < horizonte:
            marcador(com['dia_nova_ruptura'], 'nova', f'Nova ruptura {P["com_min"]} {d(com["dia_nova_ruptura"])}', 3, 'sug', lado='esq')

    # ---- a régua: as zonas (faixa de cima) e a simulação (faixa de baixo). `ini`/`fim` em dias; o script refaz a posição quando há zoom ----
    regua = []

    def chip(faixa, classe, ini, fim, rotulo, datas, serie='', breve=''):
        regua.append({'faixa': faixa, 'classe': classe, 'ini': _c(ini), 'fim': _c(fim), 'x': _c(x(ini)), 'largura': _c(x(fim) - x(ini)), 'rotulo': rotulo, 'breve': breve or rotulo, 'datas': datas, 'serie': serie,
                      'titulo': rotulo + (f' · {datas}' if datas else '')})

    if t_ruptura is not None:
        dia_ideal, dia_rup = floor(t_ruptura) - lead - ante, floor(t_ruptura)
    for classe, ini, fim, atrasada in zonas_cruas:
        rotulo, datas = _rotulo_da_zona(classe, P), ''
        if classe == 'antes':
            rotulo, datas = ('Sem ruptura prevista neste ritmo', '') if t_ruptura is None else (rotulo, f'até {d(dia_ideal)}')
        elif classe == 'critico':
            datas = f'até {d(dia_rup)}' if dia_ideal < 0 else f'{d(dia_ideal)} → {d(dia_rup)}'
        elif classe == 'pos':
            rotulo, datas = ('Estoque zerado', '') if estoque <= 0 else (rotulo, f'a partir de {d(dia_rup)}')
        chip(0, classe, ini, fim, rotulo, datas, breve=ROTULO_BREVE_DAS_ZONAS.get(classe, '') if rotulo == _rotulo_da_zona(classe, P) else '')
    if com and com['chegada'] < horizonte:
        chip(1, 'cenario', float(com['chegada']), min(float(horizonte), com['dia_nova_ruptura'] + 0.5), P['com'], f'chega {d(com["chegada"])} → nova ruptura {d(com["dia_nova_ruptura"])}', 'sug')

    # ---- os outros ritmos: só um pontinho onde a linha encosta no zero (o detalhe vem no passar do mouse e no cartão do ritmo) ----
    pontos_de_ruptura = []
    for s in com_ritmo:
        if s['dias'] == destaque or not (estoque > 0 and s['media'] > 0):
            continue
        t = estoque / s['media']
        if t < horizonte:
            pontos_de_ruptura.append({'id': f's{s["dias"]}', 'cor': _cor(s['dias']), 't': _c(t), 'x': _c(x(t)),
                                      'rotulo': f'Ruptura {d(floor(t))} no ritmo de {_plural(s["dias"], "dia", "dias")}'})

    # ---- os eixos ----
    passo_y = _passo_do_eixo_y(y_max)
    grades_y, valor = [], 0.0
    while valor <= y_max:
        grades_y.append({'y': _c(y(valor)), 'rotulo': _numero(valor)})
        valor += passo_y
    passo_x = next((p for p in PASSOS_DO_EIXO_X if horizonte / p <= 8), 365)
    ticks_x = [{'t': t, 'x_meio': _c(x(t + 0.5)), 'leitura': t == 0, 'rotulo': d(t)} for t in range(0, horizonte, passo_x)]   # o primeiro é o dia da leitura do estoque (sem "HOJE": a data real do envio vem do Mercado Livre)

    # ---- a legenda didática ("Como ler este gráfico"): só o que está desenhado ----
    legenda = _legenda(P, hoje, estoque, lead, ante, destaque, media_foco, t_ruptura, zonas, marcadores, [s for s in com_ritmo if s['dias'] != destaque], com, folga)

    periodos = [_periodo(s, estoque, lead, ante, hoje, s['dias'] == destaque, P) for s in series]
    cartao_da_remessa = _cartao_da_remessa(com, lead, folga, hoje, P) if com else (_cartao_sem_data(sem_data, hoje, P) if sem_data else None)
    dados = {
        'hoje': hoje.isoformat(), 'horizonte': horizonte, 'estoque': estoque, 'yMax': round(y_max, 4), 'zoomMinimo': ZOOM_MINIMO_EM_DIAS, 'lead': lead, 'foco': f's{destaque}',
        'ruptura': None if t_ruptura is None else round(t_ruptura, 4), 'enviar': None if (t_envio is None or t_envio < 0) else round(t_envio, 4),
        'rupturaDia': dia_ruptura, 'enviarDia': dia_envio,
        'sug': None if not com else {'id': 'sug', 'rotulo': P['com'], 'cor': COR_DA_REMESSA, 'media': round(media_foco, 6), 'chega': com['chegada'], 'antes': round(com['antes'], 4), 'depois': round(com['apos'], 4),
                                     'tZero': round(com['t_zero'], 4), 'diaZero': com['dia_nova_ruptura'], 'qtd': com['qtd']},
        'series': [{'id': f's{s["dias"]}', 'dias': s['dias'], 'rotulo': _plural(s['dias'], 'dia', 'dias'), 'media': round(s['media'], 6), 'cor': _cor(s['dias']),
                    'diaRuptura': floor(estoque / s['media']) if estoque > 0 and s['media'] > 0 else None} for s in com_ritmo],
    }
    descricao = (f'Curvas do estoque de {_numero(estoque)} unidades nos próximos {horizonte} dias, uma para cada ritmo de vendas ({", ".join(str(s["dias"]) for s in com_ritmo)} dias); '
                 f'em destaque, o ritmo de {_plural(destaque, "dia", "dias")}.')
    nota = f'A ruptura no ritmo de {_plural(destaque, "dia", "dias")} fica além do que o gráfico mostra ({horizonte} dias).' if truncado else ''
    return {'linhas': linhas, 'zonas': zonas, 'regua': regua, 'legenda': legenda, 'marcadores': marcadores, 'pontos_de_ruptura': pontos_de_ruptura,
            'grades_y': grades_y, 'ticks_x': ticks_x, 'periodos': periodos, 'remessa': remessa, 'cartao_da_remessa': cartao_da_remessa, 'n_cartoes': len(periodos) + (1 if cartao_da_remessa else 0),
            'envio_ideal': cartao_da_remessa['envio_ideal'] if cartao_da_remessa else '', 'dados': dados, 'descricao': descricao, 'horizonte': horizonte, 'viewbox': f'0 0 {horizonte} 100',
            'truncado': truncado, 'nota': nota}
