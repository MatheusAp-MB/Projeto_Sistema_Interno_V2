# * [RESUMO] → Enriquece a árvore do Hub (já montada por
#              classificar_lote_de_skus) com o veredito de precificação
#              de cada folha — não recalcula nada, só LÊ o que já foi
#              calculado em lote (calcular_recomendacoes_precificacao.py).
#              Também calcula os 3 contadores do topo da tela, sobre
#              TODO o resultado filtrado, não só a página atual.

from mercado_livre.models import RecomendacaoPrecificacao, VariacaoAnuncioMercadoLivre, PromocaoMercadoLivre
from mercado_livre.funcoes_auxiliares.calculo_margem import buscar_configuracao_tipo_anuncio
from mercado_livre.funcoes_auxiliares.recomendacao_precificacao import montar_motivo


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

    # * [EXPLICAÇÃO] → margem_minima não é persistida em
    #                  RecomendacaoPrecificacao (não varia por
    #                  comportamento) — busca na config real (tabela
    #                  com só 8 linhas), com cache local pra nunca
    #                  repetir a mesma busca 2x na mesma página.
    config_cache = {}
    margem_minima_por_variacao = {}
    for v in VariacaoAnuncioMercadoLivre.objects.filter(
        id__in=ids_variacao
    ).select_related('anuncio__tipo_de_anuncio'):
        tipo_obj = v.anuncio.tipo_de_anuncio if v.anuncio else None
        if not tipo_obj:
            continue
        if tipo_obj.pk not in config_cache:
            config_cache[tipo_obj.pk] = buscar_configuracao_tipo_anuncio(tipo_obj)
        config = config_cache[tipo_obj.pk]
        margem_minima_por_variacao[v.id] = config.margem_padrao if config else None

    for folha in todas_folhas:
        recomendacoes_da_variacao = recomendacoes_por_variacao.get(folha['id'], {})
        comportamento_ativo = folha.get('comportamento_ativo', 'padrao')
        veredito = recomendacoes_da_variacao.get(comportamento_ativo)
        folha['veredito'] = veredito

        # * [EXPLICAÇÃO] → margem_atual (em %) não é persistida em
        #                  lugar nenhum — é sempre derivada aqui:
        #                  margem_recomendada - variacao_margem_pp (o
        #                  mesmo cálculo inverso que a tela individual
        #                  já faz em 'diferenca'). "Sugestão vs Original"
        #                  é só a soma das 2 diferenças já persistidas —
        #                  nenhuma margem nova é calculada, só aritmética
        #                  de exibição sobre o que já está no banco.
        folha['margem_atual_exibicao'] = None
        folha['sugestao_vs_original_pp'] = None
        if veredito and veredito.margem_recomendada is not None and veredito.variacao_margem_pp is not None:
            folha['margem_atual_exibicao'] = veredito.margem_recomendada - veredito.variacao_margem_pp
            if folha.get('margem_atual_vs_original_pp') is not None:
                folha['sugestao_vs_original_pp'] = veredito.variacao_margem_pp + folha['margem_atual_vs_original_pp']

        margem_minima = margem_minima_por_variacao.get(folha['id'])
        folha['motivo'] = montar_motivo(
            veredito.bucket_nome if veredito else None,
            veredito.preco_recomendado if veredito else None,
            veredito.margem_recomendada if veredito else None,
            margem_minima,
        )

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
    página atual) — 1 contador por categoria_estado (os 7 estados),
    contando cada MLB só pelo comportamento que está ATIVO nele (igual
    ao veredito exibido no card, nunca os 3 comportamentos juntos).

    * [EXPLICAÇÃO] → Continua sendo uma aproximação (não repete a
    cascata Base↔Catálogo completa por SKU) — suficiente pra um
    contador de dashboard, igual já era antes."""
    from mercado_livre.funcoes_auxiliares.classificacao_catalogo import carregar_variacoes_por_sku

    variacoes_por_sku = carregar_variacoes_por_sku(skus=skus)
    todas_variacoes = [v for lista in variacoes_por_sku.values() for v in lista]
    ids_variacao = [v.id for v in todas_variacoes]

    categoria_por_variacao_comportamento = {
        (variacao_id, comportamento): categoria
        for variacao_id, comportamento, categoria in RecomendacaoPrecificacao.objects.filter(
            variacao_id__in=ids_variacao
        ).values_list('variacao_id', 'comportamento', 'categoria_estado')
    }

    Categoria = RecomendacaoPrecificacao.CategoriaEstado
    contagem = {chave: 0 for chave, _ in Categoria.choices}

    for v in todas_variacoes:
        categoria = categoria_por_variacao_comportamento.get((v.id, v.comportamento_ativo))
        if categoria:
            contagem[categoria] += 1

    return {
        'sem_oportunidade': contagem[Categoria.SEM_OPORTUNIDADE],
        'candidato': contagem[Categoria.CANDIDATO],
        'sugestao_risco': contagem[Categoria.SUGESTAO_RISCO],
        'oportunidade_troca': contagem[Categoria.OPORTUNIDADE_TROCA],
        'otimizado': contagem[Categoria.OTIMIZADO],
        'operando_em_risco': contagem[Categoria.OPERANDO_EM_RISCO],
        'conflito_multiplas_ativas': contagem[Categoria.CONFLITO_MULTIPLAS_ATIVAS],
    }