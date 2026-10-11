# gestao_vendas/funcoes_auxiliares/vendas_ml.py
#
# Função Objetivo: Monta tudo o que a tela "Histórico de vendas" mostra, LENDO SÓ DO BANCO (VendaItemMercadoLivre, ColetaVendasMercadoLivre,
# Produto e as variações de anúncio): cartões-resumo, calendário em semanas ou meses (com navegador e leitura do ritmo), mapa de calor hora × dia da semana, quebra por
# origem (Full / fora do Full), por MLB e por Código ML. Nada aqui chama a API do Mercado Livre: quem chama é o coletor, por clique.
#
# REGRAS DO MATHEUS que moram aqui:
#   - Venda CANCELADA não conta (nem no dia da venda original): só soma o que não é status 'cancelled'. O cancelado aparece à parte.
#   - O dia da venda é date_created no horário de Brasília (dia_venda, gravado pelo coletor).
#   - Ausente não é zero: dia fora do que foi coletado aparece como "sem dado", nunca como "0 vendas". O que foi coletado vem do registro de
#     coletas (cobertura), por SKU.
#   - 5 níveis: 1 Produto (o SKU todo), 2 No Full, 3 Fora do Full, 4 Por MLB, 5 Por Código ML.
#
#   - Períodos por CALENDÁRIO (ver cobertura_vendas_ml): Última semana, Último mês, Últimos 3 meses, Últimos 6 meses, Último ano. O fim é hoje (parcial)
#     e o início é a mesma data uma unidade atrás. O período anterior (para comparar) é a mesma unidade imediatamente antes, colado no atual.
#
# * [EXPLICAÇÃO] → O dia de um período é "completo" só se a coleta terminou DEPOIS que o dia acabou. Hoje nunca é completo. Dia parcial entra nas
#                  somas (a venda existe), mas fica de fora da média por dia, dos dias sem venda e da comparação com o período anterior,
#                  que seriam enganosos.

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.db.models import Count, Q, Sum
from django.utils import timezone

from integracao_mercado_livre.servicos.cobertura_vendas_ml import (  # noqa: F401
    PERIODO_PADRAO, carregar_coletas, cobertura, dia_completo, dias_para_tras, frase_frente_ao_anterior, frase_no_anterior, inicio_do_periodo,
    normalizar_periodo, periodo_anterior, periodos_de_hoje, primeiro_dia_do_ml, rotulo_do_periodo, voltar_unidade)
from integracao_mercado_livre.servicos.cobertura_vendas_ml import mapa_de_dias as _mapa_de_dias
from mercado_livre.models import VariacaoAnuncioMercadoLivre, VendaItemMercadoLivre
from produtos.models import Produto

FUSO = ZoneInfo('America/Sao_Paulo')
STATUS_CANCELADO = 'cancelled'
DIAS_DA_SEMANA = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
NIVEIS = [
    ('produto', 'Produto', 'Todos os anúncios do SKU, Full e fora do Full'),
    ('full', 'No Full', 'Só as vendas cujo estoque saiu de um centro do Full'),
    ('fora', 'Fora do Full', 'Só as vendas cujo estoque saiu do estoque próprio (coleta, agência, Flex)'),
    ('mlb', 'Por MLB', 'Um anúncio de cada vez'),
    ('codigo', 'Por Código ML', 'Um Código ML (inventory_id) de cada vez'),
]
NOMES_DOS_NIVEIS = {chave: rotulo for chave, rotulo, _ in NIVEIS}
MESES_ABREV = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
VISOES = ('semanas', 'meses')
MAX_DIAS_ZERADOS_NA_LISTA = 60
MAX_CODIGOS_NO_CARTAO = 4
DIAS_VISAO_MESES = 180  # períodos com tantos dias (de calendário) ou mais: a tela abre em MESES (6 meses e ano); abaixo, em SEMANAS; a pessoa troca pelo botão (?visao=)


# ==================================================== regras pequenas ====================================================

# * [EXPLICAÇÃO] → REGRA PROVISÓRIA (medida em 10/10/2026, conta Magazine, 1 dia, 20 envios consultados): os nós de centros do Full
#                  (BRSP11, BRBA01...) deram logistic.type = fulfillment em 19 de 19; o nó próprio (começa com BRP e contém o código do vendedor)
#                  deu cross_docking (1 caso) e só ele tinha store_id preenchido. Por isso: store_id preenchido OU nó BRP... = fora do Full;
#                  outro nó = Full; sem nó = indefinido. Falta testar mais casos de fora do Full (só 1 foi visto). Esta é a ÚNICA função que
#                  decide isso: se a regra mudar, muda aqui.
PREFIXO_DO_NO_PROPRIO = 'BRP'


def classificar_origem(node_id, store_id):
    if store_id:
        return 'fora'
    if node_id and node_id.upper().startswith(PREFIXO_DO_NO_PROPRIO):
        return 'fora'
    if node_id:
        return 'full'
    return 'indefinido'


def _inteiro(valor, padrao):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def numero(n):
    return f'{int(n):,}'.replace(',', '.')


def dinheiro(valor):
    return 'R$ ' + f'{valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def data_curta(d):
    return f'{d:%d/%m}'


def data_hora(instante):
    return timezone.localtime(instante, FUSO).strftime('%d/%m às %H:%M')


def url_da_tela(base, **parametros):
    limpos = {k: v for k, v in parametros.items() if v not in (None, '')}
    return f'{base}?{urlencode(limpos)}' if limpos else base


# ==================================================== produto, MLBs e Códigos ML ====================================================

# Função Objetivo: Busca de produtos para escolher o SKU: pelo SKU, título, EAN, MLB ou Código ML. Só produtos que têm anúncio do Mercado Livre.
def buscar_produtos(texto, limite=20):
    texto = (texto or '').strip()
    if not texto:
        return []
    filtro = (Q(sku__icontains=texto) | Q(titulo__icontains=texto) | Q(ean__icontains=texto)
              | Q(variacoes_mercado_livre__anuncio__mlb__icontains=texto) | Q(variacoes_mercado_livre__inventory_id__iexact=texto))
    produtos = (Produto.objects.filter(filtro, variacoes_mercado_livre__isnull=False).exclude(sku__isnull=True).exclude(sku='')
                .distinct().order_by('titulo')[:limite])
    return [{'sku': p.sku, 'titulo': p.titulo, 'marca': p.marca or ''} for p in produtos]


# Função Objetivo: Os SKUs que mais venderam nos últimos 30 dias (do que já está no banco): atalho para abrir sem digitar.
def skus_com_vendas(limite=12):
    desde = datetime.now(FUSO).date() - timedelta(days=30)
    linhas = (VendaItemMercadoLivre.objects.filter(dia_venda__gte=desde).exclude(status=STATUS_CANCELADO).exclude(seller_sku='')
              .values('seller_sku').annotate(un=Sum('quantidade')).order_by('-un')[:limite])
    return [{'sku': l['seller_sku'], 'unidades': numero(l['un'])} for l in linhas]


# Função Objetivo: O cadastro do SKU e os MLBs dele (com título e as variações → Código ML). None se o SKU não está em Produto.
def carregar_produto(sku):
    produto = Produto.objects.filter(sku=sku).first()
    if produto is None:
        return None
    mlbs = {}
    variacoes = VariacaoAnuncioMercadoLivre.objects.filter(produto__sku=sku).select_related('anuncio')
    for v in variacoes:
        mlb = v.anuncio.mlb
        if not mlb:
            continue
        item = mlbs.setdefault(mlb, {'titulo': v.anuncio.titulo_anuncio or '', 'variacoes': []})
        item['variacoes'].append((str(v.variacao_id or ''), (v.inventory_id or '').strip().upper()))
    return {'titulo': produto.titulo, 'marca': produto.marca or '', 'imagem': produto.imagem_url or '', 'mlbs': mlbs}


# Função Objetivo: O Código ML (inventory_id) de um item vendido, ligado pelo MLB (e pela variação, se o pedido trouxe). None se o MLB
# não tem Código no banco ou tem mais de um e o pedido não diz qual (aí a tela mostra "indefinido" em vez de chutar).
def codigo_do_item(mlbs, mlb, variation_id):
    variacoes = (mlbs.get(mlb) or {}).get('variacoes') or []
    if variation_id:
        for var_id, codigo in variacoes:
            if var_id == variation_id and codigo:
                return codigo
    codigos = {codigo for _, codigo in variacoes if codigo}
    return next(iter(codigos)) if len(codigos) == 1 else None


# ==================================================== cobertura (o que foi coletado) ====================================================

# A regra de cobertura (carregar_coletas, cobertura, dia_completo) mora em integracao_mercado_livre/servicos/cobertura_vendas_ml.py: UM lugar só,
# que o coletor também usa para buscar só o que falta. Os nomes são importados lá em cima porque o resto desta tela (e os testes) os chamam daqui.

def _faixas(dias_ordenados):
    faixas = []
    for dia in dias_ordenados:
        if faixas and dia - faixas[-1][1] == timedelta(days=1):
            faixas[-1][1] = dia
        else:
            faixas.append([dia, dia])
    return faixas


def _texto_das_faixas(faixas):
    partes = [f'{f[0]:%d/%m/%Y}' if f[0] == f[1] else f'{f[0]:%d/%m/%Y} a {f[1]:%d/%m/%Y}' for f in faixas]
    return ' · '.join(partes[:4]) + (f' · (+{len(partes) - 4})' if len(partes) > 4 else '')


# ==================================================== linhas de venda do produto ====================================================

# Função Objetivo: As linhas de venda (1 por item de pedido) do SKU entre duas datas. O SKU vem do seller_sku do pedido; linha sem seller_sku
# entra só se o MLB é de um anúncio do produto (e, se o pedido traz a variação, só se a variação também é do produto).
def _carregar_linhas(sku, mlbs, de, ate):
    filtro = Q(seller_sku=sku)
    if mlbs:
        filtro |= Q(seller_sku='', mlb__in=list(mlbs))
    return list(VendaItemMercadoLivre.objects.filter(filtro, dia_venda__range=(de, ate)).values(
        'order_id', 'seller_sku', 'mlb', 'variation_id', 'quantidade', 'preco_unitario', 'status', 'dia_venda', 'hora_venda', 'node_id', 'store_id'))


# Função Objetivo: Acrescenta a cada linha a origem (Full / fora / indefinida) e o Código ML, e troca os nomes dos campos por nomes curtos.
def _anotar(linhas, mlbs):
    saida = []
    for l in linhas:
        if not l['seller_sku'] and l['variation_id']:
            ids = {var_id for var_id, _ in (mlbs.get(l['mlb']) or {}).get('variacoes', [])}
            if ids and l['variation_id'] not in ids:
                continue
        saida.append({
            'dia': l['dia_venda'], 'hora': l['hora_venda'], 'qtd': l['quantidade'], 'preco': l['preco_unitario'],
            'cancelado': l['status'] == STATUS_CANCELADO, 'pedido': l['order_id'], 'mlb': l['mlb'],
            'codigo': codigo_do_item(mlbs, l['mlb'], l['variation_id']),
            'origem': classificar_origem(l['node_id'], l['store_id']),
        })
    return saida


# Função Objetivo: Soma de um conjunto de linhas: unidades, pedidos distintos e faturamento (preço × quantidade; linha sem preço fica fora e é contada).
def _somar(linhas):
    pedidos, unidades, faturamento, sem_preco = set(), 0, Decimal('0'), 0
    for l in linhas:
        pedidos.add(l['pedido'])
        unidades += l['qtd']
        if l['preco'] is None:
            sem_preco += 1
        else:
            faturamento += l['preco'] * l['qtd']
    return {'un': unidades, 'pedidos': len(pedidos), 'fat': faturamento, 'sem_preco': sem_preco}


# Função Objetivo: O recorte que o nível escolhido pede (1 Produto = tudo; 2 Full; 3 Fora do Full; 4 um MLB; 5 um Código ML).
def _selecionar(linhas, nivel, item):
    if nivel in ('full', 'fora'):
        return [l for l in linhas if l['origem'] == nivel]
    if nivel == 'mlb':
        return [l for l in linhas if l['mlb'] == item]
    if nivel == 'codigo':
        return [l for l in linhas if l['codigo'] == item]
    return linhas


def _agrupar(linhas, chave):
    grupos = defaultdict(list)
    for l in linhas:
        grupos[chave(l)].append(l)
    return grupos


def _decimal_br(valor, casas=1):
    return f'{valor:.{casas}f}'.replace('.', ',')


def _percentual(parte, total):
    return (_decimal_br(parte / total * 100, 0) + '%') if total else '—'


def _estado_do_dia(dia, cob):
    if dia not in cob:
        return 'sem_dado'
    return 'ok' if dia_completo(dia, cob[dia]) else 'parcial'


def _s(n, singular, plural):
    return singular if n == 1 else plural


# ==================================================== a página ====================================================

# Função Objetivo: Tudo da tela a partir da query string (sku, q, periodo, nivel, item, visao; o antigo ?dias=7/30/90/180/365 ainda vale). Sem sku: busca + atalhos. Com sku: o histórico do produto.
def montar_pagina(parametros, base_url, hoje=None):
    hoje = hoje or datetime.now(FUSO).date()
    texto = (parametros.get('q') or '').strip()
    sku = (parametros.get('sku') or '').strip()
    periodo = normalizar_periodo(parametros.get('periodo') or parametros.get('dias'))
    nivel = parametros.get('nivel') if parametros.get('nivel') in NOMES_DOS_NIVEIS else 'produto'
    item = (parametros.get('item') or '').strip().upper()
    visao = parametros.get('visao') if parametros.get('visao') in VISOES else ''

    def url(**mudancas):
        atuais = {'sku': sku, 'periodo': periodo if periodo != PERIODO_PADRAO else None, 'nivel': nivel if nivel != 'produto' else None, 'item': item, 'visao': visao or None}
        atuais.update(mudancas)
        return url_da_tela(base_url, **atuais)

    def periodo_na_url(valor):
        return valor if valor != PERIODO_PADRAO else None

    pagina = {
        'texto': texto, 'sku': sku, 'periodo': periodo, 'periodo_e_padrao': periodo == PERIODO_PADRAO, 'dias_para_tras': dias_para_tras(periodo, hoje), 'nivel': nivel, 'hoje': hoje, 'url_limpar': base_url,
        'periodos': [{**p, 'ativo': p['chave'] == periodo, 'url': url(periodo=periodo_na_url(p['chave']))} for p in periodos_de_hoje(hoje)],
        'resultados': [], 'atalhos': [], 'produto': None,
    }
    if not sku:
        pagina['resultados'] = [{**r, 'url': url_da_tela(base_url, sku=r['sku'], periodo=periodo_na_url(periodo))} for r in buscar_produtos(texto)]
        pagina['atalhos'] = [{**a, 'url': url_da_tela(base_url, sku=a['sku'], periodo=periodo_na_url(periodo))} for a in skus_com_vendas()]
        return pagina

    pagina['produto'] = montar_vendas(sku, periodo, nivel, item, hoje, url, visao)
    pagina['nivel'] = pagina['produto']['nivel']
    return pagina


# ==================================================== escala de cor (por percentil) ====================================================

# * [EXPLICAÇÃO] → A cor de cada dia NÃO é proporcional ao maior valor (um dia atípico, por exemplo uma promoção, deixaria todo o resto pálido). Os
#                  dias COM venda são ordenados e divididos em 5 faixas do mesmo tamanho (percentis): cada cor pega cerca de 1/5 dos dias. Zero venda
#                  é à parte (nível 0). Se vários dias têm o mesmo valor, duas faixas podem coincidir: a legenda só mostra as faixas que existem.

# Função Objetivo: Os 5 cortes (limite superior de cada nível de cor, de 1 a 5) a partir dos valores positivos. Lista vazia se não há valor positivo.
def _cortes_de_percentil(valores):
    ordenados = sorted(v for v in valores if v > 0)
    n = len(ordenados)
    if not n:
        return []
    return [ordenados[-(-(n * k) // 5) - 1] for k in range(1, 6)]


# Função Objetivo: O nível de cor (0 a 5) de um valor. 0 = zero venda; 1 a 5 = faixa de percentil.
def _nivel_por_cortes(valor, cortes):
    if valor <= 0 or not cortes:
        return 0
    for nivel, corte in enumerate(cortes, start=1):
        if valor <= corte:
            return nivel
    return 5


# Função Objetivo: A legenda das faixas de cor ("2–18 un", "19–29 un"...), só das faixas que existem. `minimo` = o menor valor positivo.
def _legenda_dos_cortes(cortes, minimo):
    legenda, anterior = [], 0
    for nivel, corte in enumerate(cortes, start=1):
        if corte <= anterior:
            continue
        baixo = minimo if anterior == 0 else anterior + 1
        legenda.append({'nivel': nivel, 'texto': f'{numero(baixo)}–{numero(corte)} un' if baixo < corte else f'{numero(corte)} un'})
        anterior = corte
    return legenda


# ==================================================== calendário: dias, semanas e meses ====================================================

# Função Objetivo: Os dados de CADA dia do período (estado, unidades, pedidos, faturamento, cor, texto do balão). É a fonte única das duas visões
# (semanas e meses). Devolve (dados por dia, cortes de percentil, legenda das faixas de cor).
def _dados_dos_dias(dias_do_periodo, por_dia, estados, cob):
    de = dias_do_periodo[0]
    info = {}
    for d in dias_do_periodo:
        estado = estados[d]
        dado = por_dia.get(d)
        un = dado['un'] if dado else 0
        ped = len(dado['ped']) if dado else 0
        fat = dado['fat'] if dado else Decimal('0')
        if estado == 'sem_dado':
            titulo = f'{DIAS_DA_SEMANA[d.weekday()]} {d:%d/%m/%Y} — sem dado coletado (não é zero)'
        else:
            titulo = (f'{DIAS_DA_SEMANA[d.weekday()]} {d:%d/%m/%Y} — {numero(un)} un · {ped} {_s(ped, "pedido", "pedidos")} · {dinheiro(fat)}'
                      f' · coletado em {data_hora(cob[d])}' + (' · dia ainda incompleto (parcial)' if estado == 'parcial' else ''))
        info[d] = {'dia': d.day, 'rotulo': f'{d.day:02d}/{d.month:02d}' if (d.day == 1 or d == de) else f'{d.day:02d}', 'iso': f'{d:%Y-%m-%d}', 'dsem': d.weekday(),
                   'estado': estado, 'un': un, 'pedidos': ped, 'fat': fat, 'zero': estado == 'ok' and un == 0, 'titulo': titulo, 'nivel': 0}
    positivos = [v['un'] for v in info.values() if v['estado'] != 'sem_dado' and v['un'] > 0]
    cortes = _cortes_de_percentil(positivos)
    for v in info.values():
        if v['estado'] != 'sem_dado':
            v['nivel'] = _nivel_por_cortes(v['un'], cortes)
    legenda = _legenda_dos_cortes(cortes, min(positivos)) if positivos else []
    return info, cortes, legenda


# Função Objetivo: O detalhe de CADA dia (o card que abre ao clicar no dia do calendário) e a divisão Full / Fora do Full que aparece dentro da célula.
# Acrescenta em info[d] (as células das duas visões usam estes mesmos dicts): un_full, un_fora, un_sem, divisao (a célula mostra a divisão?) e div_txt.
# Devolve ({data ISO: detalhe com os textos já formatados}, a divisão vale neste nível?). Nos níveis "No Full" e "Fora do Full" a divisão não aparece:
# ela só repetiria o total. "Não-Full" na tela = "Fora do Full"; venda sem centro de estoque informado (node_id vazio) vira um terceiro item só quando existe.
LIMITE_ANUNCIOS_NO_CARD = 3
TAMANHO_DO_TITULO_NO_CARD = 46


def _pct_do_dia(parte, total):
    if not total or not parte:
        return '0%'
    p = parte / total * 100
    return '<1%' if p < 0.5 else f'{p:.0f}%'


def _detalhe_dos_dias(info, recorte, canceladas, mlbs, nivel, media, cob):
    com_divisao = nivel in ('produto', 'mlb', 'codigo')
    linhas_do_dia = _agrupar(recorte, lambda l: l['dia'])
    canceladas_do_dia = defaultdict(int)
    for l in canceladas:
        canceladas_do_dia[l['dia']] += l['qtd']
    detalhes = {}
    for d, v in info.items():
        linhas = linhas_do_dia.get(d, [])
        por_origem = _agrupar(linhas, lambda l: l['origem'])
        somas = {chave: _somar(por_origem.get(chave, [])) for chave in ('full', 'fora', 'indefinido')}
        un_full, un_fora, un_sem = somas['full']['un'], somas['fora']['un'], somas['indefinido']['un']
        tem_venda = v['estado'] != 'sem_dado' and v['un'] > 0
        v['un_full'], v['un_fora'], v['un_sem'] = un_full, un_fora, un_sem
        v['divisao'] = bool(com_divisao and tem_venda)
        v['div_txt'] = f'F {numero(un_full)} · N {numero(un_fora)}' + (f' · ? {numero(un_sem)}' if un_sem else '')

        detalhe = {'titulo': f'{DIAS_DA_SEMANA[v["dsem"]]}, {d:%d/%m/%Y}', 'estado': v['estado']}
        if v['estado'] == 'sem_dado':
            detalhe['estado_txt'] = 'Sem dado coletado'
            detalhes[v['iso']] = detalhe
            continue
        un_com_preco = sum(l['qtd'] for l in linhas if l['preco'] is not None)
        detalhe.update({
            'estado_txt': 'Dia completo' if v['estado'] == 'ok' else 'Dia ainda incompleto',
            'coletado': f'coletado em {data_hora(cob[d])}',
            'zero': v['zero'], 'un': numero(v['un']),
            'pedidos': f'{numero(v["pedidos"])} {_s(v["pedidos"], "pedido", "pedidos")}',
            'fat': dinheiro(v['fat']),
            'preco_medio': f'{dinheiro(v["fat"] / un_com_preco)}/un' if un_com_preco else '',
        })
        if v['un'] > 0:
            if com_divisao:
                linhas_origem = [('full', 'Full'), ('fora', 'Fora do Full')] + ([('indefinido', 'Sem origem informada')] if un_sem else [])
                detalhe['origens'] = [{'chave': chave, 'rotulo': rotulo, 'un': numero(somas[chave]['un']), 'pct': _pct_do_dia(somas[chave]['un'], v['un']),
                                       'barra': round(somas[chave]['un'] / v['un'] * 100, 1), 'pedidos': numero(somas[chave]['pedidos']),
                                       'fat': dinheiro(somas[chave]['fat'])} for chave, rotulo in linhas_origem]
            if nivel != 'mlb':
                por_anuncio = sorted(((m, sum(l['qtd'] for l in ls)) for m, ls in _agrupar(linhas, lambda l: l['mlb']).items()), key=lambda x: (-x[1], x[0]))
                curtos = []
                for m, un_m in por_anuncio[:LIMITE_ANUNCIOS_NO_CARD]:
                    nome = (mlbs.get(m) or {}).get('titulo') or ''
                    if len(nome) > TAMANHO_DO_TITULO_NO_CARD:
                        nome = nome[:TAMANHO_DO_TITULO_NO_CARD - 1].rstrip() + '…'
                    curtos.append({'mlb': m, 'un': numero(un_m), 'titulo': nome})
                detalhe['anuncios'] = curtos
                detalhe['anuncios_extra'] = max(0, len(por_anuncio) - LIMITE_ANUNCIOS_NO_CARD)
            por_hora = defaultdict(int)
            for l in linhas:
                if l['hora'] is not None and 0 <= l['hora'] <= 23:
                    por_hora[l['hora']] += l['qtd']
            if por_hora:
                hora = max(por_hora, key=lambda h: (por_hora[h], -h))
                detalhe['pico'] = f'{hora:02d}h ({numero(por_hora[hora])} un)'
        if canceladas_do_dia.get(d):
            detalhe['cancelados'] = f'{numero(canceladas_do_dia[d])} un'
        if v['estado'] == 'ok' and media:
            detalhe['media'] = f'{v["un"] / media * 100:.0f}% da média de {_decimal_br(media)} un/dia'
            if media >= 8 and v['un'] < 0.25 * media:
                detalhe['aviso'] = {'tipo': 'baixo', 'texto': 'Muito abaixo do normal: vale conferir se este dia foi coletado por inteiro (botão "Atualizar este dia").'}
            elif media >= 8 and v['un'] > 2.5 * media:
                detalhe['aviso'] = {'tipo': 'alto', 'texto': 'Muito acima do normal: confira se houve promoção ou campanha neste dia.'}
        elif v['estado'] == 'parcial':
            detalhe['aviso'] = {'tipo': 'parcial', 'texto': 'Coletado antes do fim do dia: o número ainda pode mudar. Use "Atualizar este dia" depois que ele acabar.'}
        detalhes[v['iso']] = detalhe
    return detalhes, com_divisao


def _lista_em_portugues(partes):
    return partes[0] if len(partes) == 1 else ', '.join(partes[:-1]) + ' e ' + partes[-1]


# Função Objetivo: Por que uma semana é "incompleta" (os motivos viram a nota do asterisco "*" embaixo do calendário).
def _motivos_da_semana(inicio, de, hoje, no_periodo, parciais, sem_dado):
    motivos = []
    if inicio < de:
        motivos.append(f'tem só {len(no_periodo)} {_s(len(no_periodo), "dia", "dias")} dentro do período')
    fim_da_semana = inicio + timedelta(days=6)
    if fim_da_semana > hoje:
        primeiro_futuro = hoje + timedelta(days=1)
        motivos.append(f'{fim_da_semana:%d/%m} ainda não aconteceu' if primeiro_futuro == fim_da_semana
                       else f'{primeiro_futuro:%d/%m} a {fim_da_semana:%d/%m} ainda não aconteceram')
    if parciais:
        datas = [f'{c["iso"][8:10]}/{c["iso"][5:7]}' for c in parciais]
        motivos.append(f'inclui o dia parcial {datas[0]}' if len(datas) == 1 else f'inclui os dias parciais {_lista_em_portugues(datas)}')
    if sem_dado:
        motivos.append(f'tem {len(sem_dado)} {_s(len(sem_dado), "dia", "dias")} sem dado')
    return motivos


# Função Objetivo: A visão em SEMANAS: uma linha por semana de calendário (segunda a domingo), a mais recente em cima. Devolve
# (semanas, médias por dia da semana, nota do asterisco, navegador de semanas).
#   Dia de semana: ok = coletado e o dia já acabou; parcial = coletado antes de acabar; sem_dado = nunca coletado (NÃO é zero);
#   fora = antes do período; futuro = depois de hoje. Só dias "ok" entram nas médias.
def _semanas(de, hoje, info):
    semanas = []
    inicio = de - timedelta(days=de.weekday())
    limite = hoje + timedelta(days=6 - hoje.weekday())
    while inicio <= limite:
        celulas, no_periodo = [], []
        for i in range(7):
            d = inicio + timedelta(days=i)
            if d < de:
                celulas.append({'estado': 'fora', 'dia': d.day})
            elif d > hoje:
                celulas.append({'estado': 'futuro', 'dia': d.day})
            else:
                celulas.append(info[d])
                no_periodo.append(info[d])
        ok = [c for c in no_periodo if c['estado'] == 'ok']
        parciais = [c for c in no_periodo if c['estado'] == 'parcial']
        sem_dado = [c for c in no_periodo if c['estado'] == 'sem_dado']
        total = sum(c['un'] for c in ok + parciais)
        motivos = _motivos_da_semana(inicio, de, hoje, no_periodo, parciais, sem_dado)
        dias_texto = f'{len(ok)} {_s(len(ok), "dia completo", "dias completos")}'
        if parciais:
            dias_texto += f' (+{len(parciais)} {_s(len(parciais), "parcial", "parciais")})'
        if sem_dado:
            dias_texto += f' · {len(sem_dado)} sem dado'
        fim_da_semana = inicio + timedelta(days=6)
        semanas.append({
            'rotulo': f'{inicio:%d/%m}–{fim_da_semana:%d/%m}', 'celulas': celulas, 'tem_dado': bool(ok or parciais), 'total_un': total,
            'total': numero(total) if (ok or parciais) else '—', 'incompleta': bool(motivos), 'motivos': motivos, 'dias_texto': dias_texto,
            'completa': len(ok) == 7, 'media': sum(c['un'] for c in ok) / len(ok) if ok else None,
        })
        inicio += timedelta(days=7)
    semanas.reverse()

    # Média por dia da semana (só dias completos).
    acumulado = defaultdict(lambda: [0, 0])
    for v in info.values():
        if v['estado'] == 'ok':
            acumulado[v['dsem']][0] += v['un']
            acumulado[v['dsem']][1] += 1
    medias = [{'rotulo': DIAS_DA_SEMANA[i], 'media': _decimal_br(acumulado[i][0] / acumulado[i][1]) if acumulado[i][1] else '—', 'n': acumulado[i][1]}
              for i in range(7)]

    nota = ''
    marcadas = [f'{s["rotulo"]} {_lista_em_portugues(s["motivos"])}' for s in semanas if s['incompleta'] and s['tem_dado']]
    if marcadas:
        nota = '* Semana incompleta no período: ' + '; '.join(marcadas) + '.'

    # Navegador: a barra segue o UN/DIA (não o total: as semanas têm tamanhos diferentes). Destaque (maior e menor ritmo) só entre semanas COMPLETAS.
    maior_media = max((s['media'] for s in semanas if s['media'] is not None), default=0)
    completas = [s for s in semanas if s['completa']]
    forte = max(completas, key=lambda s: s['media']) if len(completas) >= 2 else None
    fraca = min(completas, key=lambda s: s['media']) if len(completas) >= 2 else None
    if forte is not None and forte['media'] == fraca['media']:
        forte = fraca = None
    navegador = [{'rotulo': s['rotulo'], 'dias_texto': s['dias_texto'], 'un': numero(s['total_un']) if s['tem_dado'] else '—',
                  'media': _decimal_br(s['media']) if s['media'] is not None else '—',
                  'barra': round(s['media'] / maior_media * 100, 1) if (s['media'] is not None and maior_media) else 0,
                  'destaque': 'maior' if s is forte else ('menor' if s is fraca else '')} for s in semanas]
    return semanas, medias, nota, navegador


# Função Objetivo: A visão em MESES: um mini-calendário por mês tocado pelo período (o primeiro e o último podem ser só um trecho do mês) e o
# navegador de meses (unidades, UN/DIA dos dias completos e faturamento). Devolve (meses, navegador).
def _meses(de, hoje, info):
    meses = []
    ano, mes = de.year, de.month
    while (ano, mes) <= (hoje.year, hoje.month):
        primeiro = date(ano, mes, 1)
        ultimo = (date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)) - timedelta(days=1)
        ini, fim = max(primeiro, de), min(ultimo, hoje)
        dias_do_mes = [info[ini + timedelta(days=i)] for i in range((fim - ini).days + 1)]
        celulas = [{'estado': 'vazio'}] * ini.weekday() + dias_do_mes
        celulas += [{'estado': 'vazio'}] * (-len(celulas) % 7)
        ok = [c for c in dias_do_mes if c['estado'] == 'ok']
        com_dado = [c for c in dias_do_mes if c['estado'] != 'sem_dado']
        if ini > primeiro and fim < ultimo:
            recorte = f'dias {ini.day} a {fim.day}'
        elif ini > primeiro:
            recorte = f'a partir do dia {ini.day}'
        elif fim < ultimo:
            recorte = f'até o dia {fim.day}'
        else:
            recorte = ''
        meses.append({
            'chave': f'{ano}-{mes:02d}', 'nome': f'{MESES_ABREV[mes - 1]}/{str(ano)[2:]}', 'nome_longo': f'{MESES_ABREV[mes - 1]}/{ano}', 'recorte': recorte,
            'un': sum(c['un'] for c in com_dado), 'un_txt': numero(sum(c['un'] for c in com_dado)) if com_dado else '—', 'fat': sum((c['fat'] for c in com_dado), Decimal('0')), 'tem_dado': bool(com_dado),
            'media': sum(c['un'] for c in ok) / len(ok) if ok else None,
            'media_txt': _decimal_br(sum(c['un'] for c in ok) / len(ok)) if ok else '—',
            'linhas': [celulas[i:i + 7] for i in range(0, len(celulas), 7)],
        })
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    maior_media = max((m['media'] for m in meses if m['media'] is not None), default=0)
    navegador = [{'nome': m['nome'], 'recorte': m['recorte'], 'un': numero(m['un']) if m['tem_dado'] else '—',
                  'media': _decimal_br(m['media']) if m['media'] is not None else '—', 'fat': dinheiro(m['fat']) if m['tem_dado'] else '—',
                  'barra': round(m['media'] / maior_media * 100, 1) if (m['media'] is not None and maior_media) else 0} for m in meses]
    return meses, navegador


# ==================================================== leitura do ritmo (texto calculado) ====================================================

def _b(texto):
    return {'t': texto, 'b': True}


def _par(*partes):
    return [p if isinstance(p, dict) else {'t': p, 'b': False} for p in partes]


def _relacao_de_ritmo(razao):
    if 0.45 <= razao <= 0.56:
        return 'cerca da metade do ritmo do período'
    if razao >= 1.1:
        return f'{(razao - 1) * 100:.0f}% acima do ritmo do período'
    if razao <= 0.9:
        return f'{(1 - razao) * 100:.0f}% abaixo do ritmo do período'
    return 'em linha com o ritmo do período'


# Função Objetivo: A "leitura do ritmo": 4 a 6 frases calculadas dos próprios números da tela (nada é digitado). Cada frase é uma lista de trechos
# {'t': texto, 'b': negrito?}. Dia parcial nunca entra em média; semana/mês incompleto não disputa "melhor/mais fraco".
def _ritmo(visao, frente_ao_anterior, soma, media, comparacao, nota_comparacao, info, semanas, meses):
    paragrafos = []
    if media is not None:
        paragrafos.append(_par('O período totalizou ', _b(f'{numero(soma["un"])} unidades'), ' e ', _b(dinheiro(soma['fat'])),
                               ', com média de ', _b(f'{_decimal_br(media)} un/dia'), '.'))
    else:
        paragrafos.append(_par('O período totalizou ', _b(f'{numero(soma["un"])} unidades'), ' e ', _b(dinheiro(soma['fat'])),
                               '; ainda não há dia completo para calcular a média.'))
    if comparacao:
        pct = abs(comparacao['pct'])
        if comparacao['classe'] == 'igual':
            paragrafos.append(_par(f'O ritmo ficou estável {frente_ao_anterior} ({comparacao["media_ant"]} un/dia).'))
        else:
            verbo = 'subiu' if comparacao['classe'] == 'sobe' else 'caiu'
            paragrafos.append(_par(f'O ritmo {verbo} {pct:.0f}% {frente_ao_anterior} ({comparacao["media_ant"]} un/dia).'))
    elif nota_comparacao:
        paragrafos.append(_par(nota_comparacao))

    if visao == 'semanas':
        completas = [s for s in semanas if s['completa']]
        if len(completas) >= 2:
            forte, fraca = max(completas, key=lambda s: s['media']), min(completas, key=lambda s: s['media'])
            if forte is not fraca and forte['media'] != fraca['media']:
                paragrafos.append(_par('A melhor semana completa foi ', _b(forte['rotulo']), f', com {numero(forte["total_un"])} un ({_decimal_br(forte["media"])} un/dia); '
                                       'a mais fraca foi ', _b(fraca['rotulo']), f', com {numero(fraca["total_un"])} un ({_decimal_br(fraca["media"])} un/dia).'))
    else:
        inteiros = [m for m in meses if not m['recorte'] and m['media'] is not None]
        if len(inteiros) >= 2:
            melhor = max(inteiros, key=lambda m: m['un'])
            paragrafos.append(_par(_b(melhor['nome_longo']), f' foi o melhor mês completo, com {numero(melhor["un"])} un e {dinheiro(melhor["fat"])}.'))
        ok_dias = sorted(d for d, v in info.items() if v['estado'] == 'ok')
        if media and len(ok_dias) >= 28:
            janela = ok_dias[-14:]
            media_janela = sum(info[d]['un'] for d in janela) / len(janela)
            paragrafos.append(_par(f'Nos {len(janela)} dias completos mais recentes ({janela[0]:%d/%m} a {janela[-1]:%d/%m}): ', _b(f'{_decimal_br(media_janela)} un/dia'),
                                   f', {_relacao_de_ritmo(media_janela / media)}.'))

    zeros = [d for d, v in sorted(info.items()) if v['zero']]
    n_completos = sum(1 for v in info.values() if v['estado'] == 'ok')
    if not zeros:
        paragrafos.append(_par('Nenhum dia completo ficou sem vendas.'))
    elif len(zeros) == 1:
        paragrafos.append(_par('Apenas ', _b('1 dia completo'), f' ficou sem vendas: {zeros[0]:%d/%m}.'))
    elif len(zeros) <= 5:
        paragrafos.append(_par(_b(f'{len(zeros)} dias completos'), ' ficaram sem vendas: ' + ', '.join(f'{d:%d/%m}' for d in zeros) + '.'))
    else:
        paragrafos.append(_par(_b(f'{len(zeros)} dias completos'), f' ficaram sem vendas ({len(zeros) / n_completos * 100:.0f}% dos dias completos).'))

    parciais = [d for d, v in sorted(info.items()) if v['estado'] == 'parcial']
    if len(parciais) == 1:
        paragrafos.append(_par(_b(f'{parciais[0]:%d/%m} é parcial'), f' ({numero(info[parciais[0]]["un"])} un) e ficou fora da média.'))
    elif parciais:
        paragrafos.append(_par(_b('Dias parciais'), f' ({", ".join(f"{d:%d/%m}" for d in parciais)}) ficaram fora da média.'))
    n_sem_dado = sum(1 for v in info.values() if v['estado'] == 'sem_dado')
    if n_sem_dado:
        paragrafos.append(_par(_b(f'{n_sem_dado} {_s(n_sem_dado, "dia", "dias")} sem dado'), ' ficou fora das contas (não é zero).' if n_sem_dado == 1 else ' ficaram fora das contas (não é zero).'))
    return paragrafos


# ==================================================== mapa de calor ====================================================

# Função Objetivo: Mapa de calor hora × dia da semana: soma das unidades dos dias que têm coleta (dia sem coleta não entra: ausente não é zero).
def _mapa_de_calor(recorte, cob):
    grade = [[0] * 24 for _ in range(7)]
    for l in recorte:
        if l['dia'] in cob and 0 <= l['hora'] <= 23:
            grade[l['dia'].weekday()][l['hora']] += l['qtd']
    maximo = max((v for linha in grade for v in linha), default=0)
    cortes = _cortes_de_percentil([v for linha in grade for v in linha])
    por_hora = [sum(grade[w][h] for w in range(7)) for h in range(24)]
    return {
        'maximo': maximo, 'total': sum(por_hora),
        'linhas': [{'rotulo': DIAS_DA_SEMANA[w], 'total': numero(sum(grade[w])),
                    'celulas': [{'hora': h, 'un': grade[w][h], 'nivel': _nivel_por_cortes(grade[w][h], cortes),
                                 'titulo': f'{DIAS_DA_SEMANA[w]} {h:02d}h — {grade[w][h]} un'} for h in range(24)]} for w in range(7)],
        'picos': [{'hora': f'{h:02d}h', 'un': numero(por_hora[h])} for h in sorted(range(24), key=lambda h: (-por_hora[h], h))[:3] if por_hora[h] > 0],
    }


# ==================================================== tabelas por origem, MLB e Código ML ====================================================

def _tabela_origem(validas, soma_total, url, nivel):
    por_origem = _agrupar(validas, lambda l: l['origem'])
    tabela = []
    for chave, rotulo in (('full', 'No Full'), ('fora', 'Fora do Full'), ('indefinido', 'Sem origem informada')):
        s = _somar(por_origem.get(chave, []))
        if chave == 'indefinido' and not s['un']:
            continue
        tabela.append({'chave': chave, 'rotulo': rotulo, 'un': numero(s['un']), 'pedidos': numero(s['pedidos']), 'fat': dinheiro(s['fat']),
                       'pct': _percentual(s['un'], soma_total['un']), 'url': url(nivel=chave, item=None) if chave != 'indefinido' else '',
                       'ativo': nivel == chave})
    return tabela, _somar(por_origem.get('full', []))['un'], _somar(por_origem.get('indefinido', []))['un']


def _tabela_mlb(todos_mlbs, mlbs, validas, soma_total, coletas, de, hoje, url, nivel, item):
    tabela = []
    for mlb in todos_mlbs:
        s = _somar([l for l in validas if l['mlb'] == mlb])
        cob_mlb = cobertura(coletas, [mlb], de, hoje)
        tabela.append({
            'mlb': mlb, 'titulo': (mlbs.get(mlb) or {}).get('titulo') or '(anúncio fora do cadastro do produto)', 'no_cadastro': mlb in mlbs,
            'un': numero(s['un']), 'pedidos': numero(s['pedidos']), 'fat': dinheiro(s['fat']), 'pct': _percentual(s['un'], soma_total['un']),
            'sem_vendas': not s['un'], 'atualizado': data_hora(max(cob_mlb.values())) if cob_mlb else 'nunca',
            'url': url(nivel='mlb', item=mlb), 'ativo': nivel == 'mlb' and item == mlb,
        })
    return tabela


def _tabela_codigo(todos_codigos, mlbs, validas, soma_total, url, nivel, item):
    tabela = []
    for codigo in todos_codigos + (['indefinido'] if any(not l['codigo'] for l in validas) else []):
        escolhidas = [l for l in validas if (l['codigo'] or 'indefinido') == codigo]
        s = _somar(escolhidas)
        dele = sorted({m for m, d in mlbs.items() if any(c == codigo for _, c in d['variacoes'])} | {l['mlb'] for l in escolhidas})
        tabela.append({
            'codigo': codigo, 'mlbs': ', '.join(dele), 'un': numero(s['un']), 'pedidos': numero(s['pedidos']), 'fat': dinheiro(s['fat']),
            'pct': _percentual(s['un'], soma_total['un']), 'sem_vendas': not s['un'],
            'url': url(nivel='codigo', item=codigo) if codigo != 'indefinido' else '', 'ativo': nivel == 'codigo' and item == codigo,
        })
    return tabela


# ==================================================== o histórico de UM produto ====================================================

# Função Objetivo: O histórico de vendas de UM produto (SKU) no período pedido (`periodo` = semana, mes, 3meses, 6meses ou ano; de `de` até hoje), no
# nível pedido. LÊ SÓ DO BANCO. `dias` aqui é o total de dias de calendário do período (com hoje); varia com o mês (ex.: 3 meses = 90 a 93).
def montar_vendas(sku, periodo, nivel, item, hoje, url, visao=''):
    de, recortado = inicio_do_periodo(periodo, hoje)
    dias = (hoje - de).days + 1
    de_ant, ate_ant = periodo_anterior(periodo, hoje)
    tem_anterior = de_ant >= primeiro_dia_do_ml(hoje)
    inicio_da_carga = de_ant if tem_anterior else de
    cadastro = carregar_produto(sku)
    mlbs = cadastro['mlbs'] if cadastro else {}

    todas = _anotar(_carregar_linhas(sku, mlbs, inicio_da_carga, hoje), mlbs)
    atuais = [l for l in todas if l['dia'] >= de]
    anteriores = [l for l in todas if l['dia'] <= ate_ant and not l['cancelado']]
    validas = [l for l in atuais if not l['cancelado']]
    canceladas = [l for l in atuais if l['cancelado']]

    coletas = carregar_coletas(inicio_da_carga, hoje)
    dias_do_periodo = [de + timedelta(days=i) for i in range(dias)]
    dias_ant = [de_ant + timedelta(days=i) for i in range((ate_ant - de_ant).days + 1)]
    cob = cobertura(coletas, list(mlbs), de, hoje)
    cob_ant = cobertura(coletas, list(mlbs), de_ant, ate_ant) if tem_anterior else {}

    # ---- opções dos níveis "Por MLB" e "Por Código ML" (o que mais vendeu primeiro; os sem venda depois) ----
    un_mlb = {m: _somar(ls)['un'] for m, ls in _agrupar(validas, lambda l: l['mlb']).items()}
    un_codigo = {c: _somar(ls)['un'] for c, ls in _agrupar(validas, lambda l: l['codigo']).items() if c}
    todos_mlbs = sorted(set(mlbs) | set(un_mlb), key=lambda m: (-un_mlb.get(m, 0), m))
    todos_codigos = sorted({c for d in mlbs.values() for _, c in d['variacoes'] if c} | set(un_codigo), key=lambda c: (-un_codigo.get(c, 0), c))
    if nivel == 'mlb' and todos_mlbs:
        item = item if item in todos_mlbs else todos_mlbs[0]
    elif nivel == 'codigo' and todos_codigos:
        item = item if item in todos_codigos else todos_codigos[0]
    elif nivel in ('mlb', 'codigo'):
        nivel, item = 'produto', ''
    else:
        item = ''

    recorte = _selecionar(validas, nivel, item)
    recorte_ant = _selecionar(anteriores, nivel, item)
    recorte_canc = _selecionar(canceladas, nivel, item)
    soma = _somar(recorte)
    soma_total = _somar(validas)

    # ---- por dia (do recorte) e o que é "completo" ----
    por_dia = defaultdict(lambda: {'un': 0, 'ped': set(), 'fat': Decimal('0')})
    for l in recorte:
        por_dia[l['dia']]['un'] += l['qtd']
        por_dia[l['dia']]['ped'].add(l['pedido'])
        if l['preco'] is not None:
            por_dia[l['dia']]['fat'] += l['preco'] * l['qtd']
    estados = {d: _estado_do_dia(d, cob) for d in dias_do_periodo}
    completos = [d for d in dias_do_periodo if estados[d] == 'ok']
    sem_dado = [d for d in dias_do_periodo if estados[d] == 'sem_dado']
    un_completos = sum(por_dia[d]['un'] for d in completos if d in por_dia)
    dias_com_venda = [d for d in completos if d in por_dia and por_dia[d]['un'] > 0]
    media = un_completos / len(completos) if completos else None
    media_com_venda = un_completos / len(dias_com_venda) if dias_com_venda else None
    dias_sem_venda = len(completos) - len(dias_com_venda)
    melhor = max(((d, v['un'], v['fat']) for d, v in por_dia.items()), key=lambda x: (x[1], x[0]), default=None)

    # ---- comparação com o período anterior: só se o anterior inteiro foi coletado e já acabou ----
    anterior_completo = tem_anterior and all(d in cob_ant and dia_completo(d, cob_ant[d]) for d in dias_ant)
    comparacao = None
    if anterior_completo and media is not None:
        media_ant = _somar(recorte_ant)['un'] / len(dias_ant)
        if media_ant > 0:
            pct = (media - media_ant) / media_ant * 100
            classe = 'sobe' if pct > 0.5 else ('desce' if pct < -0.5 else 'igual')
            comparacao = {'texto': '0%' if classe == 'igual' else f'{pct:+.0f}%'.replace('-', '−'), 'classe': classe, 'pct': pct, 'media_ant': _decimal_br(media_ant),
                          'base': f'{_decimal_br(media_ant)} un/dia {frase_no_anterior(periodo)}'}
    if comparacao or anterior_completo:
        nota_comparacao = ''
    elif not tem_anterior:
        nota_comparacao = 'Sem comparação: o período anterior ficaria fora dos 12 meses que o Mercado Livre guarda.'
    else:
        nota_comparacao = 'Sem comparação: o período anterior ainda não foi coletado por inteiro.'

    tabela_origem, un_full, sem_origem = _tabela_origem(validas, soma_total, url, nivel)
    n_comp = len(completos)
    un_com_preco = sum(l['qtd'] for l in recorte if l['preco'] is not None)
    preco_medio = soma['fat'] / un_com_preco if un_com_preco else None
    un_canceladas = _somar(recorte_canc)['un']
    if media_com_venda is not None:
        sub_media = f'{_decimal_br(media_com_venda)} un nos {len(dias_com_venda)} {_s(len(dias_com_venda), "dia", "dias")} com venda'
    else:
        sub_media = 'nenhum dia completo com venda' if completos else 'nenhum dia completo coletado'
    cartoes = [
        {'icone': 'fa-cube', 'rotulo': 'Unidades vendidas', 'valor': numero(soma['un']), 'sub': f'{numero(soma["pedidos"])} {_s(soma["pedidos"], "pedido", "pedidos")}',
         'info': 'Soma das unidades vendidas no período (inclusive o dia parcial), sem cancelados. Pedidos = pedidos distintos.'},
        {'icone': 'fa-chart-simple', 'rotulo': 'Média por dia', 'valor': f'{_decimal_br(media)} un/dia' if media is not None else '—', 'sub': sub_media,
         'info': f'Unidades dos dias completos ÷ dias completos ({n_comp}). Dia sem venda entra como zero; dia parcial e dia sem dado ficam de fora.',
         'comparacao': comparacao, 'nota': nota_comparacao},
        {'icone': 'fa-sack-dollar', 'rotulo': 'Faturamento', 'valor': dinheiro(soma['fat']), 'dinheiro': True,
         'sub': f'preço médio: {dinheiro(preco_medio)}/un' if preco_medio is not None else 'sem vendas no recorte',
         'info': 'Preço × quantidade dos itens vendidos, sem cancelados.',
         'nota': f'{soma["sem_preco"]} {_s(soma["sem_preco"], "item sem preço, fora da conta", "itens sem preço, fora da conta")}' if soma['sem_preco'] else ''},
        {'icone': 'fa-calendar-day', 'rotulo': 'Melhor dia', 'valor': f'{melhor[0]:%d/%m/%Y}' if melhor else '—',
         'sub': f'{numero(melhor[1])} un · {dinheiro(melhor[2])}' if melhor else 'sem vendas'},
        {'tracejado': True, 'rotulo': 'Dias sem venda', 'valor': numero(dias_sem_venda), 'sub': 'dias completos com zero venda',
         'info': f'Dia completo (coletado depois que o dia acabou) sem nenhuma unidade vendida. São {n_comp} dias completos no período. Dia sem dado não é zero e não entra aqui.'},
        {'icone': 'fa-circle-xmark', 'rotulo': 'Cancelados', 'valor': f'{numero(un_canceladas)} un',
         'sub': f'{_decimal_br(un_canceladas / soma["un"] * 100)}% das unidades vendidas' if soma['un'] else 'sem vendas no recorte',
         'info': 'Unidades de pedidos cancelados: ficam fora de todas as contas da tela.'},
        {'icone': 'fa-warehouse', 'rotulo': '% no Full', 'valor': _percentual(un_full, soma_total['un']), 'sub': 'do produto inteiro',
         'info': 'Parte das unidades do produto inteiro (qualquer nível escolhido) cujo estoque saiu de um centro do Full.'},
    ]

    # ---- calendário: os dados de cada dia, a escala de cor e a visão escolhida (semanas OU meses) ----
    dados_dos_dias, _cortes, legenda_niveis = _dados_dos_dias(dias_do_periodo, por_dia, estados, cob)
    dias_json, divisao_dias = _detalhe_dos_dias(dados_dos_dias, recorte, recorte_canc, mlbs, nivel, media, cob)
    visao_efetiva = visao if visao in VISOES else ('meses' if dias >= DIAS_VISAO_MESES else 'semanas')
    semanas, medias_semana, nota_semanas, nav_semanas, meses, nav_meses = [], [], '', [], [], []
    if visao_efetiva == 'meses':
        meses, nav_meses = _meses(de, hoje, dados_dos_dias)
    else:
        semanas, medias_semana, nota_semanas, nav_semanas = _semanas(de, hoje, dados_dos_dias)
    ritmo = _ritmo(visao_efetiva, frase_frente_ao_anterior(periodo), soma, media, comparacao, nota_comparacao, dados_dos_dias, semanas, meses)
    dias_zerados = [{'texto': f'{d:%d/%m} · {DIAS_DA_SEMANA[d.weekday()].lower()}', 'titulo': f'{d:%d/%m/%Y}'} for d in dias_do_periodo if dados_dos_dias[d]['zero']]

    niveis = [{'chave': c, 'rotulo': r, 'dica': d, 'ativo': c == nivel, 'url': url(nivel=c if c != 'produto' else None, item=None)} for c, r, d in NIVEIS]
    if nivel == 'mlb':
        itens = [{'rotulo': m, 'sub': numero(un_mlb.get(m, 0)), 'ativo': m == item, 'url': url(nivel='mlb', item=m)} for m in todos_mlbs]
    elif nivel == 'codigo':
        itens = [{'rotulo': c, 'sub': numero(un_codigo.get(c, 0)), 'ativo': c == item, 'url': url(nivel='codigo', item=c)} for c in todos_codigos]
    else:
        itens = []

    aviso_limite_ml = (f'Limite do ML: o Mercado Livre só guarda pedidos a partir de {de:%d/%m/%Y}, por isso "{rotulo_do_periodo(periodo)}" começa aí '
                       f'e não em {voltar_unidade(hoje, periodo):%d/%m/%Y}.') if recortado else ''
    ultima = max(cob.values()) if cob else None
    cobertura_info = {
        'periodo': f'{de:%d/%m/%Y} a {hoje:%d/%m/%Y}', 'n_dias': dias, 'n_com_dado': len(cob), 'n_completos': n_comp, 'n_sem_dado': len(sem_dado),
        'faixas': _texto_das_faixas(_faixas(sorted(cob))), 'faixas_sem_dado': _texto_das_faixas(_faixas(sem_dado)),
        'ultima': data_hora(ultima) if ultima else '', 'nada_coletado': not cob, 'tudo_coletado': not sem_dado,
    }

    avisos = [aviso_limite_ml] if aviso_limite_ml else []
    if cadastro is None:
        avisos.append(f'O SKU {sku} não está no cadastro de Produto: aparecem só as vendas que já estão no banco com esse SKU.')
    elif not mlbs:
        avisos.append('O banco não liga nenhum MLB a este SKU: o botão "Atualizar produto" não tem o que consultar. Use "Coletar período da conta".')
    if sem_origem:
        avisos.append(f'{numero(sem_origem)} un vendidas sem centro de estoque (node_id) no pedido: não entram em "No Full" nem em "Fora do Full", só no Produto.')
    sem_codigo = sum(l['qtd'] for l in validas if not l['codigo'])
    if sem_codigo and mlbs:
        avisos.append(f'{numero(sem_codigo)} un vendidas em anúncios sem Código ML único no banco (ficam como "indefinido" no nível Por Código ML).')
    fora_do_cadastro = sorted(m for m in un_mlb if cadastro is not None and m not in mlbs)
    if fora_do_cadastro:
        avisos.append('Vendas deste SKU em MLB que o cadastro não liga ao produto: ' + ', '.join(fora_do_cadastro) + '.')
    if soma_total['sem_preco']:
        avisos.append(f'{soma_total["sem_preco"]} {_s(soma_total["sem_preco"], "item sem preço", "itens sem preço")} no pedido: o faturamento está um pouco abaixo do real.')

    return {
        'sku': sku, 'no_cadastro': cadastro is not None, 'titulo': cadastro['titulo'] if cadastro else '', 'marca': cadastro['marca'] if cadastro else '',
        'imagem': cadastro['imagem'] if cadastro else '', 'n_mlbs': len(mlbs), 'nivel': nivel, 'nivel_nome': NOMES_DOS_NIVEIS[nivel], 'item': item,
        'niveis': niveis, 'itens': itens, 'dias': dias, 'periodo': periodo, 'periodo_rotulo': rotulo_do_periodo(periodo), 'aviso_limite_ml': aviso_limite_ml,
        'cobertura': cobertura_info, 'cartoes': cartoes, 'semanas': semanas, 'medias_semana': medias_semana,
        'dias_json': dias_json, 'divisao_dias': divisao_dias,
        'divisao_sem_origem': any(c['un_sem'] for c in dados_dos_dias.values() if c['divisao']),
        'visao': visao_efetiva, 'url_visao_meses': url(visao='meses'), 'url_visao_semanas': url(visao='semanas'), 'legenda_niveis': legenda_niveis,
        'nota_semanas': nota_semanas, 'nav_semanas': nav_semanas, 'tem_destaque_semana': any(l['destaque'] for l in nav_semanas), 'meses': meses, 'nav_meses': nav_meses,
        'ritmo': ritmo, 'dias_zerados': dias_zerados[:MAX_DIAS_ZERADOS_NA_LISTA], 'dias_zerados_extra': max(0, len(dias_zerados) - MAX_DIAS_ZERADOS_NA_LISTA),
        'codigos_ml': todos_codigos[:MAX_CODIGOS_NO_CARTAO], 'codigos_ml_extra': max(0, len(todos_codigos) - MAX_CODIGOS_NO_CARTAO),
        'tabela_origem_total': {'un': numero(soma_total['un']), 'pedidos': numero(soma_total['pedidos']), 'fat': dinheiro(soma_total['fat']), 'pct': '100%'},
        'mapa_calor': _mapa_de_calor(recorte, cob), 'tabela_origem': tabela_origem,
        'tabela_mlb': _tabela_mlb(todos_mlbs, mlbs, validas, soma_total, coletas, de, hoje, url, nivel, item),
        'tabela_codigo': _tabela_codigo(todos_codigos, mlbs, validas, soma_total, url, nivel, item),
        'avisos': avisos, 'sem_vendas_no_recorte': not recorte,
    }
