# * [RESUMO] → Enriquece a árvore do Hub (já montada por
#              classificar_lote_de_skus) com o veredito de precificação
#              de cada folha — não recalcula nada, só LÊ o que já foi
#              calculado em lote (calcular_recomendacoes_precificacao.py).
#              Também calcula os 3 contadores do topo da tela, sobre
#              TODO o resultado filtrado, não só a página atual.

from mercado_livre.models import RecomendacaoPrecificacao, VariacaoAnuncioMercadoLivre, PromocaoMercadoLivre


def _coletar_folhas(arvore):
    """Percorre a árvore de 1 SKU e devolve todas as folhas (dicts de
    info_variacao) numa lista só, não importa em que nível estejam."""
    folhas = []
    if not arvore.get('encontrado'):
        return folhas

    for pagina in arvore.get('paginas_catalogo', []):
        for base in pagina.get('anuncios_base', []):
            folhas.extend(base['folhas'])
            for catalogo in base.get('anuncios_catalogo', []):
                folhas.extend(catalogo['folhas'])
        for orfao in pagina.get('anuncios_catalogo_orfaos', []):
            folhas.extend(orfao['folhas'])

    for simples in arvore.get('anuncios_simples', []):
        folhas.extend(simples['folhas'])

    return folhas


def enriquecer_arvores_com_veredito(arvores):
    """Mutação in-place: adiciona 'veredito' em cada folha da árvore
    (só das folhas da PÁGINA atual, já que 'arvores' só cobre isso)."""
    todas_folhas = []
    for arvore in arvores.values():
        todas_folhas.extend(_coletar_folhas(arvore))

    ids_variacao = [f['id'] for f in todas_folhas]

    recomendacoes_por_variacao = {}
    for r in RecomendacaoPrecificacao.objects.filter(variacao_id__in=ids_variacao):
        recomendacoes_por_variacao.setdefault(r.variacao_id, {})[r.comportamento] = r

    # * [EXPLICAÇÃO] → Só anexa 'promocao_ativa' quando existe EXATAMENTE
    #                  1 promoção 'started' pra variação — é o caso normal
    #                  (estado atual bem definido). Quando há 0 ou 2+,
    #                  fica None; o card decide o que mostrar olhando
    #                  pra 'categoria_estado' (que já cobre esses casos).
    promocoes_ativas_por_variacao = {}
    for p in PromocaoMercadoLivre.objects.filter(variacao_id__in=ids_variacao, status='started'):
        promocoes_ativas_por_variacao.setdefault(p.variacao_id, []).append(p)

    for folha in todas_folhas:
        recomendacoes_da_variacao = recomendacoes_por_variacao.get(folha['id'], {})
        comportamento_ativo = folha.get('comportamento_ativo', 'padrao')
        folha['veredito'] = recomendacoes_da_variacao.get(comportamento_ativo)

        ativas = promocoes_ativas_por_variacao.get(folha['id'], [])
        if len(ativas) == 1:
            ativa = ativas[0]
            folha['promocao_ativa'] = {
                'nome': ativa.nome or ativa.tipo,
                'preco_avaliado': ativa.preco_avaliado,
                'meli_percentage': ativa.meli_percentage,
                'chave_externa': ativa.chave_externa,
            }
        else:
            folha['promocao_ativa'] = None


def calcular_contadores_promocao(skus):
    """Contadores agregados sobre TODO o resultado filtrado (não só a
    página atual).

    * [EXPLICAÇÃO] → É uma aproximação por query direta — não repete a
    cascata Base↔Catálogo completa (que só roda por SKU individual).
    Conta variações que batem os critérios dentro dos SKUs filtrados,
    não necessariamente idêntico folha-a-folha ao que aparece renderizado
    na árvore. Suficiente pra um contador de dashboard; exatidão perfeita
    exigiria rodar a cascata pra cada SKU, igual já fazemos pra
    'total_anuncios' no Hub de Anúncios — fica como refinamento futuro
    se a diferença incomodar na prática."""
    from mercado_livre.funcoes_auxiliares.classificacao_catalogo import carregar_variacoes_por_sku

    variacoes_por_sku = carregar_variacoes_por_sku(skus=skus)
    todas_variacoes = [v for lista in variacoes_por_sku.values() for v in lista]
    ids_variacao = [v.id for v in todas_variacoes]

    com_ativa = VariacaoAnuncioMercadoLivre.objects.filter(
        id__in=ids_variacao, promocoes__status='started'
    ).distinct().count()

    candidatos = VariacaoAnuncioMercadoLivre.objects.filter(
        id__in=ids_variacao, promocoes__status='candidate'
    ).distinct().count()

    recomendacoes_validas = set(
        RecomendacaoPrecificacao.objects.filter(
            variacao_id__in=ids_variacao, tem_escolha=True
        ).values_list('variacao_id', 'comportamento')
    )

    com_recomendacao = sum(
        1 for v in todas_variacoes
        if (v.id, v.comportamento_ativo) in recomendacoes_validas
    )

    return {
        'com_promocao_ativa': com_ativa,
        'candidatos': candidatos,
        'com_recomendacao': com_recomendacao,
    }