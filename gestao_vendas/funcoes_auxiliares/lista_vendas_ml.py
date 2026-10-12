# gestao_vendas/funcoes_auxiliares/lista_vendas_ml.py
#
# Função Objetivo: A LISTA da tela "Vendas — Histórico de vendas": o que aparece quando NENHUM produto (SKU) está aberto (ela substituiu a antiga busca
# + "Mais vendidos"). Mostra as vendas da conta toda no período, uma linha por Produto (SKU), por Anúncio (MLB) ou por Código ML, com Full × Fora do Full,
# "vs. anterior" e a ligação de cada linha para o calendário de vendas (a tela do produto, em vendas_ml.py). LÊ SÓ DO BANCO: nada aqui chama a API do
# Mercado Livre (a única coisa que chama o ML nesta tela continua sendo o clique em "Coletar período da conta" e nos botões "Atualizar" do produto).
#
# REGRAS DO MATHEUS que moram aqui (são as MESMAS da tela do produto; nada foi reinventado, tudo é reaproveitado de vendas_ml.py):
#   - Venda CANCELADA não conta.
#   - Full × Fora do Full é decidido por UMA função só: classificar_origem (regras 1 a 4, com _mlbs_fora_pela_logistica para a regra 4).
#   - O Código ML de uma venda é o de codigo_do_item (variação do pedido; senão o único Código do MLB), olhando só as variações do SKU da venda.
#   - Períodos por CALENDÁRIO (Última semana, Último mês, Últimos 3 meses, Últimos 6 meses, Último ano), o mesmo da tela do produto e do coletor.
#   - Ausente não é zero: dia que a conta toda ainda não coletou NÃO entra na média por dia nem no "vs. anterior" (só entra nas unidades somadas).
#
# * [EXPLICAÇÃO] → POR QUE A COBERTURA AQUI É "DA CONTA TODA": a tela do produto olha a cobertura daquele produto (a conta toda OU todos os MLBs dele
#                  coletados um a um). Na lista seriam ~1000 coberturas diferentes, então a lista usa só a coleta da CONTA TODA (dia e período). Efeito: se
#                  você atualizou um produto sozinho ("Atualizar produto") para além do que a conta toda coletou, as unidades dele entram na lista, mas a
#                  média por dia e o "vs. anterior" só consideram os dias que a conta toda coletou. A faixa no topo da lista mostra essa cobertura.
# * [EXPLICAÇÃO] → "vs. anterior" compara a MÉDIA POR DIA (só dias completos) com a média por dia do período imediatamente anterior, do mesmo tamanho,
#                  e só existe quando o período anterior inteiro foi coletado por completo (a mesma regra dos cartões da tela do produto). Subindo ou
#                  caindo = mudança de 10% ou mais (LIMITE_DA_TENDENCIA_PCT).
# * [EXPLICAÇÃO] → COMO A LISTA É CALCULADA SEM FICAR LENTA (~1000 SKUs): 1 consulta das variações de anúncio (cadastro), 1 consulta dos produtos, 1 consulta
#                  das linhas de venda do período (só as colunas necessárias) e 1 consulta já SOMADA do período anterior. Tudo o mais é conta em memória.
#                  Nenhuma consulta por SKU ou por MLB.
# * [EXPLICAÇÃO] → A QUE SKU UMA VENDA PERTENCE: ao seller_sku do pedido (160 de 160 itens medidos trazem). Pedido sem seller_sku só vai para um SKU
#                  quando o MLB (e a variação, se o pedido trouxe) aponta para UM único SKU no cadastro de anúncios; senão cai em "Sem cadastro".

import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from gestao_vendas.funcoes_auxiliares.vendas_ml import (
    FUSO, STATUS_CANCELADO, TIPOS_DE_ANUNCIO, _dados_do_anuncio, _decimal_br, _inteiro, _mlbs_fora_pela_logistica, _s, _selos_do_anuncio, _url_segura, classificar_origem,
    codigo_do_item, data_hora, dinheiro, numero, prefixo_do_no_proprio, url_da_tela)
from integracao_mercado_livre.servicos.cobertura_vendas_ml import (
    PERIODO_PADRAO, carregar_coletas, cobertura, dia_completo, frase_frente_ao_anterior, frase_no_anterior, inicio_do_periodo, normalizar_periodo,
    periodo_anterior, periodos_de_hoje, primeiro_dia_do_ml)
from mercado_livre.models import VariacaoAnuncioMercadoLivre, VendaItemMercadoLivre
from produtos.models import Produto

# (chave na URL, rótulo do botão, ajuda sob os botões, rótulo do "Sem cadastro" do filtro de situação, nome da coluna, o que a linha é no plural/singular)
GRANULARIDADES = [
    ('sku', 'Produto (SKU)', 'Cada linha é um produto (SKU). Abra a linha para ver os anúncios (MLB) e o Código ML de cada um.', 'Sem cadastro', 'produtos', 'produto'),
    ('mlb', 'Anúncio (MLB)', 'Cada linha é um anúncio (MLB), com o SKU e o Código ML dele ao lado.', 'Sem cadastro', 'anúncios', 'anúncio'),
    ('codigo', 'Código ML', 'Cada linha é um Código ML (o estoque no Full). Abra para ver os anúncios que vendem usando esse código.', 'Sem Código ML', 'Códigos ML', 'Código ML'),
]
GRANULARIDADE_PADRAO = 'sku'
SITUACOES = ('todos', 'com', 'sem', 'alerta')
TENDENCIAS = ('todas', 'up', 'flat', 'down', 'sem')
ORIGENS = ('todas', 'full', 'fora', 'ambos')
COLUNAS = ('nome', 'un', 'ped', 'fat', 'fu', 'fo', 'media', 'delta', 'ult')
COLUNAS_DE_ORDEM_CRESCENTE = ('nome', 'ult')   # estas abrem em A→Z / mais recente primeiro; as outras abrem do maior para o menor
ORDENS_PRONTAS = [
    ('un', 'desc', 'Mais vendidos (unidades)'),
    ('fat', 'desc', 'Maior faturamento'),
    ('delta', 'desc', 'Maior alta no período'),
    ('delta', 'asc', 'Maior queda no período'),
    ('ult', 'asc', 'Venda mais recente'),
    ('nome', 'asc', 'Nome (A–Z)'),
]
POR_PAGINA_OPCOES = (10, 25, 50, 100)
POR_PAGINA_PADRAO = 25
LIMITE_DA_TENDENCIA_PCT = 10
MAX_FILHOS_SEM_CODIGO = 60
SEM_CADASTRO = 'sem-cadastro'   # chave da linha que junta as vendas que não dá para ligar a nenhum SKU
SEM_CODIGO = 'sem-codigo'       # chave da linha que junta as vendas de anúncio sem Código ML


# ==================================================== pequenas ajudas ====================================================

def _sem_acento(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto or '')) if unicodedata.category(c) != 'Mn').lower()


def _reais(valor):
    return 'R$ ' + f'{valor:,.0f}'.replace(',', '.')


def _reais_com_centavos(valor):
    return dinheiro(valor)


def _pct(parte, total):
    return round(parte / total * 100) if total else 0


def _com_sinal(pct):
    r = round(pct)
    return ('+' if r > 0 else ('−' if r < 0 else '')) + f'{abs(r)}%'


def _dominante(contador, ignorar=('',)):
    """A chave que mais apareceu (empate: a de menor ordem alfabética, para a tela não mudar de uma abertura para outra)."""
    for chave, _ in sorted(contador.items(), key=lambda par: (-par[1], par[0])):
        if chave not in ignorar:
            return chave
    return ''


def _texto_ultima_venda(quando, hoje):
    if quando is None:
        return '—'
    t = timezone.localtime(quando, FUSO)
    dia = t.date()
    prefixo = 'Hoje' if dia == hoje else ('Ontem' if dia == hoje - timedelta(days=1) else f'{dia:%d/%m}')
    return f'{prefixo} {t:%H:%M}'


def _rotulo_do_tipo(tipo):
    if not tipo:
        return ''
    return TIPOS_DE_ANUNCIO.get(tipo.get('tipo_anuncio'), tipo.get('tipo_anuncio') or '')


# ==================================================== a "conta" (a soma de um grupo de linhas de venda) ====================================================

class _Conta:
    """Soma de um grupo de linhas de venda (um SKU, um MLB, um Código ML, ou um MLB dentro de um SKU...)."""
    __slots__ = ('un', 'un_preco', 'fat', 'pedidos', 'full', 'fora', 'indef', 'un_comp', 'ult', 'ant', 'skus', 'mlbs')

    def __init__(self):
        self.un = 0
        self.un_preco = 0          # unidades que têm preço (base do preço médio)
        self.fat = Decimal('0')
        self.pedidos = set()       # pedidos distintos (um pedido com 2 itens do mesmo grupo conta 1 vez)
        self.full = 0
        self.fora = 0
        self.indef = 0             # "Sem origem informada": não entra em Full nem em Fora do Full
        self.un_comp = 0           # unidades só dos dias COMPLETOS (base da média por dia)
        self.ult = None            # instante da última venda
        self.ant = 0               # unidades do período anterior
        self.skus = Counter()
        self.mlbs = Counter()

    def somar(self, qtd, preco, pedido, origem, completo, quando):
        self.un += qtd
        if preco is not None:
            self.fat += preco * qtd
            self.un_preco += qtd
        self.pedidos.add(pedido)
        if origem == 'full':
            self.full += qtd
        elif origem == 'fora':
            self.fora += qtd
        else:
            self.indef += qtd
        if completo:
            self.un_comp += qtd
        if self.ult is None or quando > self.ult:
            self.ult = quando


# ==================================================== cadastro: SKUs, anúncios e Códigos ML (em lote) ====================================================

# Função Objetivo: O cadastro de TODOS os anúncios numa consulta só (a tela do produto, carregar_produto, faz isso para 1 SKU; aqui é para todos de uma vez).
# Devolve: por_sku {sku: {'mlbs': {mlb: {'titulo', 'tipo', 'variacoes': [(variacao_id, Código ML)]}}}} (o MESMO formato de carregar_produto, para o
# codigo_do_item dar o mesmo resultado), candidatos {mlb: {sku: {variacao_id}}} (para o pedido sem seller_sku), anuncios {mlb: {'titulo', 'tipo',
# 'variacoes', 'imagem', 'link', 'selos'}} (todas as variações do MLB, de qualquer SKU; foto, link e selos para o cartão do anúncio) e codigos {Código ML: {'mlbs', 'skus'}}.
def _carregar_cadastro():
    por_sku, anuncios = {}, {}
    candidatos = defaultdict(dict)
    codigos = defaultdict(lambda: {'mlbs': set(), 'skus': set()})
    variacoes = VariacaoAnuncioMercadoLivre.objects.select_related('anuncio', 'anuncio__tipo_de_anuncio').exclude(anuncio__mlb='')
    for v in variacoes:
        mlb = v.anuncio.mlb
        if not mlb:
            continue
        item = anuncios.get(mlb)
        if item is None:
            dados = _dados_do_anuncio(v.anuncio)
            item = anuncios[mlb] = {'titulo': dados['titulo'], 'tipo': dados['tipo'], 'variacoes': [], 'imagem': '', 'link': dados['link'],
                                    'selos': _selos_do_anuncio(dados['tipo'])}
        # * [EXPLICAÇÃO] → A foto é do anúncio: vale a da primeira variação que tiver (imagem principal; sem ela, a miniatura), como no Hub e no painel do dia.
        if not item['imagem']:
            item['imagem'] = _url_segura(v.imagem_principal_url) or _url_segura(v.thumbnail_url)
        variacao_id = str(v.variacao_id or '')
        codigo = (v.inventory_id or '').strip().upper()
        item['variacoes'].append((variacao_id, codigo))
        if codigo:
            codigos[codigo]['mlbs'].add(mlb)
        sku = v.produto_id   # a ligação com Produto é pelo campo sku (to_field), então produto_id já é o SKU
        if sku:
            if codigo:
                codigos[codigo]['skus'].add(sku)
            do_sku = por_sku.setdefault(sku, {'mlbs': {}})['mlbs']
            do_sku.setdefault(mlb, {'titulo': item['titulo'], 'tipo': item['tipo'], 'variacoes': []})['variacoes'].append((variacao_id, codigo))
            candidatos[mlb].setdefault(sku, set()).add(variacao_id)
    return {'por_sku': por_sku, 'candidatos': candidatos, 'anuncios': anuncios, 'codigos': codigos}


# Função Objetivo: O "cartão" de um anúncio (MLB) no jeito do Hub de Anúncios: foto, selos (status, tipo, logística, Flex e papel no catálogo), título e o MLB com o SKU
# e o Código ML. Os selos são os mesmos do Hub e do painel do dia (registro único em mercado_livre/funcoes_auxiliares/badges.py, via _selos_do_anuncio).
# * [EXPLICAÇÃO] → Foto, título e selos já vêm do cadastro carregado UMA vez (_carregar_cadastro): nenhuma consulta nova por anúncio. Sem foto do anúncio usa a do
#                  produto (como o Hub). Anúncio fora da tabela de Anúncios não tem título, foto nem selos: só aparece o aviso ("Sem cadastro") e o que a venda sabe (SKU).
def _cartao_do_anuncio(mlb, anuncio, produto, sku, codigos, aviso='', aviso_classe=''):
    if codigos:
        codigo = f'Código ML {codigos[0]}' if len(codigos) == 1 else f'{len(codigos)} Códigos ML'
    else:
        codigo = 'sem Código ML' if anuncio else ''
    return {'mlb': mlb, 'titulo': (anuncio or {}).get('titulo') or '', 'imagem': ((anuncio or {}).get('imagem') or (produto or {}).get('imagem') or '') if anuncio else '',
            'selos': (anuncio or {}).get('selos') or [], 'link': (anuncio or {}).get('link') or '', 'sku': sku, 'codigo': codigo, 'aviso': aviso, 'aviso_classe': aviso_classe}


# Função Objetivo: A URL da foto do produto COMO ESTÁ NO CADASTRO (a mesma que as outras telas usam), só aceitando http:// ou https:// (nunca "javascript:" ou outro tipo de endereço).
# * [EXPLICAÇÃO] → NÃO troca http:// por https://: a foto do cadastro vem do ERP e pode estar num servidor que só responde em http; trocar o endereço quebra a imagem.
def _url_da_foto(url):
    url = url.strip() if isinstance(url, str) else ''
    return url if url.lower().startswith(('http://', 'https://')) else ''


# Função Objetivo: Os dados dos produtos (título, marca, EAN, foto) dos SKUs pedidos, em poucas consultas.
def _carregar_produtos(skus):
    skus = sorted(s for s in skus if s)
    saida = {}
    for i in range(0, len(skus), 800):
        for p in Produto.objects.filter(sku__in=skus[i:i + 800]).values('sku', 'titulo', 'marca', 'ean', 'imagem_url'):
            saida[p['sku']] = {'titulo': p['titulo'] or '', 'marca': p['marca'] or '', 'ean': p['ean'] or '', 'imagem': _url_da_foto(p['imagem_url'])}
    return saida


# Função Objetivo: Liga uma linha de venda ao seu SKU e ao seu Código ML. Devolve (sku, codigo): '' = sem SKU / sem Código ML (as linhas "Sem cadastro" e
# "Sem Código ML"). A regra é a mesma de _anotar (tela do produto), em versão para todos os SKUs.
def _atribuir(cad, seller_sku, mlb, variation_id):
    if seller_sku:
        do_sku = cad['por_sku'].get(seller_sku, {}).get('mlbs', {})
        return seller_sku, codigo_do_item(do_sku, mlb, variation_id) or ''
    # Pedido sem seller_sku: vale o SKU cujo cadastro tem este MLB (e esta variação, se o pedido trouxe), desde que seja UM só.
    candidatos = [sku for sku, ids in cad['candidatos'].get(mlb, {}).items() if not variation_id or variation_id in ids]
    if len(candidatos) == 1:
        return candidatos[0], codigo_do_item(cad['por_sku'][candidatos[0]]['mlbs'], mlb, variation_id) or ''
    anuncio = cad['anuncios'].get(mlb)
    return '', (codigo_do_item({mlb: anuncio}, mlb, variation_id) or '') if anuncio else ''


# ==================================================== o cálculo (período atual e anterior) ====================================================

# Função Objetivo: Lê o banco UMA vez e soma tudo do período: por SKU, por MLB e por Código ML (e guarda as linhas por SKU e por Código para abrir as linhas
# de dentro sem reler o banco). Devolve também o contexto de datas e cobertura que as contas de "média por dia" e "vs. anterior" precisam.
def _calcular(periodo, hoje):
    de, recortado = inicio_do_periodo(periodo, hoje)
    de_ant, ate_ant = periodo_anterior(periodo, hoje)
    tem_anterior = de_ant >= primeiro_dia_do_ml(hoje)
    dias_do_periodo = [de + timedelta(days=i) for i in range((hoje - de).days + 1)]
    dias_ant = [de_ant + timedelta(days=i) for i in range((ate_ant - de_ant).days + 1)] if tem_anterior else []

    # ---- cobertura da CONTA TODA (coleta de dia e de período) e o que é "completo" ----
    coletas = carregar_coletas(de_ant if tem_anterior else de, hoje)
    cob = cobertura(coletas, [], de, hoje)
    cob_ant = cobertura(coletas, [], de_ant, ate_ant) if tem_anterior else {}
    completos = {d for d in dias_do_periodo if d in cob and dia_completo(d, cob[d])}
    anterior_completo = tem_anterior and all(d in cob_ant and dia_completo(d, cob_ant[d]) for d in dias_ant)

    # ---- cadastro e origem ----
    cad = _carregar_cadastro()
    no_proprio = prefixo_do_no_proprio()
    fora_pela_logistica = _mlbs_fora_pela_logistica({mlb: {'tipo': a['tipo']} for mlb, a in cad['anuncios'].items()}, no_proprio)

    contas_sku, contas_mlb, contas_cod = defaultdict(_Conta), defaultdict(_Conta), defaultdict(_Conta)
    linhas_do_sku, linhas_do_cod = defaultdict(list), defaultdict(list)
    ant_sku_mlb, ant_cod_mlb = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    memo = {}

    def atribuir(seller_sku, mlb, variation_id):
        chave = (seller_sku, mlb, variation_id)
        resultado = memo.get(chave)
        if resultado is None:
            resultado = memo[chave] = _atribuir(cad, seller_sku, mlb, variation_id)
        return resultado

    # ---- período atual: 1 consulta, só as colunas necessárias, sem cancelados ----
    linhas = (VendaItemMercadoLivre.objects.filter(dia_venda__range=(de, hoje)).exclude(status=STATUS_CANCELADO)
              .values_list('order_id', 'seller_sku', 'mlb', 'variation_id', 'quantidade', 'preco_unitario', 'dia_venda', 'node_id', 'store_id', 'criado_em_ml'))
    for pedido, seller_sku, mlb, variation_id, qtd, preco, dia, node_id, store_id, quando in linhas:
        sku, codigo = atribuir(seller_sku, mlb, variation_id)
        origem = classificar_origem(node_id, store_id, no_proprio, mlb in fora_pela_logistica)
        completo = dia in completos
        for conta in (contas_sku[sku], contas_mlb[mlb], contas_cod[codigo]):
            conta.somar(qtd, preco, pedido, origem, completo, quando)
        contas_sku[sku].mlbs[mlb] += qtd
        contas_mlb[mlb].skus[sku] += qtd
        contas_cod[codigo].skus[sku] += qtd
        contas_cod[codigo].mlbs[mlb] += qtd
        linha = (mlb, qtd, preco, pedido, origem, completo, quando)
        linhas_do_sku[sku].append(linha)
        linhas_do_cod[codigo].append(linha)

    # ---- período anterior: 1 consulta já SOMADA por (seller_sku, mlb, variation_id) ----
    if tem_anterior:
        anteriores = (VendaItemMercadoLivre.objects.filter(dia_venda__range=(de_ant, ate_ant)).exclude(status=STATUS_CANCELADO).order_by()
                      .values_list('seller_sku', 'mlb', 'variation_id').annotate(un=Sum('quantidade')))
        for seller_sku, mlb, variation_id, un in anteriores:
            sku, codigo = atribuir(seller_sku, mlb, variation_id)
            contas_sku[sku].ant += un
            contas_mlb[mlb].ant += un
            contas_cod[codigo].ant += un
            ant_sku_mlb[sku][mlb] += un
            ant_cod_mlb[codigo][mlb] += un

    produtos = _carregar_produtos(set(cad['por_sku']) | {s for s in contas_sku if s})
    return {
        'de': de, 'recortado': recortado, 'dias': len(dias_do_periodo), 'de_ant': de_ant, 'ate_ant': ate_ant, 'tem_anterior': tem_anterior,
        'n_dias_ant': len(dias_ant), 'anterior_completo': anterior_completo, 'n_completos': len(completos), 'cob': cob,
        'cad': cad, 'produtos': produtos,
        'contas_sku': contas_sku, 'contas_mlb': contas_mlb, 'contas_cod': contas_cod,
        'linhas_do_sku': linhas_do_sku, 'linhas_do_cod': linhas_do_cod, 'ant_sku_mlb': ant_sku_mlb, 'ant_cod_mlb': ant_cod_mlb,
    }


# Função Objetivo: Os números de uma conta já prontos para ordenar, filtrar e mostrar: unidades, pedidos, faturamento, Full, fora, média por dia e "vs. anterior".
def _metricas(conta, calc):
    media = conta.un_comp / calc['n_completos'] if calc['n_completos'] else None
    media_ant = conta.ant / calc['n_dias_ant'] if calc['anterior_completo'] and calc['n_dias_ant'] else None
    delta = (media / media_ant - 1) * 100 if media is not None and media_ant else None
    if delta is None:
        categoria = 'sem'
    elif delta >= LIMITE_DA_TENDENCIA_PCT:
        categoria = 'up'
    elif delta <= -LIMITE_DA_TENDENCIA_PCT:
        categoria = 'down'
    else:
        categoria = 'flat'
    novo = calc['anterior_completo'] and media is not None and media_ant == 0 and conta.un > 0
    return {'un': conta.un, 'ped': len(conta.pedidos), 'fat': conta.fat, 'fu': conta.full, 'fo': conta.fora, 'indef': conta.indef, 'un_preco': conta.un_preco,
            'media': media, 'media_ant': media_ant, 'delta': delta, 'cat': categoria, 'novo': novo, 'ult': conta.ult, 'un_comp': conta.un_comp, 'ant': conta.ant}


# Função Objetivo: Os textos e as larguras de uma linha (ou de uma linha de dentro), prontos para o template.
def _visual(m, calc, periodo, hoje):
    un = m['un']
    if m['cat'] == 'sem':
        classe, texto = 'nenhuma', ('Novo' if m['novo'] else '—')
    else:
        classe = {'up': 'sobe', 'down': 'desce', 'flat': 'igual'}[m['cat']]
        texto = _com_sinal(m['delta'])
    if m['media'] is None:
        titulo_t = 'Sem dia completo coletado da conta toda neste período: não dá para comparar.'
    elif not calc['tem_anterior']:
        titulo_t = 'Sem comparação: o período anterior ficaria fora dos 12 meses que o Mercado Livre guarda.'
    elif not calc['anterior_completo']:
        titulo_t = 'Sem comparação: o período anterior ainda não foi coletado por inteiro (conta toda).'
    elif m['novo']:
        titulo_t = f'Novo: sem vendas {frase_no_anterior(periodo)}.'
    elif m['media_ant'] == 0:
        titulo_t = f'Sem vendas {frase_no_anterior(periodo)} e sem vendas agora.'
    else:
        titulo_t = f'{_decimal_br(m["media"])} un/dia, contra {_decimal_br(m["media_ant"])} un/dia {frase_no_anterior(periodo)}.'
    return {
        'un': numero(un), 'ped': numero(m['ped']), 'fat': _reais(m['fat']), 'fat_titulo': _reais_com_centavos(m['fat']),
        'fu': numero(m['fu']), 'fo': numero(m['fo']), 'p_fu': f'{_pct(m["fu"], un)}%', 'p_fo': f'{_pct(m["fo"], un)}%',
        'l_fu': round(m['fu'] / un * 100, 1) if un else 0, 'l_fo': round(m['fo'] / un * 100, 1) if un else 0,
        'sem_origem': numero(m['indef']) if m['indef'] else '',
        'media': _decimal_br(m['media']) if m['media'] is not None else '—',
        't_texto': texto, 't_classe': classe, 't_titulo': titulo_t,
        'ult': _texto_ultima_venda(m['ult'], hoje),
        'preco_medio': _reais_com_centavos(m['fat'] / m['un_preco']) if m['un_preco'] else '',
    }


# ==================================================== as linhas de cada nível ====================================================

# Função Objetivo: O endereço da tela do produto (o calendário de vendas) já no nível e no item da linha: ?sku=&nivel=&item=&periodo=.
def _endereco_do_calendario(link, periodo, base_url):
    if not link:
        return ''
    return url_da_tela(base_url, sku=link['sku'], periodo=periodo if periodo != PERIODO_PADRAO else None,
                       nivel=link['nivel'] if link['nivel'] != 'produto' else None, item=link['item'])


def _nova_linha(chave, titulo, marca, meta, conta, calc, partes, link=None, motivo='', alerta=False, selo='', foto='', codigo=False, plano=False):
    return {'chave': chave, 'titulo': titulo, 'titulo_ordem': _sem_acento(titulo), 'marca': marca, 'meta': meta, 'alerta': alerta, 'selo': selo, 'foto': foto,
            'conta': conta, 'm': _metricas(conta, calc), 'partes': partes, 'link': link, 'motivo': motivo, 'codigo': codigo, 'plano': plano,
            'filhos': [], 'filhos_nota': ''}


def _juntar(*partes):
    return ' · '.join(p for p in partes if p)


# Função Objetivo: As linhas do nível "Produto (SKU)": todo SKU com anúncio (tenha vendido ou não) + todo SKU que vendeu + a linha "Sem cadastro" (vendas que
# não dá para ligar a nenhum SKU).
def _linhas_de_sku(calc):
    cad, produtos, contas = calc['cad'], calc['produtos'], calc['contas_sku']
    linhas = []
    for sku in set(cad['por_sku']) | set(contas):
        conta = contas.get(sku) or _Conta()
        if sku == '':
            n = len(conta.mlbs)
            linhas.append(_nova_linha(
                SEM_CADASTRO, 'Sem cadastro', '', f'{n} {_s(n, "MLB que vendeu", "MLBs que venderam")} sem SKU no pedido e sem um SKU único no cadastro de anúncios',
                conta, calc, ['sem cadastro'] + sorted(conta.mlbs), motivo='Sem SKU: o calendário abre por produto', alerta=True, selo='Fora de Anúncios'))
            continue
        produto = produtos.get(sku)
        mlbs_cad = cad['por_sku'].get(sku, {}).get('mlbs', {})
        todos_mlbs = set(mlbs_cad) | set(conta.mlbs)
        codigos = {c for m in mlbs_cad.values() for _, c in m['variacoes'] if c}
        marca = produto['marca'] if produto else ''
        n_mlbs, n_cod = len(todos_mlbs), len(codigos)
        meta = _juntar(f'SKU {sku}', marca, f'{n_mlbs} {_s(n_mlbs, "anúncio", "anúncios")}', f'{n_cod} {_s(n_cod, "Código ML", "Códigos ML")}' if n_cod else 'sem Código ML')
        linhas.append(_nova_linha(
            sku, (produto or {}).get('titulo') or '(SKU fora do cadastro de Produto)', marca, meta, conta, calc,
            [sku, (produto or {}).get('titulo', ''), marca, (produto or {}).get('ean', '')] + sorted(todos_mlbs) + sorted(codigos),
            link={'sku': sku, 'nivel': 'produto', 'item': ''}, alerta=produto is None, selo='' if produto else 'Fora de Produto', foto=(produto or {}).get('imagem', '')))
    return linhas


# Função Objetivo: As linhas do nível "Anúncio (MLB)": todo MLB do cadastro de anúncios + todo MLB que vendeu (inclusive o que não está no cadastro: "Sem cadastro").
def _linhas_de_mlb(calc):
    cad, produtos, contas = calc['cad'], calc['produtos'], calc['contas_mlb']
    linhas = []
    for mlb in set(cad['anuncios']) | set(contas):
        conta = contas.get(mlb) or _Conta()
        anuncio = cad['anuncios'].get(mlb)
        skus_do_mlb = {s for s in conta.skus if s} | set(cad['candidatos'].get(mlb, {}))
        sku = _dominante(conta.skus) or (sorted(skus_do_mlb)[0] if skus_do_mlb else '')
        mais = len(skus_do_mlb) - 1 if len(skus_do_mlb) > 1 else 0
        produto = produtos.get(sku)
        codigos = sorted({c for _, c in anuncio['variacoes'] if c}) if anuncio else []
        if anuncio is None:
            situacao = 'fora de Anúncios'
        elif not codigos:
            situacao = 'fora do Full'
        else:
            situacao = f'Código ML {codigos[0]}' if len(codigos) == 1 else f'{len(codigos)} Códigos ML'
        titulo = (anuncio or {}).get('titulo') or (produto or {}).get('titulo') or 'Título indisponível (MLB fora de Anúncios)'
        marca = (produto or {}).get('marca', '')
        meta = _juntar(mlb, (f'SKU {sku}' + (f' +{mais}' if mais else '')) if sku else 'sem SKU', _rotulo_do_tipo((anuncio or {}).get('tipo')), situacao)
        linhas.append(_nova_linha(
            mlb, titulo, marca, meta, conta, calc, [mlb, titulo, sku, marca, (produto or {}).get('ean', '')] + codigos,
            link={'sku': sku, 'nivel': 'mlb', 'item': mlb} if sku else None, motivo='Sem SKU: o calendário abre por produto', alerta=anuncio is None,
            selo='Sem cadastro' if anuncio is None else '', foto=(produto or {}).get('imagem', ''), plano=True))
        linhas[-1]['anuncio'] = _cartao_do_anuncio(mlb, anuncio, produto, sku, codigos, 'Sem cadastro' if anuncio is None else '', 'sem')
    return linhas


# Função Objetivo: As linhas do nível "Código ML": todo Código ML do cadastro + todo Código que vendeu + a linha "Sem Código ML" (anúncios que nunca tiveram Código).
def _linhas_de_codigo(calc):
    cad, produtos, contas = calc['cad'], calc['produtos'], calc['contas_cod']
    linhas = []
    for codigo in set(cad['codigos']) | {c for c in contas if c}:
        conta = contas.get(codigo) or _Conta()
        dados = cad['codigos'].get(codigo) or {'mlbs': set(), 'skus': set()}
        skus_cad = sorted(dados['skus'])
        sku = _dominante(conta.skus) or (skus_cad[0] if skus_cad else '')
        produto = produtos.get(sku)
        mlbs = set(dados['mlbs']) | set(conta.mlbs)
        marca = (produto or {}).get('marca', '')
        meta = _juntar((produto or {}).get('titulo', ''), f'SKU {sku}' if sku else 'sem SKU ligado', f'{len(mlbs)} {_s(len(mlbs), "anúncio", "anúncios")}')
        linhas.append(_nova_linha(
            codigo, codigo, marca, meta, conta, calc, [codigo, (produto or {}).get('titulo', ''), sku, marca, (produto or {}).get('ean', '')] + sorted(mlbs),
            link={'sku': sku, 'nivel': 'codigo', 'item': codigo} if sku else None, motivo='Sem SKU ligado a este Código ML', foto=(produto or {}).get('imagem', ''), codigo=True))
    conta = contas.get('') or _Conta()
    sem_codigo_no_cadastro = {mlb for mlb, a in cad['anuncios'].items() if not any(c for _, c in a['variacoes'])}
    todos = sem_codigo_no_cadastro | set(conta.mlbs)
    if todos or conta.un or conta.ant:
        sem_cadastro = len(set(conta.mlbs) - set(cad['anuncios']))
        meta = f'{len(todos)} {_s(len(todos), "anúncio", "anúncios")} sem Código ML' + (f' ({sem_cadastro} sem cadastro)' if sem_cadastro else '')
        linhas.append(_nova_linha(
            SEM_CODIGO, 'Sem Código ML', '', meta, conta, calc, ['sem codigo ml', 'fora do full'] + sorted(todos),
            motivo='Linha que junta vários anúncios sem Código ML. Abra pelo MLB dentro dela.', alerta=True, selo='Fora do Full'))
    return linhas


CONSTRUTORES = {'sku': _linhas_de_sku, 'mlb': _linhas_de_mlb, 'codigo': _linhas_de_codigo}


# Função Objetivo: As linhas de DENTRO de uma linha aberta (os MLBs de um SKU ou de um Código ML), com o chip de Código ML, o tipo/preço médio e o link do
# calendário já no MLB. Só é chamada para as linhas da página que está na tela. Devolve (lista de linhas de dentro, nota sobre as que ficaram de fora).
def _filhos(gran, linha, calc, periodo, hoje, base_url):
    cad = calc['cad']
    chave = linha['chave']
    if gran == 'sku':
        sku = '' if chave == SEM_CADASTRO else chave
        indice, anteriores = calc['linhas_do_sku'].get(sku, ()), calc['ant_sku_mlb'].get(sku, {})
        do_cadastro = set(cad['por_sku'].get(sku, {}).get('mlbs', {})) if sku else set()
    else:
        codigo = '' if chave == SEM_CODIGO else chave
        indice, anteriores = calc['linhas_do_cod'].get(codigo, ()), calc['ant_cod_mlb'].get(codigo, {})
        do_cadastro = set((cad['codigos'].get(codigo) or {}).get('mlbs', ())) if codigo else set()
    contas = {}
    for mlb, qtd, preco, pedido, origem, completo, quando in indice:
        contas.setdefault(mlb, _Conta()).somar(qtd, preco, pedido, origem, completo, quando)
    for mlb, un in anteriores.items():
        contas.setdefault(mlb, _Conta())
    for mlb, conta in contas.items():
        conta.ant = anteriores.get(mlb, 0)
    mlbs = set(contas) | do_cadastro
    nota = ''
    if chave == SEM_CODIGO:
        # Todos os anúncios sem Código ML sem venda encheriam a linha de centenas de MLBs: só os que venderam (no período ou no anterior) e no máximo
        # MAX_FILHOS_SEM_CODIGO; o resto vira uma nota.
        sem_codigo = {mlb for mlb, a in cad['anuncios'].items() if not any(c for _, c in a['variacoes'])} | set(contas)
        com_dado = sorted((m for m in mlbs if m in contas and (contas[m].un or contas[m].ant)), key=lambda m: (-contas[m].un, m))
        mostrar = com_dado[:MAX_FILHOS_SEM_CODIGO]
        ficaram = len(sem_codigo) - len(mostrar)
        if ficaram > 0:
            nota = f'… e mais {numero(ficaram)} {_s(ficaram, "anúncio", "anúncios")} sem Código ML, sem venda no período (ou além do limite de {MAX_FILHOS_SEM_CODIGO} linhas desta lista).'
        mlbs = set(mostrar)
        ordem = mostrar
    else:
        ordem = sorted(mlbs, key=lambda m: (-(contas[m].un if m in contas else 0), m))
    sku_da_linha = ((linha['link'] or {}).get('sku') or '') if gran == 'codigo' else sku

    filhos = []
    for mlb in ordem:
        conta = contas.get(mlb) or _Conta()
        anuncio = cad['anuncios'].get(mlb)
        do_sku = cad['por_sku'].get(sku, {}).get('mlbs', {}) if gran == 'sku' and sku else {}
        if gran == 'sku' and sku and mlb in do_sku:
            variacoes = do_sku[mlb]['variacoes']
        else:
            variacoes = anuncio['variacoes'] if anuncio else []
        codigos = sorted({c for _, c in variacoes if c})
        aviso = ''
        if anuncio is None:
            aviso = 'Sem cadastro'
        elif gran == 'sku' and sku and mlb not in do_sku:
            aviso = 'Fora do cadastro do SKU'
        m = _metricas(conta, calc)
        v = _visual(m, calc, periodo, hoje)
        sku_do_mlb = sku_da_linha or _dominante((calc['contas_mlb'].get(mlb) or _Conta()).skus) if chave == SEM_CODIGO else sku_da_linha
        link = {'sku': sku_do_mlb, 'nivel': 'mlb', 'item': mlb} if sku_do_mlb else None
        cartao = _cartao_do_anuncio(mlb, anuncio, calc['produtos'].get(sku_do_mlb), sku_do_mlb, codigos, aviso, 'sem')
        filhos.append({'rotulo': mlb, 'anuncio': cartao, 'v': v, 'url_calendario': _endereco_do_calendario(link, periodo, base_url),
                       'motivo': 'Sem SKU: o calendário abre por produto'})
    return filhos, nota


# ==================================================== a página da lista ====================================================

def _escolher(parametros, nome, validos, padrao):
    valor = (parametros.get(nome) or '').strip()
    return valor if valor in validos else padrao


# Função Objetivo: Os números de PÁGINAS que aparecem na paginação (a primeira, a última e as vizinhas da atual); None = "…" entre dois saltos.
def _janela_de_paginas(atual, total):
    paginas = sorted({1, total} | {p for p in range(atual - 2, atual + 3) if 1 <= p <= total})
    saida = []
    for p in paginas:
        if saida and p - saida[-1] > 1:
            saida.append(None)
        saida.append(p)
    return saida


# Função Objetivo: Tudo da lista a partir da query string. Parâmetros: gran (sku|mlb|codigo), periodo, q (busca), marca, sit (todos|com|sem|alerta),
# tend (todas|up|flat|down|sem), ori (todas|full|fora|ambos), ord + dir (coluna e sentido), por (linhas por página) e pag. Parâmetro inválido volta ao padrão.
def montar_lista(parametros, base_url, hoje):
    periodo = normalizar_periodo(parametros.get('periodo') or parametros.get('dias'))
    por_chave = {g[0]: g for g in GRANULARIDADES}
    gran = _escolher(parametros, 'gran', por_chave, GRANULARIDADE_PADRAO)
    _, _, ajuda, rotulo_alerta, unidade_plural, unidade_singular = por_chave[gran]
    texto = (parametros.get('q') or '').strip()
    marca = (parametros.get('marca') or '').strip()
    sit = _escolher(parametros, 'sit', SITUACOES, 'todos')
    tend = _escolher(parametros, 'tend', TENDENCIAS, 'todas')
    ori = _escolher(parametros, 'ori', ORIGENS, 'todas')
    ordem = _escolher(parametros, 'ord', COLUNAS, 'un')
    direcao = _escolher(parametros, 'dir', ('asc', 'desc'), 'asc' if ordem in COLUNAS_DE_ORDEM_CRESCENTE else 'desc')
    por = _inteiro(parametros.get('por'), POR_PAGINA_PADRAO)
    por = por if por in POR_PAGINA_OPCOES else POR_PAGINA_PADRAO
    numero_da_pagina = max(1, _inteiro(parametros.get('pag'), 1))

    padroes = {'gran': GRANULARIDADE_PADRAO, 'periodo': PERIODO_PADRAO, 'sit': 'todos', 'tend': 'todas', 'ori': 'todas', 'por': POR_PAGINA_PADRAO, 'pag': 1}

    def parametros_da_url(mudancas):
        atuais = {'gran': gran, 'periodo': periodo, 'q': texto, 'marca': marca, 'sit': sit, 'tend': tend, 'ori': ori, 'ord': ordem, 'dir': direcao, 'por': por,
                  'pag': numero_da_pagina}
        atuais.update(mudancas)
        if 'pag' not in mudancas:
            atuais['pag'] = 1   # qualquer mudança de filtro, busca ou ordem volta para a página 1
        limpos = {k: (None if v == padroes.get(k) else v) for k, v in atuais.items()}
        if (atuais['ord'], atuais['dir']) == ('un', 'desc'):
            limpos['ord'] = limpos['dir'] = None
        return limpos

    def url(**mudancas):
        return url_da_tela(base_url, **parametros_da_url(mudancas))

    calc = _calcular(periodo, hoje)
    todas = CONSTRUTORES[gran](calc)

    # ---- busca e marca (a base dos números dos filtros) ----
    marcas = sorted({l['marca'] for l in todas if l['marca']}, key=_sem_acento)
    procurado = _sem_acento(texto)
    base = [l for l in todas if (not marca or l['marca'] == marca) and (not procurado or procurado in _sem_acento(' '.join(l['partes'])))]

    def ok_sit(l, k):
        return k == 'todos' or (k == 'com' and l['m']['un'] > 0) or (k == 'sem' and l['m']['un'] == 0) or (k == 'alerta' and l['alerta'])

    def ok_tend(l, k):
        return k == 'todas' or l['m']['cat'] == k

    def ok_ori(l, k):
        fu, fo = l['m']['fu'], l['m']['fo']
        return k == 'todas' or (k == 'full' and fu > 0 and fo == 0) or (k == 'fora' and fo > 0 and fu == 0) or (k == 'ambos' and fu > 0 and fo > 0)

    def contar(predicado):
        return sum(1 for l in base if predicado(l))

    def chip(parametro, atual, valor, rotulo, n):
        return {'rotulo': rotulo, 'n': numero(n), 'ativo': atual == valor, 'vazio': n == 0, 'url': url(**{parametro: valor})}

    grupos_chips = [
        {'titulo': 'Situação', 'chips': [
            chip('sit', sit, 'todos', 'Todos', len(base)), chip('sit', sit, 'com', 'Com venda', contar(lambda l: l['m']['un'] > 0)),
            chip('sit', sit, 'sem', 'Sem venda no período', contar(lambda l: l['m']['un'] == 0)), chip('sit', sit, 'alerta', rotulo_alerta, contar(lambda l: l['alerta']))]},
        {'titulo': 'Tendência', 'chips': [
            chip('tend', tend, 'todas', 'Todas', len(base)), chip('tend', tend, 'up', 'Subindo', contar(lambda l: l['m']['cat'] == 'up')),
            chip('tend', tend, 'flat', 'Estável', contar(lambda l: l['m']['cat'] == 'flat')), chip('tend', tend, 'down', 'Caindo', contar(lambda l: l['m']['cat'] == 'down')),
            chip('tend', tend, 'sem', 'Sem comparação', contar(lambda l: l['m']['cat'] == 'sem'))]},
        {'titulo': 'Origem', 'chips': [
            chip('ori', ori, 'todas', 'Todas', len(base)), chip('ori', ori, 'full', 'Só Full', contar(lambda l: ok_ori(l, 'full'))),
            chip('ori', ori, 'fora', 'Só fora do Full', contar(lambda l: ok_ori(l, 'fora'))), chip('ori', ori, 'ambos', 'Full e fora do Full', contar(lambda l: ok_ori(l, 'ambos')))]},
    ]
    filtradas = [l for l in base if ok_sit(l, sit) and ok_tend(l, tend) and ok_ori(l, ori)]

    # ---- ordem: quem não tem o valor (ex.: sem comparação) fica sempre no fim; empate desempata pelo nome ----
    def valor_de_ordem(l):
        m = l['m']
        if ordem == 'nome':
            return l['titulo_ordem']
        if ordem == 'ult':
            return -m['ult'].timestamp() if m['ult'] else None   # crescente = a venda mais recente primeiro
        return {'un': m['un'], 'ped': m['ped'], 'fat': m['fat'], 'fu': m['fu'], 'fo': m['fo'], 'media': m['media'], 'delta': m['delta']}[ordem]

    com_valor = [l for l in filtradas if valor_de_ordem(l) is not None]
    sem_valor = sorted((l for l in filtradas if valor_de_ordem(l) is None), key=lambda l: l['titulo_ordem'])
    com_valor.sort(key=lambda l: l['titulo_ordem'])
    com_valor.sort(key=valor_de_ordem, reverse=direcao == 'desc')
    filtradas = com_valor + sem_valor

    # ---- resumo (todas as linhas filtradas, não só a página) ----
    un = sum(l['m']['un'] for l in filtradas)
    pedidos = len(set().union(*(l['conta'].pedidos for l in filtradas))) if filtradas else 0
    fat = sum((l['m']['fat'] for l in filtradas), Decimal('0'))
    fu, fo, indef = (sum(l['m'][c] for l in filtradas) for c in ('fu', 'fo', 'indef'))
    un_comp, ant = sum(l['m']['un_comp'] for l in filtradas), sum(l['m']['ant'] for l in filtradas)
    media = un_comp / calc['n_completos'] if calc['n_completos'] else None
    media_ant = ant / calc['n_dias_ant'] if calc['anterior_completo'] and calc['n_dias_ant'] else None
    delta = (media / media_ant - 1) * 100 if media is not None and media_ant else None
    if delta is not None:
        delta_classe = 'sobe' if delta >= 0.5 else ('desce' if delta <= -0.5 else 'igual')
        vs_texto = frase_frente_ao_anterior(periodo)
    else:
        delta_classe = 'nenhuma'
        if not calc['tem_anterior']:
            vs_texto = 'Sem comparação: o período anterior ficaria fora dos 12 meses que o Mercado Livre guarda.'
        elif not calc['anterior_completo']:
            vs_texto = 'Sem comparação: o período anterior ainda não foi coletado por inteiro.'
        else:
            vs_texto = 'Sem comparação: nenhum dia completo coletado neste período.'
    dias = calc['dias']
    resumo = {
        'un': numero(un), 'delta_texto': _com_sinal(delta) if delta is not None else '—', 'delta_classe': delta_classe, 'vs_texto': vs_texto,
        'periodo_texto': f'{calc["de"]:%d/%m/%Y} a {hoje:%d/%m/%Y} · {dias} dias' + (' · limite do ML' if calc['recortado'] else '')
                         + (f' · média de {_decimal_br(media)} por dia' if media is not None else ''),
        'ped': numero(pedidos), 'un_por_ped': _decimal_br(un / pedidos) if pedidos else '0,0',
        'fat': _reais(fat), 'ticket': _reais(fat / pedidos) if pedidos else 'R$ 0',
        'full': numero(fu), 'p_full': f'{_pct(fu, un)}%', 'fora': numero(fo), 'p_fora': f'{_pct(fo, un)}%', 'sem_origem': numero(indef) if indef else '',
    }

    # ---- cobertura da conta toda e pontos de atenção (sobre a lista inteira, sem filtros) ----
    cob = calc['cob']
    cobertura_info = {
        'periodo': f'{calc["de"]:%d/%m/%Y} a {hoje:%d/%m/%Y}', 'n_dias': dias, 'n_com_dado': len(cob), 'n_completos': calc['n_completos'],
        'ultima': data_hora(max(cob.values())) if cob else '', 'nada_coletado': not cob, 'tudo_coletado': len(cob) == dias,
    }
    avisos = []
    if cob and calc['n_completos'] < dias:
        faltam = dias - calc['n_completos']
        avisos.append(f'{faltam} {_s(faltam, "dia do período ainda não está completo", "dias do período ainda não estão completos")} na coleta da conta toda (parcial ou sem coleta): '
                      f'as vendas {_s(faltam, "dele entram", "deles entram")} nas unidades, mas não na média por dia nem em "vs. anterior".')
    total_indef = sum(c.indef for c in calc['contas_sku'].values())
    if total_indef:
        avisos.append(f'{numero(total_indef)} un vendidas sem centro de estoque (node_id) no pedido: entram no total, mas não em Full nem em Fora do Full.')
    sem_cadastro = calc['contas_sku'].get('')
    if sem_cadastro and sem_cadastro.un:
        avisos.append(f'{numero(sem_cadastro.un)} un vendidas sem SKU no pedido e sem um SKU único no cadastro de anúncios: ficam na linha "Sem cadastro".')
    sem_codigo = calc['contas_cod'].get('')
    if sem_codigo and sem_codigo.full:
        avisos.append(f'{numero(sem_codigo.full)} un de anúncios sem Código ML no banco saíram de um centro do Full: o Código ML desses anúncios pode estar faltando.')
    if calc['tem_anterior'] and not calc['anterior_completo']:
        avisos.append('O período anterior ainda não foi coletado por inteiro (conta toda): "vs. anterior" fica em "—" até a coleta terminar.')

    # ---- página atual ----
    total = len(filtradas)
    total_paginas = max(1, -(-total // por))
    pagina_atual = min(numero_da_pagina, total_paginas)
    ini = (pagina_atual - 1) * por
    fim = min(total, ini + por)
    linhas = []
    for l in filtradas[ini:fim]:
        l['filhos'], l['filhos_nota'] = ([], '') if l['plano'] else _filhos(gran, l, calc, periodo, hoje, base_url)
        l['v'] = _visual(l['m'], calc, periodo, hoje)
        l['url_calendario'] = _endereco_do_calendario(l['link'], periodo, base_url)
        linhas.append(l)

    # ---- controles: ver por, períodos, selects, colunas ----
    ordens_prontas = {(c, d) for c, d, _ in ORDENS_PRONTAS}
    ordens = [{'rotulo': r, 'url': url(**{'ord': c, 'dir': d}), 'ativo': (c, d) == (ordem, direcao)} for c, d, r in ORDENS_PRONTAS]
    if (ordem, direcao) not in ordens_prontas:
        ordens.append({'rotulo': 'Pela coluna escolhida', 'url': '', 'ativo': True, 'desabilitada': True})

    def sentido_ao_clicar(coluna):
        if coluna == ordem:
            return 'asc' if direcao == 'desc' else 'desc'
        return 'asc' if coluna in COLUNAS_DE_ORDEM_CRESCENTE else 'desc'

    colunas = {c: {'url': url(**{'ord': c, 'dir': sentido_ao_clicar(c)}), 'ativa': c == ordem, 'sentido': direcao} for c in COLUNAS}
    rotulos_das_colunas = {'nome': por_chave[gran][1], 'un': 'Unidades', 'ped': 'Pedidos', 'fat': 'Faturamento', 'fu': 'Full', 'fo': 'Fora do Full',
                           'media': 'Média/dia', 'delta': 'vs. anterior', 'ult': 'Última venda'}
    cabecalho = [{'chave': c, 'rotulo': rotulos_das_colunas[c], **colunas[c]} for c in COLUNAS]
    ocultos = [{'nome': k, 'valor': v} for k, v in parametros_da_url({'q': None}).items() if v not in (None, '') and k != 'pag']

    return {
        'gran': gran,
        'granularidades': [{'chave': g[0], 'rotulo': g[1], 'ativo': g[0] == gran, 'url': url(gran=g[0], sit='todos', tend='todas', ori='todas')} for g in GRANULARIDADES],
        'ajuda': ajuda, 'periodos': [{**p, 'ativo': p['chave'] == periodo, 'url': url(periodo=p['chave'])} for p in periodos_de_hoje(hoje)],
        'cobertura': cobertura_info, 'avisos': avisos,
        'marca': marca, 'marcas': [{'rotulo': 'Todas as marcas', 'url': url(marca=''), 'ativo': not marca}] + [{'rotulo': m, 'url': url(marca=m), 'ativo': m == marca} for m in marcas],
        'ordens': ordens, 'por_pagina': [{'rotulo': str(p), 'url': url(por=p), 'ativo': p == por} for p in POR_PAGINA_OPCOES],
        'grupos_chips': grupos_chips, 'resumo': resumo,
        'total_texto': f'{numero(total)} {unidade_singular if total == 1 else unidade_plural} com os filtros atuais', 'pode_abrir': gran != 'mlb',
        'coluna_nome': por_chave[gran][1], 'colunas': colunas, 'cabecalho': cabecalho, 'limite_da_tendencia': LIMITE_DA_TENDENCIA_PCT, 'linhas': linhas, 'vazio': total == 0,
        'filtros_ativos': bool(texto or marca or sit != 'todos' or tend != 'todas' or ori != 'todas'),
        'paginacao': {
            'numero': pagina_atual, 'total_paginas': total_paginas,
            'texto': 'Nenhum item' if not total else f'Mostrando {numero(ini + 1)}–{numero(fim)} de {numero(total)} {unidade_plural}',
            'url_anterior': url(pag=pagina_atual - 1) if pagina_atual > 1 else '', 'url_proxima': url(pag=pagina_atual + 1) if pagina_atual < total_paginas else '',
            'janela': [{'numero': p, 'url': url(pag=p), 'atual': p == pagina_atual} if p else {'reticencias': True} for p in _janela_de_paginas(pagina_atual, total_paginas)],
        },
        'url_limpar_busca': url(q=''), 'url_limpar_tudo': url(q='', marca='', sit='todos', tend='todas', ori='todas'), 'busca_ocultos': ocultos,
    }
