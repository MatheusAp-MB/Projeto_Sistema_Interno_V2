# gestao_vendas/funcoes_auxiliares/vendas_ml.py
#
# Função Objetivo: Monta tudo o que a tela "Histórico de vendas" mostra QUANDO UM PRODUTO (SKU) ESTÁ ABERTO (sem SKU, a tela mostra a LISTA, que mora em
# lista_vendas_ml.py e reaproveita as regras deste arquivo), LENDO SÓ DO BANCO (VendaItemMercadoLivre, ColetaVendasMercadoLivre,
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

import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from dotenv import load_dotenv

from core.empresa import PREFIXO_ENV_POR_EMPRESA, EmpresaNaoDefinidaError, obter_empresa_ativa
from integracao_mercado_livre.servicos.cobertura_vendas_ml import (  # noqa: F401
    PERIODO_PADRAO, carregar_coletas, cobertura, dia_completo, dias_para_tras, frase_frente_ao_anterior, frase_no_anterior, inicio_do_periodo,
    normalizar_periodo, periodo_anterior, periodos_de_hoje, primeiro_dia_do_ml, rotulo_do_periodo, voltar_unidade)
from mercado_livre.funcoes_auxiliares.badges import (
    BADGE_PADRAO, BADGES_CATALOGO, BADGES_LOGISTICA, BADGES_STATUS, BADGES_TIPO_ANUNCIO, badge_de, badge_flex,
)
from mercado_livre.models import TipoDeAnuncioMercadoLivre, VariacaoAnuncioMercadoLivre, VendaItemMercadoLivre
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

# Função Objetivo: Decide se UMA venda saiu do Full ('full'), de fora do Full ('fora') ou se a origem não dá para saber ('indefinido'). Esta é a ÚNICA
# função que decide isso: se a regra mudar, muda aqui.
#
# A REGRA, na ordem:
#   1) tem store_id                                            → fora do Full
#   2) tem node_id do nó PRÓPRIO ("BRP" + código do vendedor)   → fora do Full
#   3) tem qualquer outro node_id                              → Full
#   4) sem node_id e sem store_id                              → fora do Full só quando `fora_pela_logistica` é verdadeiro (ver _mlbs_fora_pela_logistica);
#                                                                senão 'indefinido' ("Sem origem informada"): sem chute
#
# * [EXPLICAÇÃO] → CONFIRMADA com envios reais (conta Magazine, produto de teste): na medição de 10/10/2026 (20 envios de 1 dia de pedidos da conta), os 19 de
#                  nó de centro deram fulfillment e o 1 de nó próprio deu cross_docking; em 11/10/2026, 60 envios (script confirmar_origem_das_vendas_pelos_envios):
#                  30 de "Full" = fulfillment em 30 de 30 (inclui BRPE01 e BRPR01) e 30 de "fora" = cross_docking em 30 de 30 (15 com nó próprio/loja e 15 sem origem).
#                  Nenhum envio de Flex (self_service) apareceu na amostra: se um dia aparecer Flex saindo de um centro do Full, a regra 3 precisa mudar.
# * [EXPLICAÇÃO] → "BRP" sozinho NÃO é o nó próprio: BRPE01 e BRPR01 são centros do Full (envio = fulfillment). O nó próprio é "BRP" + código do vendedor
#                  (+ "1"), e o código vem do .env ({MB|SV}_USER_ID, o mesmo da API). Por isso a regra 2 testa "BRP" + código, nunca só "BRP".
# * [EXPLICAÇÃO] → Regra 4: antes de 26/03/2026 o ML mandava o pedido de Coleta SEM stock (node_id e store_id vazios; o envio também não tem origin.node),
#                  por isso esses pedidos chegaram sem origem. A regra só os manda para "fora" quando o anúncio HOJE não é Full e o MLB nunca vendeu por
#                  centro do Full; o que não passa nesse teste continua "Sem origem informada" (10 un de 16.293 no produto de teste).
PREFIXO_DO_NO_PROPRIO = 'BRP'


def classificar_origem(node_id, store_id, no_proprio, fora_pela_logistica=False):
    if store_id:
        return 'fora'
    if node_id:
        return 'fora' if node_id.upper().startswith(no_proprio) else 'full'
    return 'fora' if fora_pela_logistica else 'indefinido'


# Função Objetivo: O código do vendedor (user_id) da conta, lido do .env ({MB|SV}_USER_ID, a mesma variável que a API do Mercado Livre usa). Lê uma vez por conta.
@lru_cache(maxsize=None)
def _codigo_do_vendedor(conta):
    load_dotenv()
    codigo = (os.getenv(f'{conta}_USER_ID') or '').strip()
    if not codigo:
        raise RuntimeError(
            f'{conta}_USER_ID não encontrado no .env da raiz do repo — a tela de vendas precisa dele para reconhecer o nó de estoque próprio '
            f'(BRP + código do vendedor). Adicione a linha {conta}_USER_ID=seu_user_id_aqui.'
        )
    return codigo


# Função Objetivo: O começo do node_id do estoque PRÓPRIO da conta ativa ("BRP" + código do vendedor), em maiúsculas: é o que a regra 2 de classificar_origem compara.
def prefixo_do_no_proprio():
    empresa = obter_empresa_ativa()
    if empresa is None:
        raise EmpresaNaoDefinidaError(
            'Nenhuma empresa ativa — a regra de origem das vendas precisa saber a conta (MB/SV) para achar o nó de estoque próprio. '
            'Chame definir_empresa_ativa() antes.'
        )
    return (PREFIXO_DO_NO_PROPRIO + _codigo_do_vendedor(PREFIXO_ENV_POR_EMPRESA[empresa])).upper()


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

# Função Objetivo: Devolve o endereço só se for seguro para a tela abrir (https). O Mercado Livre serve a mesma imagem por https, então um "http://" vira
# "https://" (senão o navegador bloquearia a foto numa página https). Qualquer outra coisa (vazio, "javascript:", etc.) vira vazio.
def _url_segura(url):
    url = (url or '').strip() if isinstance(url, str) else ''
    if url.startswith('http://'):
        url = 'https://' + url[len('http://'):]
    return url if url.startswith('https://') else ''


# Função Objetivo: O que a tela precisa saber de UM anúncio (MLB) além das variações: título, link no ML, foto e o "tipo" (status, tipo, logística, Flex e papel
# no catálogo). Tudo já está no banco (é o mesmo dado do Hub de Anúncios): nenhuma chamada nova ao Mercado Livre.
def _dados_do_anuncio(anuncio):
    tipo = anuncio.tipo_de_anuncio
    return {'titulo': anuncio.titulo_anuncio or '', 'variacoes': [], 'link': _url_segura(anuncio.permalink), 'imagem': '',
            'tipo': None if tipo is None else {'status': tipo.status, 'tipo_anuncio': tipo.tipo_anuncio, 'tipo_logistico': tipo.tipo_logistico,
                                                'classificacao_catalogo': tipo.classificacao_catalogo, 'flex': bool(tipo.flex)}}


# Função Objetivo: O cadastro do SKU e os MLBs dele (com título, foto, selos e as variações → Código ML). None se o SKU não está em Produto.
def carregar_produto(sku):
    produto = Produto.objects.filter(sku=sku).first()
    if produto is None:
        return None
    mlbs = {}
    variacoes = VariacaoAnuncioMercadoLivre.objects.filter(produto__sku=sku).select_related('anuncio', 'anuncio__tipo_de_anuncio')
    for v in variacoes:
        mlb = v.anuncio.mlb
        if not mlb:
            continue
        item = mlbs.setdefault(mlb, _dados_do_anuncio(v.anuncio))
        item['variacoes'].append((str(v.variacao_id or ''), (v.inventory_id or '').strip().upper()))
        # * [EXPLICAÇÃO] → A foto é do anúncio: vale a da primeira variação que tiver (a imagem principal, como no Hub; sem ela, a miniatura).
        if not item['imagem']:
            item['imagem'] = _url_segura(v.imagem_principal_url) or _url_segura(v.thumbnail_url)
    return {'titulo': produto.titulo, 'marca': produto.marca or '', 'imagem': produto.imagem_url or '', 'mlbs': mlbs}


# Função Objetivo: Os "selos" de um anúncio, na MESMA ordem e com as MESMAS cores do Hub de Anúncios: status, tipo, logística, Flex e papel no catálogo.
# * [EXPLICAÇÃO] → Rótulo, classe de cor e ícone vêm do registro único (mercado_livre/funcoes_auxiliares/badges.py): se uma cor mudar lá, muda aqui junto.
#                  Valor que o registro não conhece não vira selo "—" (só poluiria): simplesmente não aparece. Os selos dizem como o anúncio está HOJE
#                  (última importação do banco), não como estava no dia da venda; por isso o painel avisa isso embaixo da lista.
def _selos_do_anuncio(tipo):
    if not tipo:
        return []
    candidatos = (('Status', badge_de(BADGES_STATUS, tipo['status'])),
                  ('Tipo do anúncio', badge_de(BADGES_TIPO_ANUNCIO, tipo['tipo_anuncio'])),
                  ('Logística', badge_de(BADGES_LOGISTICA, tipo['tipo_logistico'])),
                  ('Flex', badge_flex(bool(tipo['flex']))),
                  ('Papel no catálogo', badge_de(BADGES_CATALOGO, tipo['classificacao_catalogo'])))
    return [{'rotulo': b['label'], 'classe': b['classe'], 'icone': b['icone'] or '', 'dica': f'{categoria}: {b["label"]}'}
            for categoria, b in candidatos if b is not BADGE_PADRAO]


# Função Objetivo: O que o painel do dia precisa de cada MLB, UMA vez só (em vez de repetir nos 365 dias): título, foto, link e selos. Inclui o MLB que
# vendeu mas não está no cadastro do produto (aí só aparece o que se sabe: sem foto nem selos, e "no_cadastro" falso).
def _anuncios_para_o_painel(mlbs, mlbs_vendidos):
    saida = {}
    for mlb in set(mlbs) | set(mlbs_vendidos):
        item = mlbs.get(mlb)
        saida[mlb] = {'titulo': (item or {}).get('titulo') or '', 'no_cadastro': item is not None, 'imagem': (item or {}).get('imagem') or '',
                      'link': (item or {}).get('link') or '', 'selos': _selos_do_anuncio((item or {}).get('tipo'))}
    return saida


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
def _carregar_linhas(sku, mlbs, de, ate, extras=()):
    filtro = Q(seller_sku=sku)
    if mlbs:
        filtro |= Q(seller_sku='', mlb__in=list(mlbs))
    # * [EXPLICAÇÃO] → `extras` = campos a MAIS, pedidos só por quem precisa deles. O instante exato da venda ('criado_em_ml') é pedido pela lista de pedidos do dia
    #                  e pela tela inteira (o bloco "Preços do dia" mostra a hora/minuto da primeira e da última venda de cada preço). com_desconto, catalogo e
    #                  tipo_anuncio alimentam o bloco de preços e sinais do painel do dia.
    return list(VendaItemMercadoLivre.objects.filter(filtro, dia_venda__range=(de, ate)).values(
        'order_id', 'seller_sku', 'mlb', 'variation_id', 'quantidade', 'preco_unitario', 'status', 'dia_venda', 'hora_venda', 'node_id', 'store_id',
        'com_desconto', 'catalogo', 'tipo_anuncio', *extras))


# Função Objetivo: Os MLBs cujas vendas SEM nó e SEM loja a regra 4 de classificar_origem manda para "fora do Full": anúncio que HOJE não é Full (logística do
# cadastro, já no banco) E que NUNCA vendeu por centro do Full (qualquer data, sem cancelados). Zero chamada à API; 1 consulta pequena só quando o produto tem
# algum anúncio que não é Full (produto 100% Full não consulta nada).
# * [EXPLICAÇÃO] → "Nunca vendeu por centro do Full" olha o histórico inteiro do MLB no banco (não só o período da tela), para o mesmo pedido ter a mesma origem
#                  em qualquer período. Anúncio sem cadastro ou sem logística não decide (fica "Sem origem informada").
def _mlbs_fora_pela_logistica(mlbs, no_proprio):
    full = TipoDeAnuncioMercadoLivre.TipoLogistico.FULL
    hoje_fora_do_full = {mlb for mlb, d in mlbs.items() if (d.get('tipo') or {}).get('tipo_logistico') and d['tipo']['tipo_logistico'] != full}
    if not hoje_fora_do_full:
        return set()
    ja_venderam_pelo_full = set(
        VendaItemMercadoLivre.objects.filter(mlb__in=list(hoje_fora_do_full), store_id='').exclude(node_id='').exclude(status=STATUS_CANCELADO)
        .exclude(node_id__istartswith=no_proprio).values_list('mlb', flat=True).distinct())
    return hoje_fora_do_full - ja_venderam_pelo_full


# Função Objetivo: Acrescenta a cada linha a origem (Full / fora / indefinida) e o Código ML, e troca os nomes dos campos por nomes curtos.
def _anotar(linhas, mlbs):
    no_proprio = prefixo_do_no_proprio()
    fora_pela_logistica = _mlbs_fora_pela_logistica(mlbs, no_proprio)
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
            'origem': classificar_origem(l['node_id'], l['store_id'], no_proprio, l['mlb'] in fora_pela_logistica),
            # Para o painel do dia: variação (preço por variação), as duas tags do pedido, o tipo do anúncio e o instante exato (só vem quando pedido em `extras`).
            # `seg` = o mesmo instante em segundos desde 00:00 de Brasília (ordenar vendas do mesmo dia com precisão; a tela mostra só hora:minuto).
            'variacao': l['variation_id'], 'desconto': bool(l['com_desconto']), 'catalogo': bool(l['catalogo']), 'tipo': l['tipo_anuncio'],
            'quando': l.get('criado_em_ml'), 'seg': _segundos_do_dia(l.get('criado_em_ml')),
        })
    return saida


# Função Objetivo: O instante da venda em segundos desde 00:00 do horário de Brasília (None quando a linha veio sem o instante exato).
def _segundos_do_dia(quando):
    if quando is None:
        return None
    t = timezone.localtime(quando, FUSO)
    return t.hour * 3600 + t.minute * 60 + t.second


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


# Função Objetivo: As unidades vendidas POR DIA de um produto (SKU) num recorte entre duas datas, mais o estado de cada dia, para quem precisa do RITMO de vendas sem montar a
# tela de histórico (hoje: a tela "Ruptura de estoque", app gestao_ruptura). LÊ SÓ DO BANCO; nunca chama o Mercado Livre.
# O recorte é o `nivel` ('produto' = tudo, 'full', 'fora', 'mlb' ou 'codigo'; nestes dois últimos `item` é o MLB ou o Código ML, como em _selecionar) e, opcionalmente, a
# `origem` ('full' ou 'fora') aplicada por cima dele (ex.: nivel 'mlb' + origem 'full' = só o que aquele anúncio vendeu saindo do Full). Sem `item` e `origem` é o de sempre.
# Devolve: `cadastro` (carregar_produto; None se o SKU não está em Produto), `por_dia` ({dia: unidades}, só dias com venda), `estados` ({dia: 'ok' (dia completo) |
# 'parcial' (hoje, ou coletado antes do dia acabar) | 'sem_dado' (nunca coletado)}) e `coletado_em` (a coleta mais recente que cobre o período; None se nada foi coletado).
# * [EXPLICAÇÃO] → Mesmas regras da tela de histórico: venda cancelada não conta, a origem vem de classificar_origem (única regra) e "ausente não é zero": dia sem coleta é
#                  'sem_dado', nunca 0. Quem calcula uma média por dia deve usar só os dias 'ok' (hoje e dia parcial distorcem).
def unidades_por_dia(sku, nivel, de, ate, item='', origem=''):
    cadastro = carregar_produto(sku)
    mlbs = cadastro['mlbs'] if cadastro else {}
    linhas = _anotar(_carregar_linhas(sku, mlbs, de, ate), mlbs)
    recorte = _selecionar([l for l in linhas if not l['cancelado']], nivel, item)
    if origem:
        recorte = [l for l in recorte if l['origem'] == origem]
    por_dia = defaultdict(int)
    for l in recorte:
        por_dia[l['dia']] += l['qtd']
    cob = cobertura(carregar_coletas(de, ate), list(mlbs), de, ate)
    dias = [de + timedelta(days=i) for i in range((ate - de).days + 1)]
    return {'cadastro': cadastro, 'por_dia': dict(por_dia), 'estados': {d: _estado_do_dia(d, cob) for d in dias}, 'coletado_em': max(cob.values()) if cob else None}


# ==================================================== a página ====================================================

# Função Objetivo: Tudo da tela a partir da query string. SEM sku: a LISTA de vendas (lista_vendas_ml.montar_lista: gran, periodo, q, marca, sit, tend, ori, ord, dir, por,
# pag). COM sku: o histórico do produto (sku, periodo, nivel, item, visao; o antigo ?dias=7/30/90/180/365 ainda vale).
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
        # Campos escondidos do formulário de busca (para a busca não perder o período e, na lista, os filtros).
        'busca_ocultos': [{'nome': 'periodo', 'valor': periodo}] if periodo != PERIODO_PADRAO else [],
        'lista': None, 'produto': None,
    }
    if not sku:
        # * [EXPLICAÇÃO] → Sem SKU escolhido a tela mostra a LISTA (decisão do Matheus, 12/10/2026: ela SUBSTITUIU a busca simples e os "Mais vendidos"). Importado aqui
        #                  dentro porque lista_vendas_ml importa este arquivo (as regras de origem, Código ML, etc. moram aqui e a lista só as reaproveita).
        from gestao_vendas.funcoes_auxiliares.lista_vendas_ml import montar_lista

        lista = montar_lista(parametros, base_url, hoje)
        pagina.update(lista=lista, periodos=lista['periodos'], url_limpar=lista['url_limpar_busca'], busca_ocultos=lista['busca_ocultos'])
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


# Função Objetivo: O detalhe de CADA dia (o painel que abre ao clicar no dia do calendário) e a divisão Full / Fora do Full que aparece dentro da célula.
# Acrescenta em info[d] (as células das duas visões usam estes mesmos dicts): un_full, un_fora, un_sem, divisao (a célula mostra a divisão?) e div_txt.
# Devolve ({data ISO: detalhe com os textos já formatados}, a divisão vale neste nível?). Nos níveis "No Full" e "Fora do Full" a divisão não aparece:
# ela só repetiria o total. "Não-Full" na tela = "Fora do Full"; venda sem centro de estoque informado (node_id vazio) vira um terceiro item só quando existe.
#
# O PAINEL DO DIA (desenho combinado com o Matheus em 11/10/2026): cada bloco responde uma pergunta de quem clica num dia.
#   Cabeçalho (posso confiar nesse número?) · Resumo (o que aconteceu?) · Comparação (foi bom ou ruim, comparado a quê?) · Origem (de onde veio?) ·
#   Anúncios (quais?) · Hora a hora (quando?) · Preços do dia (a que preço, e por que foi diferente?) · Pedidos e cancelamentos (conferência; é buscado só quando a
#   pessoa abre o bloco: ver pedidos_do_dia, porque a lista de pedidos de um ano inteiro deixaria a página pesada).
#
# * [EXPLICAÇÃO] → A comparação é sempre com o MESMO DIA DA SEMANA: um sábado se compara com sábados, não com a média de todos os dias (que misturava
#                  sábado com terça). A referência são os mesmos-dias-da-semana COMPLETOS DO PERÍODO ESCOLHIDO na tela (a "média dos sábados do período", o melhor
#                  e o pior sábado do período): trocou o período, trocou a referência. O dia entra na própria média quando é completo (a média é a mesma em todos os
#                  sábados do período). Menos de MIN_DIAS_DE_REFERENCIA dias = não compara e diz por quê (numa semana cada dia da semana aparece só 1 ou 2 vezes;
#                  a partir de 1 mês aparece 4 ou 5).
# * [EXPLICAÇÃO] → Dia PARCIAL: o número vale só até a hora da COLETA (não até "agora"). A comparação então é "até as 14h, este dia vendeu X; as mesmas horas
#                  dos outros dias da semana venderam Y em média e o dia inteiro fechou com Z". Não há projeção de fechamento: com poucas vendas por dia
#                  ela seria chute. A hora da própria coleta fica fora dos dois lados (ela ainda estava incompleta), para a conta ser justa.
# * [EXPLICAÇÃO] → Só aparecem adjetivos ("dia forte", "dia fraco") quando a média de referência tem pelo menos MEDIA_MINIMA_PARA_JULGAR un; com menos que isso
#                  o texto traz só a diferença em %, porque 1 venda a mais já mudaria o adjetivo.
MIN_DIAS_DE_REFERENCIA = 3
MEDIA_MINIMA_PARA_JULGAR = 5
FAIXA_DO_NORMAL = 0.20
MIN_DIAS_PARA_POSICAO = 4
MAX_PRECOS_POR_ANUNCIO = 4
MAX_ANUNCIOS_COM_TROCA_DE_PRECO = 5
MAX_LINHAS_DE_PRECO = 8
LIMITE_PEDIDOS_DO_DIA = 1000
DIAS_NO_SINGULAR = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']
DIAS_NO_PLURAL = ['segundas', 'terças', 'quartas', 'quintas', 'sextas', 'sábados', 'domingos']
TIPOS_DE_ANUNCIO = {'gold_special': 'Clássico', 'gold_pro': 'Premium'}


def _pct_do_dia(parte, total):
    if not total or not parte:
        return '0%'
    p = parte / total * 100
    return '<1%' if p < 0.5 else f'{p:.0f}%'


def _genero(dsem):
    # segunda a sexta são femininas ("das quartas", "nas quartas", "uma quarta"); sábado e domingo, masculinos.
    return ('das', 'nas', 'uma') if dsem < 5 else ('dos', 'nos', 'um')


def _com_sinal(pct):
    return f'{pct:+.0f}%'.replace('-', '−')


def _texto_da_unidade(valor):
    return numero(valor) if isinstance(valor, int) else _decimal_br(valor)


# Função Objetivo: {dia: {'un': unidades, 'horas': [unidades de cada hora 0..23], 'fat': faturamento, 'un_preco': unidades que têm preço}} dos dias COMPLETOS
# recebidos (dia completo sem venda entra com zero: é zero de verdade). É a "base" das comparações: o período da tela mais o período anterior quando ele foi
# coletado. `fat` e `un_preco` existem para o preço médio dos mesmos dias da semana (faturamento ÷ unidades COM preço; item sem preço fica fora dos dois).
def _base_de_comparacao(dias_completos, linhas):
    base = {d: {'un': 0, 'horas': [0] * 24, 'fat': Decimal('0'), 'un_preco': 0} for d in dias_completos}
    for l in linhas:
        b = base.get(l['dia'])
        if b is None:
            continue
        b['un'] += l['qtd']
        if l['preco'] is not None:
            b['fat'] += l['preco'] * l['qtd']
            b['un_preco'] += l['qtd']
        if l['hora'] is not None and 0 <= l['hora'] <= 23:
            b['horas'][l['hora']] += l['qtd']
    return base


def _dias_por_dia_da_semana(base):
    por_dsem = defaultdict(list)
    for dia in sorted(base):
        por_dsem[dia.weekday()].append(dia)
    return por_dsem


# Função Objetivo: Os dias completos do MESMO dia da semana de `dia` DENTRO DO PERÍODO da tela (em ordem de data). `por_dsem` já vem só com os dias do período.
# O próprio dia está na lista quando é completo (dia parcial não está: ainda não fechou).
def _dias_de_referencia(dia, por_dsem):
    return list(por_dsem.get(dia.weekday(), []))


# Função Objetivo: Até que hora (exclusive) um dia PARCIAL tem dado: a hora da coleta, no horário de Brasília. 0 = coletado logo depois da meia-noite.
def _hora_do_corte(dia, coletado_em):
    quando = timezone.localtime(coletado_em, FUSO)
    if quando.date() < dia:
        return 0
    if quando.date() > dia:
        return 24
    return quando.hour


def _horas_do_dia(linhas):
    horas = [0] * 24
    for l in linhas:
        if l['hora'] is not None and 0 <= l['hora'] <= 23:
            horas[l['hora']] += l['qtd']
    return horas


# Função Objetivo: A frase do veredito: o valor do dia contra a média dos mesmos dias da semana. Devolve (tipo, texto): tipo = alto | normal | baixo | neutro.
# `corte` (hora) só vem em dia parcial: o texto passa a falar "até as 14h".
def _veredito(valor, media_ref, dsem, corte=None):
    de, em, um = _genero(dsem)
    plural, singular = DIAS_NO_PLURAL[dsem], DIAS_NO_SINGULAR[dsem]
    ate = f' até as {corte}h' if corte is not None else ''
    forte, fraco = ('Ritmo forte', 'Ritmo fraco') if corte is not None else ('Dia forte', 'Dia fraco')
    if media_ref <= 0:
        if valor > 0:
            return 'neutro', f'Vendeu {numero(valor)} un{ate}; {em} {plural} do período não houve nenhuma venda{" nesse horário" if corte is not None else ""}.'
        return 'normal', f'Sem vendas{ate}, como {em} {plural} do período.'
    dif = valor / media_ref - 1
    if media_ref < MEDIA_MINIMA_PARA_JULGAR:
        return 'neutro', f'{_com_sinal(dif * 100)} frente à média {de} {plural} do período{ate}. Poucas vendas por dia: o número varia muito.'
    if dif >= FAIXA_DO_NORMAL:
        return 'alto', f'{forte}: {dif * 100:.0f}% acima da média {de} {plural} do período{ate}.'
    if dif <= -FAIXA_DO_NORMAL:
        if valor == 0:
            return 'baixo', f'{fraco}: nenhuma venda{ate} (a média {de} {plural} do período é {_decimal_br(media_ref)} un).'
        return 'baixo', f'{fraco}: {-dif * 100:.0f}% abaixo da média {de} {plural} do período{ate}.'
    return 'normal', f'Dentro do normal para {um} {singular}{ate} ({_com_sinal(dif * 100)} frente à média do período).'


# Função Objetivo: Em que posição este dia ficou entre TODOS os mesmos dias da semana com dado completo (ex.: "2º melhor dia entre 26 quartas"). Vazio quando
# há poucos dias, quando o dia não vendeu, ou quando há empate nas pontas ("melhor" e "pior" só valem sem empate).
def _posicao(dia, un, base, por_dsem):
    outros = [base[x]['un'] for x in por_dsem.get(dia.weekday(), []) if x != dia]
    total = len(outros) + 1
    if total < MIN_DIAS_PARA_POSICAO or un <= 0:
        return ''
    acima = sum(1 for o in outros if o > un)
    abaixo = sum(1 for o in outros if o < un)
    plural = DIAS_NO_PLURAL[dia.weekday()]
    if acima == 0 and abaixo == len(outros):
        return f'Melhor dia entre {total} {plural} do período (com dado completo)'
    if abaixo == 0 and acima == len(outros):
        return f'Pior dia entre {total} {plural} do período (com dado completo)'
    return f'{acima + 1}º melhor dia entre {total} {plural} do período (com dado completo)'


# Função Objetivo: O melhor e o pior dia entre TODOS os dias completos do mesmo dia da semana de `dia` (é o mesmo grupo da frase "Nº melhor dia entre X quartas":
# o próprio dia entra, quando é completo). Com `corte` (dia parcial) cada dia vale só as horas ANTES da hora da coleta. Devolve (melhor, pior) ou (None, None) quando
# o grupo tem menos de MIN_DIAS_PARA_POSICAO dias. Cada um é {'valor', 'dia' (o mais recente entre os empatados), 'empates' (quantos outros dias deram o mesmo valor)}.
def _extremos_da_semana(dia, base, por_dsem, corte=None):
    valores = [(x, sum(base[x]['horas'][:corte]) if corte is not None else base[x]['un']) for x in por_dsem.get(dia.weekday(), [])]
    if len(valores) < MIN_DIAS_PARA_POSICAO:
        return None, None

    def _escolher(alvo):
        dias = sorted(d for d, v in valores if v == alvo)
        return {'valor': alvo, 'dia': dias[-1], 'empates': len(dias) - 1}

    return _escolher(max(v for _, v in valores)), _escolher(min(v for _, v in valores))


# Função Objetivo: O bloco "Comparação" de um dia: uma RÉGUA com os pontos de referência (este dia, a média dos mesmos dias da semana, o melhor e o pior dia deles),
# uma legenda com os valores, o dia anterior, o veredito e a posição. Devolve (bloco, veredito, média de referência).
# * [EXPLICAÇÃO] → A régua vai de 0 até o maior valor entre este dia, a média e o melhor dia; `pos` (0 a 100) é onde cada ponto cai nela. Só entram na régua os
#                  pontos da mesma escala (este dia, média, melhor, pior); "dia anterior" e "dia inteiro" ficam só na legenda. Em dia parcial tudo é "até a hora da
#                  coleta" (ver a explicação acima), inclusive o melhor e o pior dia.
def _bloco_comparacao(dia, un, linhas_do_dia, parcial, coletado_em, base, por_dsem):
    dsem = dia.weekday()
    plural = DIAS_NO_PLURAL[dsem]
    singular = DIAS_NO_SINGULAR[dsem]
    refs = _dias_de_referencia(dia, por_dsem)
    corte = _hora_do_corte(dia, coletado_em) if parcial else None
    # cada linha: (chave, rótulo, valor, entra na régua?, detalhe)
    linhas, veredito, posicao, sem_base, nota, media_ref = [], None, '', '', '', None
    if parcial:
        ate_agora = sum(l['qtd'] for l in linhas_do_dia if l['hora'] is not None and l['hora'] < corte)
        linhas.append(('este', f'Este dia (até as {corte}h)', ate_agora, True, ''))
        nota = 'A hora da coleta fica de fora da conta, porque ainda estava incompleta.'
    else:
        linhas.append(('este', 'Este dia', un, True, ''))
    if corte == 0:
        sem_base = 'Coletado logo depois da meia-noite: ainda não dá para comparar.'
    elif len(refs) < MIN_DIAS_DE_REFERENCIA:
        quantos = f'só há {len(refs)} {_s(len(refs), singular, plural)}' if refs else f'não há {_genero(dsem)[2].replace("um", "nenhum")} {singular}'
        sem_base = (f'Neste período {quantos} com dado completo; para comparar são necessários pelo menos {MIN_DIAS_DE_REFERENCIA}. '
                    f'Escolha um período de 1 mês ou mais, ou colete mais dias.')
    else:
        if parcial:
            media_ref = sum(sum(base[x]['horas'][:corte]) for x in refs) / len(refs)
            linhas.append(('media', f'Média {_genero(dsem)[0]} {len(refs)} {plural} do período', media_ref, True, ''))
            veredito = _veredito(ate_agora, media_ref, dsem, corte)
            # * [EXPLICAÇÃO] → O corte ("até as 15h") é dito UMA vez, na nota, em vez de repetido em cada linha: as linhas ficam curtas e cabem em uma linha só.
            nota = (f'Média, melhor e pior contam só até as {corte}h, como este dia. A hora da coleta ({corte}h) fica de fora de tudo, '
                    f'porque ainda estava incompleta.')
        else:
            media_ref = sum(base[x]['un'] for x in refs) / len(refs)
            linhas.append(('media', f'Média {_genero(dsem)[0]} {len(refs)} {plural} do período', media_ref, True, ''))
            veredito = _veredito(un, media_ref, dsem)
            posicao = _posicao(dia, un, base, por_dsem)
        melhor, pior = _extremos_da_semana(dia, base, por_dsem, corte)
        for chave, rotulo, ponto in (('melhor', 'Melhor', melhor), ('pior', 'Pior', pior)):
            if ponto is None:
                continue
            quando = f'{ponto["dia"]:%d/%m/%y}' if ponto['dia'].year != dia.year else data_curta(ponto['dia'])
            if ponto['empates']:
                quando += f' e mais {ponto["empates"]} {_s(ponto["empates"], "dia", "dias")}'
            linhas.append((chave, f'{rotulo} {singular} do período', ponto['valor'], True, quando))
        if parcial:
            linhas.append(('inteiro', 'Média do dia inteiro', sum(base[x]['un'] for x in refs) / len(refs), False, f'{len(refs)} {plural}'))
    if not parcial:
        anterior = base.get(dia - timedelta(days=1))
        if anterior is not None:
            linhas.append(('anterior', f'Dia anterior ({DIAS_DA_SEMANA[(dsem - 1) % 7]})', anterior['un'], False, ''))
    # * [EXPLICAÇÃO] → Sem referência (período curto demais) não há régua: uma barra cheia sozinha pareceria "100%" de alguma coisa. Fica só o número na legenda.
    if sem_base:
        linhas = [(chave, rotulo, valor, False, detalhe) for chave, rotulo, valor, _, detalhe in linhas]
    maximo = max((valor for _, _, valor, na_regua, _ in linhas if na_regua), default=0) or 1
    saida = []
    for chave, rotulo, valor, na_regua, detalhe in linhas:
        # * [EXPLICAÇÃO] → O valor sai sempre com "un" (unidades vendidas), para ninguém ler a média como "dias" ou "pedidos".
        item = {'chave': chave, 'rotulo': rotulo, 'texto': f'{_texto_da_unidade(valor)} un'}
        if chave == 'media':
            item['dica'] = (f'Média de unidades vendidas {_genero(dsem)[1]} {len(refs)} {plural} com dado completo do período escolhido na tela'
                            + (f', contando só até as {corte}h' if parcial else ''))
        if na_regua:
            item['pos'] = round(valor / maximo * 100, 1)
        if detalhe:
            item['detalhe'] = detalhe
        saida.append(item)
    bloco = {'linhas': saida, 'posicao': posicao, 'sem_base': sem_base, 'nota': nota, 'n_ref': len(refs)}
    return bloco, ({'tipo': veredito[0], 'texto': veredito[1]} if veredito else None), media_ref


# Função Objetivo: O bloco "Anúncios" de um dia: TODOS os anúncios (MLB) que venderam, do que mais vendeu para o que menos vendeu, com unidades, faturamento,
# preço, tipo do anúncio e a divisão Full / Fora do Full de cada um. No nível "Por MLB" a lista seria 1 linha só; aí ela vira "Códigos ML" (uma linha por
# Código ML do anúncio) e some quando há só um Código. Os títulos não vão aqui (repetiriam em todos os dias): vão uma vez só, em "anuncios_json".
def _bloco_anuncios(linhas, nivel, com_divisao, un_total):
    por_codigo = nivel == 'mlb'
    grupos = _agrupar(linhas, (lambda l: l['codigo'] or '') if por_codigo else (lambda l: l['mlb']))
    saida = []
    for chave, ls in grupos.items():
        soma = _somar(ls)
        precos = [l['preco'] for l in ls if l['preco'] is not None]
        linha = {'chave': chave, 'un': numero(soma['un']), 'pct': _pct_do_dia(soma['un'], un_total), 'barra': round(soma['un'] / un_total * 100, 1),
                 'fat': dinheiro(soma['fat']) if precos else '', '_un': soma['un']}
        if precos:
            baixo, alto = min(precos), max(precos)
            linha['preco'] = dinheiro(baixo) if baixo == alto else f'{dinheiro(baixo)} a {dinheiro(alto)}'
            # * [EXPLICAÇÃO] → "mais de um preço" só vale se UMA MESMA variação vendeu por preços diferentes no dia (variações diferentes do mesmo MLB podem ter
            #                  preços diferentes sem que nada tenha mudado). Mesma regra do bloco "Preços do dia".
            por_variacao = defaultdict(set)
            for l in ls:
                if l['preco'] is not None:
                    por_variacao[l['variacao'] or ''].add(l['preco'])
            linha['mudou'] = any(len(v) > 1 for v in por_variacao.values())
        if not por_codigo:
            por_tipo = defaultdict(int)
            for l in ls:
                por_tipo[l['tipo']] += l['qtd']
            if por_tipo:
                tipo = max(por_tipo.items(), key=lambda kv: (kv[1], kv[0]))[0]
                linha['tipo'] = TIPOS_DE_ANUNCIO.get(tipo, tipo)
        if com_divisao:
            for rotulo, origem in (('full', 'full'), ('fora', 'fora'), ('sem', 'indefinido')):
                un_origem = sum(l['qtd'] for l in ls if l['origem'] == origem)
                if rotulo != 'sem' or un_origem:
                    linha[rotulo] = numero(un_origem)
                    linha['barra_' + rotulo] = round(un_origem / soma['un'] * 100, 1)
        saida.append(linha)
    saida.sort(key=lambda x: (-x['_un'], x['chave']))
    for linha in saida:
        del linha['_un']
    if por_codigo and len(saida) < 2:
        return None
    return {'tipo': 'codigo' if por_codigo else 'mlb', 'linhas': saida}


# Função Objetivo: O bloco "Hora a hora": unidades de cada hora (0 a 23), a hora de pico e, quando há dias de referência, a média de cada hora dos mesmos dias
# da semana (uma marca na curva). Em dia parcial `corte` diz até que hora há dado; as horas depois dele ficam "sem dado" (não são zero).
def _bloco_horas(linhas, parcial, corte, refs, base, dsem):
    horas = _horas_do_dia(linhas)
    # * [EXPLICAÇÃO] → Em dia parcial só valem as horas ANTES da hora da coleta (a própria hora da coleta ainda estava incompleta): o pico sai só delas, para o texto
    #                  não apontar uma hora que o gráfico mostra como "sem dado".
    validas = horas[:corte] if parcial and corte is not None else horas
    if not any(validas):
        return None
    pico = max(range(len(validas)), key=lambda h: (validas[h], -h))
    bloco = {'v': horas, 'pico': f'{pico:02d}h ({numero(horas[pico])} un)'}
    if parcial:
        bloco['corte'] = corte
    if len(refs) >= MIN_DIAS_DE_REFERENCIA:
        bloco['ref'] = [round(sum(base[x]['horas'][h] for x in refs) / len(refs), 1) for h in range(24)]
        bloco['nome'] = DIAS_NO_PLURAL[dsem]
        bloco['art'] = _genero(dsem)[0]
        bloco['n_ref'] = len(refs)
    return bloco


# Função Objetivo: O bloco "Preços do dia" (mais os sinais do pedido) de UM dia. Responde, em ordem: quais preços o produto vendeu naquele dia (do menor ao maior), quantas
# unidades vendeu em cada um, de que horas a que horas vendeu com aquele preço, qual foi o preço médio e como ele se compara com os mesmos dias da semana do período.
# Também aponta os anúncios cujo preço MUDOU durante o dia (e em que intervalo) e quantos pedidos vieram com desconto ou por catálogo (as duas marcas que o Mercado
# Livre põe no pedido: order_has_discount e catalog; a tela não adivinha o motivo do desconto).
# * [EXPLICAÇÃO] → O preço é o do item vendido (unit_price no instante da compra). A tela NÃO enxerga o momento em que o preço foi trocado no anúncio: só enxerga as vendas.
#                  Por isso "das 10:12 às 22:40" é a primeira e a última VENDA com aquele preço, não o tempo em que o preço ficou ativo. O tempo ativo de verdade
#                  precisaria do histórico de preços do próprio Mercado Livre (a tela avisa isso na nota do bloco).
# * [EXPLICAÇÃO] → Preços diferentes de anúncios DIFERENTES no mesmo dia são normais (Clássico x Premium, por exemplo); por isso as linhas da lista são por preço E por anúncio
#                  (MLB), e a troca de preço é conferida por anúncio e por variação (variações do mesmo MLB podem ter preços diferentes sem que nada tenha mudado).
# * [EXPLICAÇÃO] → "Troca de preço" = o mesmo anúncio/variação vendeu por 2 ou mais preços e cada preço só começou DEPOIS da última venda do anterior (ordenado pelo instante
#                  exato, com segundos). Se os períodos se cruzam (o preço voltou ao que era, ou dois preços valeram ao mesmo tempo) são "preços misturados": a tela
#                  não afirma que houve troca. Sem o instante exato (linha antiga sem criado_em_ml) a ordem só vale com 1 hora de diferença (hora cheia).

def _hhmm(segundos):
    return f'{segundos // 3600:02d}:{segundos % 3600 // 60:02d}'


# Função Objetivo: Quando um conjunto de vendas aconteceu: o primeiro e o último instante (em segundos desde 00:00). Com o instante exato vale o minuto ('preciso');
# sem ele vale a hora cheia (a venda das 10h entra como 10:00 a 10:59, e 'preciso' fica falso). `completo` = todas as linhas têm alguma hora. None = nenhuma tem.
def _quando_das_vendas(ls):
    inicios, fins, preciso, completo = [], [], True, True
    for l in ls:
        if l['seg'] is not None:
            inicios.append(l['seg'])
            fins.append(l['seg'])
        elif l['hora'] is not None and 0 <= l['hora'] <= 23:
            inicios.append(l['hora'] * 3600)
            fins.append(l['hora'] * 3600 + 3599)
            preciso = False
        else:
            completo = False
    if not inicios:
        return None
    return {'ini': min(inicios), 'fim': max(fins), 'preciso': preciso, 'completo': completo}


def _instante(segundos, preciso):
    return _hhmm(segundos) if preciso else f'{segundos // 3600:02d}h'


# Função Objetivo: "das 10:12 às 22:40" (ou "às 10:03" quando começou e terminou no mesmo minuto) de um conjunto de vendas; vazio quando nenhuma linha tem hora.
def _texto_da_janela(q):
    if q is None:
        return ''
    a, b = _instante(q['ini'], q['preciso']), _instante(q['fim'], q['preciso'])
    return f'às {a}' if a == b else f'das {a} às {b}'


# Função Objetivo: A lista de preços do dia: UMA LINHA por (preço, anúncio), do menor preço para o maior. Cada linha traz unidades, % do dia, faturamento, o anúncio (só se o dia
# teve mais de um) e de que horas a que horas houve venda com aquele preço. Só entra preço que existe (item sem preço no pedido fica fora, e é contado à parte).
# Com 2 ou mais preços diferentes no dia a linha pode ganhar as marcas MENOR, MAIOR e MAIS VENDIDO (esta só quando uma linha vendeu mais unidades que todas as outras).
# Passando de MAX_LINHAS_DE_PRECO linhas, ficam as do menor e do maior preço e as de mais unidades; o resto vira "+ N outros preços". Devolve (linhas, sobra).
def _linhas_de_preco(com_preco, un_total):
    mostrar_mlb = len({l['mlb'] for l in com_preco}) > 1
    variacoes_do_mlb = defaultdict(set)
    for l in com_preco:
        variacoes_do_mlb[l['mlb']].add(l['variacao'] or '')
    candidatas = []
    for (preco, mlb), ls in _agrupar(com_preco, lambda l: (l['preco'], l['mlb'])).items():
        candidatas.append({'preco': preco, 'mlb': mlb, 'ls': ls, 'un': sum(l['qtd'] for l in ls)})
    menor, maior = min(c['preco'] for c in candidatas), max(c['preco'] for c in candidatas)
    com_marcas = menor != maior
    campeao = None
    if com_marcas and len(candidatas) >= 2:
        por_unidades = sorted(candidatas, key=lambda c: -c['un'])
        if por_unidades[0]['un'] > por_unidades[1]['un']:
            campeao = por_unidades[0]
    escolhidas = sorted(candidatas, key=lambda c: (c['preco'] not in (menor, maior), -c['un'], c['preco'], c['mlb']))[:MAX_LINHAS_DE_PRECO]
    escolhidas.sort(key=lambda c: (c['preco'], -c['un'], c['mlb']))
    linhas = []
    for c in escolhidas:
        texto = _texto_da_janela(_quando_das_vendas(c['ls']))
        linha = {'preco': dinheiro(c['preco']), 'un': numero(c['un']), 'pct': _pct_do_dia(c['un'], un_total), 'barra': round(c['un'] / un_total * 100, 1),
                 'fat': dinheiro(c['preco'] * c['un'])}
        if mostrar_mlb:
            linha['mlb'] = c['mlb']
        # * [EXPLICAÇÃO] → A variação só aparece quando o anúncio vendeu variações diferentes no dia E a linha é de uma variação só: é o que explica dois preços do mesmo
        #                  anúncio sem que nada tenha mudado (uma variação pode custar mais que a outra).
        variacoes_da_linha = {l['variacao'] or '' for l in c['ls']}
        if len(variacoes_do_mlb[c['mlb']]) > 1 and len(variacoes_da_linha) == 1 and next(iter(variacoes_da_linha)):
            linha['var'] = next(iter(variacoes_da_linha))
        if texto:
            linha['quando'] = f'{"venda" if len(c["ls"]) == 1 else "vendas"} {texto}'
        marcas = []
        if com_marcas and c['preco'] == menor:
            marcas.append('menor')
        if com_marcas and c['preco'] == maior:
            marcas.append('maior')
        if campeao is c:
            marcas.append('top')
        if marcas:
            linha['marcas'] = marcas
        linhas.append(linha)
    mantidas = {id(c) for c in escolhidas}
    fora = [c for c in candidatas if id(c) not in mantidas]
    sobra = {'n': len(fora), 'un': numero(sum(c['un'] for c in fora))} if fora else None
    return linhas, sobra


# Função Objetivo: A RÉGUA de preços: do menor ao maior preço do dia, com uma bolinha em cada preço (maior = vendeu mais unidades) e uma marca no preço médio.
# `pos` e `media` vão de 0 a 100 (0 = menor preço, 100 = maior preço). Só existe com 2 ou mais preços diferentes.
def _regua_de_precos(com_preco, medio):
    menor, maior = min(l['preco'] for l in com_preco), max(l['preco'] for l in com_preco)
    if menor == maior:
        return None
    amplitude = maior - menor
    por_preco = defaultdict(int)
    for l in com_preco:
        por_preco[l['preco']] += l['qtd']
    mais = max(por_preco.values())
    pontos = [{'pos': round(float((p - menor) / amplitude * 100), 1), 'rel': round(un / mais, 2), 'dica': f'{dinheiro(p)} · {numero(un)} un'}
              for p, un in sorted(por_preco.items())]
    return {'min': dinheiro(menor), 'max': dinheiro(maior), 'media': round(float((medio - menor) / amplitude * 100), 1), 'pontos': pontos}


# Função Objetivo: O preço médio do dia contra o preço médio dos MESMOS DIAS DA SEMANA do período escolhido (só dias completos, com venda e com preço; o próprio dia conta,
# como na Comparação). É a mesma regra mínima da Comparação: MIN_DIAS_DE_REFERENCIA dias. Preço médio = faturamento ÷ unidades COM preço, somando todos os dias de referência
# (não é a média das médias: um dia que vendeu 50 un pesa mais que um que vendeu 2). Dia ainda incompleto não é comparado. Devolve {'sem': motivo} quando não dá.
def _preco_medio_dos_mesmos_dias(dia, medio, parcial, base, por_dsem):
    dsem = dia.weekday()
    plural, singular = DIAS_NO_PLURAL[dsem], DIAS_NO_SINGULAR[dsem]
    if parcial:
        return {'sem': f'Dia ainda incompleto: o preço médio só é comparado com {"as outras" if dsem < 5 else "os outros"} {plural} depois que o dia fecha.'}
    refs = [x for x in _dias_de_referencia(dia, por_dsem) if base[x]['un_preco'] > 0]
    if len(refs) < MIN_DIAS_DE_REFERENCIA:
        return {'sem': f'Sem comparação de preço: neste período só há {len(refs)} {_s(len(refs), singular, plural)} com venda e preço; '
                       f'são necessários pelo menos {MIN_DIAS_DE_REFERENCIA}.'}
    un = sum(base[x]['un_preco'] for x in refs)
    ref = sum(base[x]['fat'] for x in refs) / un
    dif = float(medio / ref - 1) * 100
    if abs(dif) < 0.5:
        tipo, texto = 'igual', 'Este dia: praticamente igual (menos de 0,5% de diferença)'
    elif dif > 0:
        tipo, texto = 'acima', f'Este dia ficou {_decimal_br(dif)}% acima'
    else:
        tipo, texto = 'abaixo', f'Este dia ficou {_decimal_br(-dif)}% abaixo'
    # * [EXPLICAÇÃO] → Só o essencial vai no JSON (ele é embutido na página para todos os dias do período): a explicação do cálculo é um texto fixo montado na tela,
    #                  que só precisa de `un` (as unidades da referência).
    return {'rotulo': f'Preço médio {_genero(dsem)[0]} {len(refs)} {plural} do período', 'valor': dinheiro(ref), 'texto': texto, 'tipo': tipo, 'un': numero(un)}


# Função Objetivo: Os anúncios (e variações) que venderam por MAIS DE UM preço no dia, cada um classificado: "em_ordem" = o preço mudou durante o dia (com o intervalo em que a
# troca aconteceu: da última venda com o preço antigo à primeira com o novo); senão = preços misturados (os períodos de cada preço se cruzam).
def _trocas_de_preco(com_preco):
    trocas = []
    for (mlb, variacao), ls in _agrupar(com_preco, lambda l: (l['mlb'], l['variacao'])).items():
        por_preco = _agrupar(ls, lambda l: l['preco'])
        if len(por_preco) < 2:
            continue
        passos = [{'preco': preco, 'un': sum(l['qtd'] for l in grupo), 'q': _quando_das_vendas(grupo), 'completo': all(l['seg'] is not None or l['hora'] is not None for l in grupo)}
                  for preco, grupo in por_preco.items()]
        passos.sort(key=lambda p: (p['q']['ini'] if p['q'] else 10 ** 6, p['preco']))
        em_ordem = all(p['q'] and p['completo'] for p in passos) and all(passos[i - 1]['q']['fim'] <= passos[i]['q']['ini'] for i in range(1, len(passos)))
        saida = []
        for i, p in enumerate(passos):
            q = p['q']
            item = {'preco': dinheiro(p['preco']), 'un': numero(p['un'])}
            if q:
                ini, fim = _instante(q['ini'], q['preciso']), _instante(q['fim'], q['preciso'])
                if em_ordem and i == 0:
                    item['quando'] = f'até {fim}'
                elif em_ordem and i == len(passos) - 1:
                    item['quando'] = f'a partir de {ini}'
                else:
                    item['quando'] = _texto_da_janela(q)
            if em_ordem and i > 0:
                anterior = passos[i - 1]['q']
                preciso = anterior['preciso'] and q['preciso']
                a, b = _instante(anterior['fim'], preciso), _instante(q['ini'], preciso)
                item['troca'] = f'por volta das {a}' if a == b else f'entre {a} e {b}'
            saida.append(item)
        trocas.append({'mlb': mlb, 'variacao': variacao, 'em_ordem': em_ordem, '_un': sum(p['un'] for p in passos),
                       'passos': saida[:MAX_PRECOS_POR_ANUNCIO], 'extra': max(0, len(saida) - MAX_PRECOS_POR_ANUNCIO)})
    trocas.sort(key=lambda t: (-t['_un'], t['mlb'], t['variacao'] or ''))
    for t in trocas:
        del t['_un']
    return trocas


# Função Objetivo: Junta as peças acima no bloco do dia: lista e régua de preços, preço médio, comparação com os mesmos dias da semana, trocas de preço e sinais do pedido.
def _bloco_precos(dia, linhas, parcial, base, por_dsem):
    saida = {}
    com_preco = [l for l in linhas if l['preco'] is not None]
    sem_preco = sum(l['qtd'] for l in linhas if l['preco'] is None)
    if com_preco:
        un = sum(l['qtd'] for l in com_preco)
        faturamento = sum(l['preco'] * l['qtd'] for l in com_preco)
        medio = faturamento / un
        menor, maior = min(l['preco'] for l in com_preco), max(l['preco'] for l in com_preco)
        saida['n_precos'] = len({l['preco'] for l in com_preco})
        saida['linhas'], sobra = _linhas_de_preco(com_preco, un)
        if sobra:
            saida['sobra'] = sobra
        regua = _regua_de_precos(com_preco, medio)
        if regua:
            saida['regua'] = regua
        saida['medio'] = dinheiro(medio)
        saida['conta'] = f'faturamento {dinheiro(faturamento)} ÷ {numero(un)} un'
        if menor > 0 and maior != menor:
            saida['amplitude'] = f'+{_decimal_br((maior / menor - 1) * 100)}%'
        saida['ref'] = _preco_medio_dos_mesmos_dias(dia, medio, parcial, base, por_dsem)
        trocas = _trocas_de_preco(com_preco)
        saida['trocas'] = trocas[:MAX_ANUNCIOS_COM_TROCA_DE_PRECO]
        saida['trocas_extra'] = max(0, len(trocas) - MAX_ANUNCIOS_COM_TROCA_DE_PRECO)
    if sem_preco:
        saida['sem_preco'] = f'{numero(sem_preco)} un sem preço no pedido (fora destas contas)'
    pedidos = {l['pedido'] for l in linhas}
    if pedidos:
        saida['n_pedidos'] = len(pedidos)
        saida['desconto'] = len({l['pedido'] for l in linhas if l['desconto']})
        saida['catalogo'] = len({l['pedido'] for l in linhas if l['catalogo']})
    return saida


def _detalhe_dos_dias(info, recorte, canceladas, mlbs, nivel, media, cob, base):
    com_divisao = nivel in ('produto', 'mlb', 'codigo')
    linhas_do_dia = _agrupar(recorte, lambda l: l['dia'])
    canceladas_do_dia = _agrupar(canceladas, lambda l: l['dia'])
    # * [EXPLICAÇÃO] → A referência de cada dia é o PERÍODO ESCOLHIDO na tela: só entram os dias completos do período (as chaves de `info`). O período anterior
    #                  não entra na média, no melhor nem no pior dia; ele só serve para achar o "dia anterior" do primeiro dia do período.
    por_dsem = _dias_por_dia_da_semana({d: base[d] for d in info if d in base})
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
        parcial = v['estado'] == 'parcial'
        un_com_preco = sum(l['qtd'] for l in linhas if l['preco'] is not None)
        detalhe.update({
            'estado_txt': 'Dia completo' if v['estado'] == 'ok' else 'Dia ainda incompleto',
            'coletado': f'coletado em {data_hora(cob[d])}',
            'zero': v['zero'], 'un': numero(v['un']),
            'pedidos': f'{numero(v["pedidos"])} {_s(v["pedidos"], "pedido", "pedidos")}',
            'fat': dinheiro(v['fat']),
            'preco_medio': f'{dinheiro(v["fat"] / un_com_preco)}/un' if un_com_preco else '',
        })
        # ---- bloco Comparação (e o veredito, que o painel mostra junto do resumo) ----
        comparacao, veredito, media_ref = _bloco_comparacao(d, v['un'], linhas, parcial, cob[d], base, por_dsem)
        detalhe['comparacao'] = comparacao
        if veredito:
            detalhe['veredito'] = veredito
        if v['un'] > 0:
            # ---- bloco Origem (Full x Fora do Full) ----
            if com_divisao:
                linhas_origem = [('full', 'Full'), ('fora', 'Fora do Full')] + ([('indefinido', 'Sem origem informada')] if un_sem else [])
                detalhe['origens'] = [{'chave': chave, 'rotulo': rotulo, 'un': numero(somas[chave]['un']), 'pct': _pct_do_dia(somas[chave]['un'], v['un']),
                                       'barra': round(somas[chave]['un'] / v['un'] * 100, 1), 'pedidos': numero(somas[chave]['pedidos']),
                                       'fat': dinheiro(somas[chave]['fat'])} for chave, rotulo in linhas_origem]
            # ---- bloco Anúncios (ou Códigos ML, no nível Por MLB) ----
            anuncios = _bloco_anuncios(linhas, nivel, com_divisao, v['un'])
            if anuncios:
                detalhe['anuncios'] = anuncios
            # ---- bloco Hora a hora ----
            horas = _bloco_horas(linhas, parcial, _hora_do_corte(d, cob[d]) if parcial else None, _dias_de_referencia(d, por_dsem), base, v['dsem'])
            if horas:
                detalhe['horas'] = horas
            # ---- bloco Preços do dia (e sinais do pedido) ----
            detalhe['precos'] = _bloco_precos(d, linhas, parcial, base, por_dsem)
        # ---- cancelados do dia (ficam fora de todas as contas; a lista deles vem junto dos pedidos) ----
        canc = canceladas_do_dia.get(d, [])
        if canc:
            s = _somar(canc)
            detalhe['cancelados'] = {'un': f'{numero(s["un"])} un', 'pedidos': numero(s['pedidos']), 'fat': dinheiro(s['fat']) if s['fat'] else ''}
        detalhe['tem_pedidos'] = bool(linhas or canc)
        # ---- avisos: muito fora do normal (comparando com o mesmo dia da semana quando dá; senão com a média geral) ou dia parcial ----
        referencia = media_ref if (media_ref is not None and not parcial) else media
        if v['estado'] == 'ok' and referencia:
            if referencia >= 8 and v['un'] < 0.25 * referencia:
                detalhe['aviso'] = {'tipo': 'baixo', 'texto': 'Muito abaixo do normal: vale conferir se este dia foi coletado por inteiro (botão "Atualizar este dia").'}
            elif referencia >= 8 and v['un'] > 2.5 * referencia:
                detalhe['aviso'] = {'tipo': 'alto', 'texto': 'Muito acima do normal: confira se houve promoção ou campanha neste dia.'}
        elif parcial:
            detalhe['aviso'] = {'tipo': 'parcial', 'texto': 'Coletado antes do fim do dia: o número ainda pode mudar. Use "Atualizar este dia" depois que ele acabar.'}
        detalhes[v['iso']] = detalhe
    return detalhes, com_divisao


# Função Objetivo: Os pedidos de UM dia, para o bloco "Pedidos e cancelamentos" do painel. É buscado só quando a pessoa abre o bloco (não vai no JSON da página:
# um ano de pedidos de um produto que vende bem deixaria a página pesada). Usa os MESMOS filtros e o mesmo recorte da tela (SKU, nível e item), então a lista bate
# com os números do painel. Cancelados vêm separados (não entram nas contas). Lê só o banco, nunca o Mercado Livre.
def pedidos_do_dia(sku, nivel, item, dia):
    cadastro = carregar_produto(sku)
    mlbs = cadastro['mlbs'] if cadastro else {}
    linhas = _anotar(_carregar_linhas(sku, mlbs, dia, dia, extras=('criado_em_ml',)), mlbs)
    nivel = nivel if nivel in NOMES_DOS_NIVEIS else 'produto'
    item = str(item or '').strip()
    if nivel in ('mlb', 'codigo') and not item:
        nivel = 'produto'
    selecionadas = _selecionar(linhas, nivel, item)
    selecionadas.sort(key=lambda l: (l['quando'] is None, l['quando'], l['pedido']))

    def _linha(l):
        hora = timezone.localtime(l['quando'], FUSO).strftime('%H:%M') if l['quando'] else (f'{l["hora"]:02d}h' if l['hora'] is not None else '')
        return {'hora': hora, 'pedido': str(l['pedido']), 'mlb': l['mlb'], 'un': l['qtd'], 'preco': dinheiro(l['preco']) if l['preco'] is not None else '',
                'origem': l['origem']}

    linhas_validas = [l for l in selecionadas if not l['cancelado']]
    linhas_canceladas = [l for l in selecionadas if l['cancelado']]
    validas = [_linha(l) for l in linhas_validas]
    canceladas = [_linha(l) for l in linhas_canceladas]
    # * [EXPLICAÇÃO] → A lista tem UMA LINHA POR ITEM VENDIDO (um pedido com 2 anúncios aparece 2 vezes). `n_pedidos` conta os pedidos de verdade (o mesmo número do
    #                  resumo do dia) e `n_itens` conta as linhas; o limite de 1000 vale para as linhas.
    return {'dia': f'{dia:%Y-%m-%d}', 'pedidos': validas[:LIMITE_PEDIDOS_DO_DIA], 'n_pedidos': len({l['pedido'] for l in linhas_validas}), 'n_itens': len(validas),
            'truncado': len(validas) > LIMITE_PEDIDOS_DO_DIA,
            'cancelados': canceladas[:LIMITE_PEDIDOS_DO_DIA], 'n_cancelados': len({l['pedido'] for l in linhas_canceladas}), 'n_itens_cancelados': len(canceladas)}


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

    todas = _anotar(_carregar_linhas(sku, mlbs, inicio_da_carga, hoje, extras=('criado_em_ml',)), mlbs)
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
    # * [EXPLICAÇÃO] → A "base" das comparações do painel do dia: os dias COMPLETOS do período da tela + os do período anterior que foram coletados por inteiro
    #                  (dia a dia: o anterior não precisa estar todo coletado, ao contrário da comparação dos cartões). Mais dias = comparação mais firme em períodos curtos.
    dias_ant_completos = [d for d in dias_ant if d in cob_ant and dia_completo(d, cob_ant[d])]
    base_de_comparacao = _base_de_comparacao(completos + dias_ant_completos, recorte + recorte_ant)
    dias_json, divisao_dias = _detalhe_dos_dias(dados_dos_dias, recorte, recorte_canc, mlbs, nivel, media, cob, base_de_comparacao)
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
        # Título, foto, link e selos de cada MLB, uma vez só (o painel do dia consulta aqui em vez de repetir isso em cada um dos 365 dias).
        'anuncios_json': _anuncios_para_o_painel(mlbs, un_mlb),
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
