# gestao_vendas/funcoes_auxiliares/vendas_ml.py
#
# Função Objetivo: Monta tudo o que a tela "Histórico de vendas" mostra, LENDO SÓ DO BANCO (VendaItemMercadoLivre, ColetaVendasMercadoLivre,
# Produto e as variações de anúncio): cartões-resumo, calendário semana × dia da semana, mapa de calor hora × dia da semana, quebra por
# origem (Full / fora do Full), por MLB e por Código ML. Nada aqui chama a API do Mercado Livre: quem chama é o coletor, por clique.
#
# REGRAS DO MATHEUS que moram aqui:
#   - Venda CANCELADA não conta (nem no dia da venda original): só soma o que não é status 'cancelled'. O cancelado aparece à parte.
#   - O dia da venda é date_created no horário de Brasília (dia_venda, gravado pelo coletor).
#   - Ausente não é zero: dia fora do que foi coletado aparece como "sem dado", nunca como "0 vendas". O que foi coletado vem do registro de
#     coletas (cobertura), por SKU.
#   - 5 níveis: 1 Produto (o SKU todo), 2 No Full, 3 Fora do Full, 4 Por MLB, 5 Por Código ML.
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

from integracao_mercado_livre.servicos.cobertura_vendas_ml import carregar_coletas, cobertura, dia_completo, mapa_de_dias as _mapa_de_dias  # noqa: F401
from mercado_livre.models import VariacaoAnuncioMercadoLivre, VendaItemMercadoLivre
from produtos.models import Produto

FUSO = ZoneInfo('America/Sao_Paulo')
PERIODOS = [7, 30, 90, 180, 365]
PERIODO_PADRAO = 90
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


# Função Objetivo: Nível de cor de 0 a 5. 0 = zero venda; 1 a 5 = proporcional ao maior valor da tela (sempre arredonda para cima, então qualquer venda tem cor).
def _intensidade(unidades, maximo):
    if unidades <= 0 or maximo <= 0:
        return 0
    return max(1, min(5, -(-5 * unidades // maximo)))


def _estado_do_dia(dia, cob):
    if dia not in cob:
        return 'sem_dado'
    return 'ok' if dia_completo(dia, cob[dia]) else 'parcial'


def _s(n, singular, plural):
    return singular if n == 1 else plural


# ==================================================== a página ====================================================

# Função Objetivo: Tudo da tela a partir da query string (sku, q, dias, nivel, item). Sem sku: busca + atalhos. Com sku: o histórico do produto.
def montar_pagina(parametros, base_url, hoje=None):
    hoje = hoje or datetime.now(FUSO).date()
    texto = (parametros.get('q') or '').strip()
    sku = (parametros.get('sku') or '').strip()
    dias = _inteiro(parametros.get('dias'), PERIODO_PADRAO)
    if dias not in PERIODOS:
        dias = PERIODO_PADRAO
    nivel = parametros.get('nivel') if parametros.get('nivel') in NOMES_DOS_NIVEIS else 'produto'
    item = (parametros.get('item') or '').strip().upper()

    def url(**mudancas):
        atuais = {'sku': sku, 'dias': dias if dias != PERIODO_PADRAO else None, 'nivel': nivel if nivel != 'produto' else None, 'item': item}
        atuais.update(mudancas)
        return url_da_tela(base_url, **atuais)

    def dias_na_url(valor):
        return valor if valor != PERIODO_PADRAO else None

    pagina = {
        'texto': texto, 'sku': sku, 'dias': dias, 'nivel': nivel, 'hoje': hoje, 'url_limpar': base_url,
        'periodos': [{'valor': p, 'ativo': p == dias, 'url': url(dias=dias_na_url(p))} for p in PERIODOS],
        'resultados': [], 'atalhos': [], 'produto': None,
    }
    if not sku:
        pagina['resultados'] = [{**r, 'url': url_da_tela(base_url, sku=r['sku'], dias=dias_na_url(dias))} for r in buscar_produtos(texto)]
        pagina['atalhos'] = [{**a, 'url': url_da_tela(base_url, sku=a['sku'], dias=dias_na_url(dias))} for a in skus_com_vendas()]
        return pagina

    pagina['produto'] = montar_vendas(sku, dias, nivel, item, hoje, url)
    pagina['nivel'] = pagina['produto']['nivel']
    return pagina


# ==================================================== calendário e mapa de calor ====================================================

# Função Objetivo: O calendário: uma linha por semana (segunda a domingo), a semana mais recente em cima. Cada dia tem estado:
#   ok = coletado e o dia já acabou; parcial = coletado, mas o dia ainda não acabou (hoje); sem_dado = nunca coletado (NÃO é zero); fora = fora do período.
# Devolve (semanas, médias por dia da semana). A média por dia da semana só usa dias "ok".
def _calendario(de, hoje, por_dia, estados, cob):
    maximo = max((v['un'] for d, v in por_dia.items() if estados.get(d) in ('ok', 'parcial')), default=0)
    semanas, acumulado = [], defaultdict(lambda: [0, 0])
    cursor = de - timedelta(days=de.weekday())
    fim = hoje + timedelta(days=6 - hoje.weekday())
    while cursor <= fim:
        celulas, total, incompleta, algum_dado = [], 0, False, False
        for i in range(7):
            d = cursor + timedelta(days=i)
            if d < de or d > hoje:
                celulas.append({'estado': 'fora', 'dia': d.day, 'iso': ''})
                continue
            estado = estados[d]
            un, ped = (por_dia[d]['un'], len(por_dia[d]['ped'])) if d in por_dia else (0, 0)
            if estado == 'sem_dado':
                incompleta = True
                titulo = f'{DIAS_DA_SEMANA[i]} {d:%d/%m} — sem dado coletado (não é zero)'
            else:
                algum_dado = True
                total += un
                if estado == 'parcial':
                    incompleta = True
                else:
                    acumulado[i][0] += un
                    acumulado[i][1] += 1
                titulo = (f'{DIAS_DA_SEMANA[i]} {d:%d/%m} — {un} un · {ped} {_s(ped, "pedido", "pedidos")} · coletado em {data_hora(cob[d])}'
                          + (' (dia ainda incompleto)' if estado == 'parcial' else ''))
            celulas.append({'estado': estado, 'dia': d.day, 'mes': f'{d:%d/%m}' if (d.day == 1 or d == de) else '', 'iso': f'{d:%Y-%m-%d}',
                            'un': un, 'pedidos': ped, 'nivel': _intensidade(un, maximo) if estado != 'sem_dado' else 0, 'titulo': titulo, 'hoje': d == hoje})
        semanas.append({'rotulo': f'{max(cursor, de):%d/%m} – {min(cursor + timedelta(days=6), hoje):%d/%m}', 'celulas': celulas,
                        'total': numero(total) if algum_dado else '—', 'incompleta': incompleta, 'tem_dado': algum_dado})
        cursor += timedelta(days=7)
    semanas.reverse()
    medias = [{'rotulo': DIAS_DA_SEMANA[i], 'media': _decimal_br(acumulado[i][0] / acumulado[i][1]) if acumulado[i][1] else '—', 'n': acumulado[i][1]}
              for i in range(7)]
    return semanas, medias


# Função Objetivo: Mapa de calor hora × dia da semana: soma das unidades dos dias que têm coleta (dia sem coleta não entra: ausente não é zero).
def _mapa_de_calor(recorte, cob):
    grade = [[0] * 24 for _ in range(7)]
    for l in recorte:
        if l['dia'] in cob and 0 <= l['hora'] <= 23:
            grade[l['dia'].weekday()][l['hora']] += l['qtd']
    maximo = max((v for linha in grade for v in linha), default=0)
    por_hora = [sum(grade[w][h] for w in range(7)) for h in range(24)]
    return {
        'maximo': maximo, 'total': sum(por_hora),
        'linhas': [{'rotulo': DIAS_DA_SEMANA[w], 'total': numero(sum(grade[w])),
                    'celulas': [{'hora': h, 'un': grade[w][h], 'nivel': _intensidade(grade[w][h], maximo),
                                 'titulo': f'{DIAS_DA_SEMANA[w]} {h:02d}h — {grade[w][h]} un'} for h in range(24)]} for w in range(7)],
        'picos': [{'hora': f'{h:02d}h', 'un': numero(por_hora[h])} for h in sorted(range(24), key=lambda h: (-por_hora[h], h))[:3] if por_hora[h] > 0],
    }


# ==================================================== tabelas por origem, MLB e Código ML ====================================================

def _tabela_origem(validas, soma_total, url, nivel):
    por_origem = _agrupar(validas, lambda l: l['origem'])
    tabela = []
    for chave, rotulo in (('full', 'No Full'), ('fora', 'Fora do Full'), ('indefinido', 'Origem indefinida')):
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

# Função Objetivo: O histórico de vendas de UM produto (SKU) nos últimos `dias` dias, no nível pedido. LÊ SÓ DO BANCO.
def montar_vendas(sku, dias, nivel, item, hoje, url):
    de = hoje - timedelta(days=dias - 1)
    de_ant, ate_ant = de - timedelta(days=dias), de - timedelta(days=1)
    cadastro = carregar_produto(sku)
    mlbs = cadastro['mlbs'] if cadastro else {}

    todas = _anotar(_carregar_linhas(sku, mlbs, de_ant, hoje), mlbs)
    atuais = [l for l in todas if l['dia'] >= de]
    anteriores = [l for l in todas if l['dia'] <= ate_ant and not l['cancelado']]
    validas = [l for l in atuais if not l['cancelado']]
    canceladas = [l for l in atuais if l['cancelado']]

    coletas = carregar_coletas(de_ant, hoje)
    dias_do_periodo = [de + timedelta(days=i) for i in range(dias)]
    dias_ant = [de_ant + timedelta(days=i) for i in range(dias)]
    cob = cobertura(coletas, list(mlbs), de, hoje)
    cob_ant = cobertura(coletas, list(mlbs), de_ant, ate_ant)

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
    por_dia = defaultdict(lambda: {'un': 0, 'ped': set()})
    for l in recorte:
        por_dia[l['dia']]['un'] += l['qtd']
        por_dia[l['dia']]['ped'].add(l['pedido'])
    estados = {d: _estado_do_dia(d, cob) for d in dias_do_periodo}
    completos = [d for d in dias_do_periodo if estados[d] == 'ok']
    sem_dado = [d for d in dias_do_periodo if estados[d] == 'sem_dado']
    media = sum(por_dia[d]['un'] for d in completos if d in por_dia) / len(completos) if completos else None
    dias_sem_venda = sum(1 for d in completos if d not in por_dia)
    melhor = max(((d, v['un']) for d, v in por_dia.items()), key=lambda x: (x[1], x[0]), default=None)

    # ---- comparação com o período anterior: só se o anterior inteiro foi coletado e já acabou ----
    anterior_completo = all(d in cob_ant and dia_completo(d, cob_ant[d]) for d in dias_ant)
    comparacao = None
    if anterior_completo and media is not None:
        media_ant = _somar(recorte_ant)['un'] / dias
        if media_ant > 0:
            pct = (media - media_ant) / media_ant * 100
            comparacao = {'texto': f'{pct:+.0f}%', 'classe': 'sobe' if pct > 0.5 else ('desce' if pct < -0.5 else 'igual'),
                          'base': f'{_decimal_br(media_ant)} un/dia nos {dias} dias anteriores'}
    nota_comparacao = '' if (comparacao or anterior_completo) else 'Sem comparação: o período anterior ainda não foi coletado por inteiro.'

    tabela_origem, un_full, sem_origem = _tabela_origem(validas, soma_total, url, nivel)
    n_comp = len(completos)
    cartoes = [
        {'rotulo': 'Unidades vendidas', 'valor': numero(soma['un']), 'sub': f'{numero(soma["pedidos"])} {_s(soma["pedidos"], "pedido", "pedidos")} · {dias} dias', 'destaque': True},
        {'rotulo': 'Média por dia', 'valor': _decimal_br(media) if media is not None else '—',
         'sub': f'em {n_comp} {_s(n_comp, "dia completo", "dias completos")}' if completos else 'nenhum dia completo coletado',
         'comparacao': comparacao, 'nota': nota_comparacao},
        {'rotulo': 'Faturamento', 'valor': dinheiro(soma['fat']), 'dinheiro': True,
         'sub': f'{soma["sem_preco"]} item sem preço, fora da conta' if soma['sem_preco'] else 'preço × quantidade, sem cancelados'},
        {'rotulo': 'Melhor dia', 'valor': data_curta(melhor[0]) if melhor else '—', 'sub': f'{numero(melhor[1])} un' if melhor else 'sem vendas'},
        {'rotulo': 'Dias sem venda', 'valor': numero(dias_sem_venda), 'sub': f'de {n_comp} {_s(n_comp, "dia completo", "dias completos")}'},
        {'rotulo': 'Cancelados', 'valor': numero(_somar(recorte_canc)['un']), 'sub': 'un fora da conta'},
        {'rotulo': '% no Full', 'valor': _percentual(un_full, soma_total['un']), 'sub': 'das unidades do produto'},
    ]

    semanas, medias_semana = _calendario(de, hoje, por_dia, estados, cob)

    niveis = [{'chave': c, 'rotulo': r, 'dica': d, 'ativo': c == nivel, 'url': url(nivel=c if c != 'produto' else None, item=None)} for c, r, d in NIVEIS]
    if nivel == 'mlb':
        itens = [{'rotulo': m, 'sub': numero(un_mlb.get(m, 0)), 'ativo': m == item, 'url': url(nivel='mlb', item=m)} for m in todos_mlbs]
    elif nivel == 'codigo':
        itens = [{'rotulo': c, 'sub': numero(un_codigo.get(c, 0)), 'ativo': c == item, 'url': url(nivel='codigo', item=c)} for c in todos_codigos]
    else:
        itens = []

    ultima = max(cob.values()) if cob else None
    cobertura_info = {
        'periodo': f'{de:%d/%m/%Y} a {hoje:%d/%m/%Y}', 'n_dias': dias, 'n_com_dado': len(cob), 'n_completos': n_comp, 'n_sem_dado': len(sem_dado),
        'faixas': _texto_das_faixas(_faixas(sorted(cob))), 'faixas_sem_dado': _texto_das_faixas(_faixas(sem_dado)),
        'ultima': data_hora(ultima) if ultima else '', 'nada_coletado': not cob, 'tudo_coletado': not sem_dado,
    }

    avisos = []
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
        'niveis': niveis, 'itens': itens, 'dias': dias, 'cobertura': cobertura_info, 'cartoes': cartoes, 'semanas': semanas, 'medias_semana': medias_semana,
        'mapa_calor': _mapa_de_calor(recorte, cob), 'tabela_origem': tabela_origem,
        'tabela_mlb': _tabela_mlb(todos_mlbs, mlbs, validas, soma_total, coletas, de, hoje, url, nivel, item),
        'tabela_codigo': _tabela_codigo(todos_codigos, mlbs, validas, soma_total, url, nivel, item),
        'avisos': avisos, 'sem_vendas_no_recorte': not recorte,
    }
