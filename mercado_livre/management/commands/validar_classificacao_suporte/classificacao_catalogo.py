# * [RESUMO] → Lógica de classificação e agrupamento de anúncios por SKU,
#              respeitando a hierarquia: Página de Catálogo → Base →
#              Catálogos, e Anúncios Simples separados.
#
#              VOCABULÁRIO PADRONIZADO:
#              - SKU: identifica o Produto (ERP)
#              - MLB: identifica o AnuncioMercadoLivre (agrupador —
#                     status, tipo, catálogo, logística vêm daqui)
#              - Variação: identifica o VariacaoAnuncioMercadoLivre —
#                     a unidade individual real, SEMPRE existe pelo
#                     menos 1 por MLB (mesmo sem variação de cor/tamanho)
#              - Folha: o nó final da árvore = 1 Variação = 1 card na tela.
#                     Um MLB com 20 variações gera 20 folhas/cards.

import json as jsonlib
from collections import defaultdict
from django.db.models import Q
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre
import math

def parsear_item_relations(valor):
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        try:
            return jsonlib.loads(valor)
        except Exception:
            return []
    return []


def calcular_ponteiro_termometro(score):
    score = max(0, min(100, score or 0))
    angulo_graus = 180 - (score / 100 * 180)
    angulo_rad = math.radians(angulo_graus)
    x = 30 + 22 * math.cos(angulo_rad)
    y = 30 - 22 * math.sin(angulo_rad)
    return f'{x:.1f}', f'{y:.1f}'

CORTE_SCORE_VERMELHO_AMARELO = 33
CORTE_SCORE_AMARELO_VERDE = 66


def calcular_ponto_arco(porcentagem, raio=26, centro_x=30, centro_y=30):
    angulo_graus = 180 - (porcentagem / 100 * 180)
    angulo_rad = math.radians(angulo_graus)
    x = centro_x + raio * math.cos(angulo_rad)
    y = centro_y - raio * math.sin(angulo_rad)
    return f'{x:.1f}', f'{y:.1f}'


def montar_arcos_termometro():
    inicio = calcular_ponto_arco(0)
    corte1 = calcular_ponto_arco(CORTE_SCORE_VERMELHO_AMARELO)
    corte2 = calcular_ponto_arco(CORTE_SCORE_AMARELO_VERDE)
    fim = calcular_ponto_arco(100)

    return {
        'vermelho': f'M {inicio[0]} {inicio[1]} A 26 26 0 0 1 {corte1[0]} {corte1[1]}',
        'amarelo':  f'M {corte1[0]} {corte1[1]} A 26 26 0 0 1 {corte2[0]} {corte2[1]}',
        'verde':    f'M {corte2[0]} {corte2[1]} A 26 26 0 0 1 {fim[0]} {fim[1]}',
    }

def info_variacao(variacao, imagem_url=None, titulo_produto=None):
    anuncio = variacao.anuncio
    tipo = anuncio.tipo_de_anuncio if anuncio else None

    score_numerico = 0
    ponteiro_x, ponteiro_y = calcular_ponteiro_termometro(score_numerico)


    arcos = montar_arcos_termometro()



    Status = TipoDeAnuncioMercadoLivre.Status
    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
    TipoLogistico = TipoDeAnuncioMercadoLivre.TipoLogistico

    status_classe_map = {
        Status.ATIVO: 'ativo',
        Status.PAUSADO: 'pausado',
        Status.FECHADO: 'encerrado',
        Status.EM_REVISAO: 'revisao',
        Status.DEBITO_PENDENTE: 'debito',
        Status.AGUARDANDO_ATIVACAO: 'aguardando',
    }

    status = tipo.status if tipo else None
    
    tipo_anuncio_valor = tipo.tipo_anuncio if tipo else None
    tipo_logistico_valor = tipo.tipo_logistico if tipo else None

    return {
        'mlb': anuncio.mlb if anuncio else None,
        'variacao_id': variacao.variacao_id,
        'sku_ml': variacao.sku_ml,
        'titulo': anuncio.titulo_anuncio if anuncio else None,
        'permalink': anuncio.permalink if anuncio else None,
        'thumbnail_url': variacao.thumbnail_url,
        'imagem_principal_url': variacao.imagem_principal_url,
        'imagem_url': imagem_url,
        'titulo_produto': titulo_produto,

        'estoque': variacao.estoque,
        'score': score_numerico,
        'ponteiro_x': ponteiro_x,
        'ponteiro_y': ponteiro_y,
        'arco_vermelho': arcos['vermelho'],
        'arco_amarelo': arcos['amarelo'],
        'arco_verde': arcos['verde'],

        'status_classe': status_classe_map.get(status, 'default'),
        'status_label': dict(Status.choices).get(status, '—'),

        'tipo_anuncio_classe': 'premium' if tipo_anuncio_valor == TipoAnuncio.PREMIUM else 'classico',
        'badge_tipo': 'premium' if tipo_anuncio_valor == TipoAnuncio.PREMIUM else 'classico',
        'badge_tipo_label': dict(TipoAnuncio.choices).get(tipo_anuncio_valor, '—'),

        'badge_logistica': 'full' if tipo_logistico_valor == TipoLogistico.FULL else 'coleta',
        'badge_logistica_label': dict(TipoLogistico.choices).get(tipo_logistico_valor, '—'),

        'tem_flex': tipo.flex if tipo else False,
    }


def carregar_variacoes_por_sku(skus=None):
    qs = VariacaoAnuncioMercadoLivre.objects.select_related(
        'anuncio', 'anuncio__tipo_de_anuncio', 'produto'
    ).exclude(produto__isnull=True)

    if skus is not None:
        qs = qs.filter(produto__sku__in=skus)

    variacoes_por_sku = defaultdict(list)
    for v in qs:
        variacoes_por_sku[v.produto.sku].append(v)

    return variacoes_por_sku


def montar_estrutura_de_sku(sku, variacoes):
    if not variacoes:
        return {'sku': sku, 'encontrado': False, 'paginas_catalogo': [], 'anuncios_simples': [], 'total_anuncios': 0}

    # * [EXPLICAÇÃO] → Todas as variações do mesmo SKU compartilham o
    #                  mesmo Produto — pega do primeiro item da lista.
    produto = variacoes[0].produto

    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

    variacoes_por_mlb = defaultdict(list)
    anuncio_por_mlb = {}
    for v in variacoes:
        anuncio_por_mlb[v.anuncio.mlb] = v.anuncio
        variacoes_por_mlb[v.anuncio.mlb].append(v)

    paginas = {}
    simples_mlbs = []

    for mlb, anuncio in anuncio_por_mlb.items():
        tipo = anuncio.tipo_de_anuncio
        classificacao = tipo.classificacao_catalogo if tipo else None

        if classificacao == Classificacao.SIMPLES or not anuncio.catalog_product_id:
            simples_mlbs.append(mlb)
            continue

        paginas.setdefault(anuncio.catalog_product_id, []).append(mlb)

    def folhas_do_mlb(mlb):
        return [
            info_variacao(v, imagem_url=produto.imagem_url, titulo_produto=produto.titulo)
            for v in variacoes_por_mlb[mlb]
        ]

    paginas_saida = []
    for cpid, mlbs_membros in paginas.items():
        bases_mlbs = [
            m for m in mlbs_membros
            if anuncio_por_mlb[m].tipo_de_anuncio
            and anuncio_por_mlb[m].tipo_de_anuncio.classificacao_catalogo == Classificacao.BASE
        ]
        catalogos_mlbs = [
            m for m in mlbs_membros
            if anuncio_por_mlb[m].tipo_de_anuncio
            and anuncio_por_mlb[m].tipo_de_anuncio.classificacao_catalogo == Classificacao.CATALOGO
        ]

        bases_saida = []
        catalogos_usados = set()

        for base_mlb in bases_mlbs:
            relacoes = parsear_item_relations(anuncio_por_mlb[base_mlb].item_relations)
            filhos_ids = {r.get('id') for r in relacoes if isinstance(r, dict)}
            filhos_mlbs = [c for c in catalogos_mlbs if c in filhos_ids]
            catalogos_usados.update(filhos_mlbs)

            bases_saida.append({
                'mlb': base_mlb,
                'folhas': folhas_do_mlb(base_mlb),
                'anuncios_catalogo': [
                    {'mlb': c, 'folhas': folhas_do_mlb(c)}
                    for c in filhos_mlbs
                ],
            })

        orfaos_mlbs = [c for c in catalogos_mlbs if c not in catalogos_usados]

        paginas_saida.append({
            'catalog_product_id': cpid,
            'anuncios_base': bases_saida,
            'anuncios_catalogo_orfaos': [
                {'mlb': o, 'folhas': folhas_do_mlb(o)}
                for o in orfaos_mlbs
            ],
        })

    return {
        'sku': sku,
        'encontrado': True,
        'marca': produto.marca,
        'titulo_produto': produto.titulo,
        'imagem_url': produto.imagem_url,
        'total_anuncios': len(variacoes),
        'paginas_catalogo': paginas_saida,
        'anuncios_simples': [
            {'mlb': m, 'folhas': folhas_do_mlb(m)}
            for m in simples_mlbs
        ],
    }


def classificar_todos_os_skus():
    variacoes_por_sku = carregar_variacoes_por_sku()
    return {
        sku: montar_estrutura_de_sku(sku, variacoes)
        for sku, variacoes in variacoes_por_sku.items()
    }


def listar_skus_filtrados(busca=None):
    qs = VariacaoAnuncioMercadoLivre.objects.exclude(produto__isnull=True)

    if busca:
        termos = busca.split()  # * [EXPLICAÇÃO] → separa por espaço: "6671 guarany" → ["6671", "guarany"]

        for termo in termos:
            # * [EXPLICAÇÃO] → CADA termo precisa aparecer em ALGUM dos campos —
            #                  não precisam estar juntos, nem no mesmo campo.
            qs = qs.filter(
                Q(produto__sku__icontains=termo) |
                Q(produto__marca__icontains=termo) |
                Q(produto__titulo__icontains=termo) |
                Q(produto__ean__icontains=termo) |
                Q(anuncio__mlb__icontains=termo) |
                Q(anuncio__titulo_anuncio__icontains=termo)
            )

    return list(
        qs.select_related('produto')
        .values_list('produto__sku', flat=True)
        .distinct()
        .order_by('produto__sku')
    )


def classificar_lote_de_skus(skus):
    variacoes_por_sku = carregar_variacoes_por_sku(skus=skus)
    return {
        sku: montar_estrutura_de_sku(sku, variacoes)
        for sku, variacoes in variacoes_por_sku.items()
    }