# * [RESUMO] → Lógica de classificação e agrupamento de anúncios por SKU,
#              respeitando a hierarquia: Página de Catálogo → Base →
#              Catálogos, e Anúncios Simples separados.
#              Portado de classificar_por_SKU.py (script paralelo de API),
#              adaptado para rodar sobre o banco em vez de JSON.
#
#              Uso em massa: carregar_anuncios_por_sku() faz 1 única query,
#              agrupando tudo em memória — nunca query por SKU dentro de loop.

import json as jsonlib
from collections import defaultdict
from django.db.models import Q
from produtos.models import Produto
from mercado_livre.models import VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre


def parsear_item_relations(valor):
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        try:
            return jsonlib.loads(valor)
        except Exception:
            return []
    return []


def carregar_anuncios_por_sku():
    # * [EXPLICAÇÃO] → 1 única query para todo o banco. Um AnuncioMercadoLivre
    #                  pode ter variações de SKUs diferentes — por isso o
    #                  agrupamento é por SKU, não por anúncio.
    anuncios_por_sku = defaultdict(set)

    variacoes = VariacaoAnuncioMercadoLivre.objects.select_related(
        'anuncio', 'anuncio__tipo_de_anuncio', 'produto'
    ).exclude(produto__isnull=True)

    for v in variacoes:
        anuncios_por_sku[v.produto.sku].add(v.anuncio)

    return anuncios_por_sku


def montar_estrutura_de_sku(sku, anuncios):
    # * [EXPLICAÇÃO] → Recebe o conjunto de AnuncioMercadoLivre já carregado
    #                  (vindo de carregar_anuncios_por_sku()) — não faz
    #                  nenhuma query nova.
    if not anuncios:
        return {'sku': sku, 'encontrado': False, 'paginas_catalogo': [], 'anuncios_simples': []}

    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo
    paginas = {}
    simples = []

    for anuncio in anuncios:
        tipo = anuncio.tipo_de_anuncio
        classificacao = tipo.classificacao_catalogo if tipo else None

        if classificacao == Classificacao.SIMPLES or not anuncio.catalog_product_id:
            simples.append(anuncio)
            continue

        paginas.setdefault(anuncio.catalog_product_id, []).append(anuncio)

    def info_basica(anuncio):
        return {'mlb': anuncio.mlb, 'titulo': anuncio.titulo_anuncio}

    paginas_saida = []
    for cpid, membros in paginas.items():
        bases = [a for a in membros if a.tipo_de_anuncio and a.tipo_de_anuncio.classificacao_catalogo == Classificacao.BASE]
        catalogos = [a for a in membros if a.tipo_de_anuncio and a.tipo_de_anuncio.classificacao_catalogo == Classificacao.CATALOGO]

        bases_saida = []
        catalogos_usados = set()

        for base in bases:
            relacoes = parsear_item_relations(base.item_relations)
            filhos_ids = {r.get('id') for r in relacoes if isinstance(r, dict)}
            filhos = [c for c in catalogos if c.mlb in filhos_ids]
            catalogos_usados.update(f.mlb for f in filhos)

            base_info = info_basica(base)
            base_info['anuncios_catalogo'] = [info_basica(c) for c in filhos]
            bases_saida.append(base_info)

        orfaos = [c for c in catalogos if c.mlb not in catalogos_usados]

        paginas_saida.append({
            'catalog_product_id': cpid,
            'anuncios_base': bases_saida,
            'anuncios_catalogo_orfaos': [info_basica(c) for c in orfaos],
        })

    return {
        'sku': sku,
        'encontrado': True,
        'total_anuncios': len(anuncios),
        'paginas_catalogo': paginas_saida,
        'anuncios_simples': [info_basica(a) for a in simples],
    }


def classificar_todos_os_skus():
    # * [EXPLICAÇÃO] → Ponto de entrada para validação/uso em massa.
    #                  Retorna {sku: estrutura}, para todos os SKUs do banco.
    anuncios_por_sku = carregar_anuncios_por_sku()
    return {
        sku: montar_estrutura_de_sku(sku, anuncios)
        for sku, anuncios in anuncios_por_sku.items()
    }

def listar_skus_filtrados(busca=None):
    # * [EXPLICAÇÃO] → Só a lista de SKUs (sem árvore, sem anúncio) —
    #                  usada para paginação. Busca genérica: procura o
    #                  termo em SKU, Marca, MLB e Título simultaneamente.
    qs = VariacaoAnuncioMercadoLivre.objects.exclude(produto__isnull=True)

    if busca:
        qs = qs.filter(
            Q(produto__sku__icontains=busca) |
            Q(produto__marca__icontains=busca) |
            Q(anuncio__mlb__icontains=busca) |
            Q(anuncio__titulo_anuncio__icontains=busca)
        )

    return list(
        qs.select_related('produto')
        .values_list('produto__sku', flat=True)
        .distinct()
        .order_by('produto__sku')
    )


def classificar_lote_de_skus(skus):
    # * [EXPLICAÇÃO] → Mesma lógica de carregar_anuncios_por_sku(), mas
    #                  filtrada só para os SKUs do lote — nunca processa
    #                  o banco inteiro. Usada para montar a árvore só
    #                  dos SKUs da página atual.
    anuncios_por_sku = defaultdict(set)

    variacoes = VariacaoAnuncioMercadoLivre.objects.filter(
        produto__sku__in=skus
    ).select_related('anuncio', 'anuncio__tipo_de_anuncio', 'produto')

    for v in variacoes:
        anuncios_por_sku[v.produto.sku].add(v.anuncio)

    return {
        sku: montar_estrutura_de_sku(sku, anuncios)
        for sku, anuncios in anuncios_por_sku.items()
    }