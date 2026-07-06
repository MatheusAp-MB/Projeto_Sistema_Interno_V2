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
#
#              A classificação (Base/Catálogo/Simples) é do MLB — todas
#              as variações do mesmo MLB herdam a mesma classificação.

import json as jsonlib
from collections import defaultdict
from django.db.models import Q
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


def info_variacao(variacao):
    # * [EXPLICAÇÃO] → Monta o dict completo que o card precisa exibir.
    #                  1 variação = 1 folha = 1 card.
    anuncio = variacao.anuncio
    tipo = anuncio.tipo_de_anuncio if anuncio else None

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

        'estoque': variacao.estoque,
        'score': '000',  # * [EXPLICAÇÃO] → placeholder até o módulo de Reputação existir

        'status_classe': status_classe_map.get(status, 'default'),
        'status_label': dict(Status.choices).get(status, '—'),

        'tipo_anuncio_classe': 'premium' if tipo_anuncio_valor == TipoAnuncio.PREMIUM else 'classico',
        'badge_tipo': 'premium' if tipo_anuncio_valor == TipoAnuncio.PREMIUM else 'classico',
        'badge_tipo_label': dict(TipoAnuncio.choices).get(tipo_anuncio_valor, '—'),

        'badge_logistica': 'full' if tipo_logistico_valor == TipoLogistico.FULL else 'flex',
        'badge_logistica_label': dict(TipoLogistico.choices).get(tipo_logistico_valor, '—'),
    }


def carregar_variacoes_por_sku(skus=None):
    # * [EXPLICAÇÃO] → 1 única query. Agrupa VARIAÇÕES (folhas reais) por SKU
    #                  do produto — nunca deduplica por MLB.
    #                  Se `skus` for None, carrega o banco inteiro (uso em massa).
    #                  Se `skus` for uma lista, filtra só esses (uso paginado).
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
    # * [EXPLICAÇÃO] → Recebe a LISTA de Variações já carregada (folhas reais).
    #                  A classificação (Base/Catálogo/Simples) é do MLB
    #                  (anuncio.tipo_de_anuncio) — todas as variações do
    #                  mesmo MLB herdam a mesma classificação.
    if not variacoes:
        return {'sku': sku, 'encontrado': False, 'paginas_catalogo': [], 'anuncios_simples': [], 'total_anuncios': 0}

    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

    # Agrupa variações por MLB (precisamos disso para achar item_relations do MLB)
    variacoes_por_mlb = defaultdict(list)
    anuncio_por_mlb = {}
    for v in variacoes:
        anuncio_por_mlb[v.anuncio.mlb] = v.anuncio
        variacoes_por_mlb[v.anuncio.mlb].append(v)

    paginas = {}   # catalog_product_id -> lista de MLBs (não variações ainda)
    simples_mlbs = []

    for mlb, anuncio in anuncio_por_mlb.items():
        tipo = anuncio.tipo_de_anuncio
        classificacao = tipo.classificacao_catalogo if tipo else None

        if classificacao == Classificacao.SIMPLES or not anuncio.catalog_product_id:
            simples_mlbs.append(mlb)
            continue

        paginas.setdefault(anuncio.catalog_product_id, []).append(mlb)

    def folhas_do_mlb(mlb):
        # * [EXPLICAÇÃO] → Todo card/folha daquele MLB — 1 por variação.
        return [info_variacao(v) for v in variacoes_por_mlb[mlb]]

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
        'total_anuncios': len(variacoes),  # * total de FOLHAS (variações), não de MLBs
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
    variacoes_por_sku = carregar_variacoes_por_sku(skus=skus)
    return {
        sku: montar_estrutura_de_sku(sku, variacoes)
        for sku, variacoes in variacoes_por_sku.items()
    }