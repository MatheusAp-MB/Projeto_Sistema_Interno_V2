# * [RESUMO] → Monta a lista de linhas candidatas (promoções reais do
#              banco + "Preço Direto"/"Preço Atual") pra 1 variação.
#              Reaproveitado pelo cálculo em lote
#              (calcular_recomendacoes_precificacao.py) E pela tela
#              individual (que exibe a tabela completa) — por isso cada
#              linha carrega TODOS os campos que a tabela usa, não só
#              o mínimo que o cálculo em lote precisaria.
#
#              Auditoria de otimização (15/07): config_tipo (já
#              calculado 1 vez no início desta função) agora é
#              REPASSADO explicitamente pra TODAS as chamadas de
#              calcular_margem — antes, cada chamada passava
#              tipo_anuncio_obj e deixava calcular_margem buscar
#              config_tipo de novo, sozinha, internamente. Só foi
#              descoberto porque a medição de consultas (antes capada
#              em 9.000 pelo Django) foi corrigida — revelou 67.363
#              consultas reais numa única rodada, a maioria vindo
#              exatamente daqui.

from decimal import Decimal
from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_margem, calcular_fixo, buscar_configuracao_tipo_anuncio


def montar_linhas_candidatas(variacao, frete_todas=None, config_geral=None, faixas_armazenagem=None, configs_por_tipo=None):
    """Retorna (linhas, eh_catalogo, margem_minima, margem_atual,
    config_tipo, margem_original) pra uma variação. linhas é a lista
    pronta pra passar em recomendar_precificacao() OU pra exibir na
    tabela da tela individual. Retorna ([], False, None, None, None,
    None) se faltar dado essencial (produto ou configuração de tipo).

    frete_todas: opcional — TODA a tabela FreteML já carregada em
    memória (pelo comando em lote, 1 vez só, fora do loop de
    variações). Quando passado, FIXO e as faixas de frete são
    calculados 1 VEZ aqui e reaproveitados em TODAS as chamadas de
    calcular_margem desta função (preço atual, preço original, preço
    direto, e cada promoção) — elimina dezenas de queries repetidas
    por variação. Sem esse parâmetro (ex: tela individual, só 1 MLB),
    cada calcular_margem busca frete no banco por conta própria —
    comportamento antigo, preservado.

    config_geral, faixas_armazenagem: opcionais — repassados direto
    pra calcular_fixo (mesmo padrão da Grade). Sem eles,
    ConfiguracaoMercadoLivre.obter() bate no banco 1 vez POR VARIAÇÃO.

    configs_por_tipo: opcional — dict {tipo_anuncio: config} já
    carregado (só 2 linhas no total, Clássico/Premium). Achado real
    (só visível depois de corrigir a medição de consultas, antes
    capada em 9.000 pelo Django): sem esse parâmetro,
    buscar_configuracao_tipo_anuncio bate no banco 1 vez POR VARIAÇÃO
    (~5.672 consultas evitáveis, confirmado).

    * [EXPLICAÇÃO] → 3 escopos de margem, cada um com seu próprio
    preço e seu próprio rebate — NUNCA misturados entre si:
      - ATUAL: variacao.preco_atual + rebate da promoção REALMENTE
        ativa agora (só quando existe exatamente 1 'started' — com 0
        ou 2+, sem rebate, pra não supor qual contar; o caso de
        2+ já é sinalizado à parte como conflito).
      - ORIGINAL: preco_original (ou preco_atual quando não há
        nenhuma promoção ativa hoje — nesse caso os dois são o
        mesmo preço) — NUNCA tem rebate, por definição.
      - SUGERIDO: cada linha candidata (cada promoção avaliada) já
        calcula o rebate DELA MESMA, isolado — isso não muda aqui.
    Bug corrigido: antes, margem_atual nunca incluía rebate nenhum, e
    a linha "sem promoção" reaproveitava essa margem_atual sem rebate
    como se fosse a margem "de hoje" também — os dois escopos
    ficavam contaminados um pelo outro."""
    anuncio = variacao.anuncio
    produto = variacao.produto
    tipo_anuncio_obj = anuncio.tipo_de_anuncio

    if not produto or not tipo_anuncio_obj:
        return [], False, None, None, None, None

    if configs_por_tipo is not None:
        config_tipo = configs_por_tipo.get(tipo_anuncio_obj.tipo_anuncio)
    else:
        config_tipo = buscar_configuracao_tipo_anuncio(tipo_anuncio_obj)
    if not config_tipo:
        return [], False, None, None, None, None

    margem_minima = config_tipo.margem_padrao

    # * [EXPLICAÇÃO] → FIXO não depende de tipo de anúncio nem de
    #                  preço — calculado 1 vez aqui, reaproveitado em
    #                  todas as chamadas de calcular_margem abaixo
    #                  (nunca recalculado por linha candidata).
    fixo = calcular_fixo(produto, config_geral=config_geral, faixas_armazenagem=faixas_armazenagem)

    faixas_produto = None
    if frete_todas is not None:
        # * [EXPLICAÇÃO] → Peso da EMBALAGEM (confirmado com o usuário
        #                  — mesma regra usada em buscar_frete e
        #                  preparar_fixo_e_faixas) — nunca do produto
        #                  sem embalar.
        peso_cubado = produto.peso_cubado or Decimal('0')
        peso_embalagem = produto.peso_produto_apos_embalado or Decimal('0')
        peso = max(peso_embalagem, peso_cubado)
        faixas_produto = sorted(
            (f for f in frete_todas if f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)),
            key=lambda f: f.preco_min,
        )

    # * [EXPLICAÇÃO] → Só 1 promoção ativa dá um rebate inequívoco pra
    #                  somar na margem ATUAL. Com 0, não tem rebate
    #                  mesmo. Com 2+ (conflito), não dá pra saber qual
    #                  rebate é o "de verdade" sem ambiguidade — fica
    #                  sem rebate aqui, mas o estado de conflito já
    #                  avisa isso separadamente, então não é dado
    #                  escondido, é uma limitação conhecida e visível.
    ativas = [p for p in variacao.promocoes.all() if p.status == 'started']
    ativa_unica = ativas[0] if len(ativas) == 1 else None

    margem_atual = None
    if variacao.preco_atual:
        rebate_pct = ativa_unica.meli_percentage if (ativa_unica and ativa_unica.meli_percentage is not None) else None
        rebate_preco_original = ativa_unica.preco_original if (ativa_unica and ativa_unica.meli_percentage is not None) else None
        margem_atual = calcular_margem(
            produto, variacao.preco_atual,
            rebate_percentual=rebate_pct, preco_original=rebate_preco_original,
            config_tipo=config_tipo, fixo=fixo, faixas_frete=faixas_produto,
        )

    # * [EXPLICAÇÃO] → Preço ORIGINAL: se existe preco_original (há
    #                  promoção ativa que também baixa preço), usa
    #                  ele. Se não existe (preço não mudou, ou não há
    #                  promoção), preco_original == preco_atual — o
    #                  preço de hoje JÁ É o original. NUNCA tem rebate.
    preco_sem_promocao = variacao.preco_original or variacao.preco_atual
    margem_original = None
    if preco_sem_promocao:
        margem_original = calcular_margem(
            produto, preco_sem_promocao,
            config_tipo=config_tipo, fixo=fixo, faixas_frete=faixas_produto,
        )

    eh_catalogo = hasattr(anuncio, 'competicao')
    price_to_win = None
    if eh_catalogo:
        price_to_win = anuncio.competicao.price_to_win

    linhas = []

    if eh_catalogo and price_to_win:
        margem_preco_direto = calcular_margem(
            produto, price_to_win,
            config_tipo=config_tipo, fixo=fixo, faixas_frete=faixas_produto,
        )
        if margem_preco_direto:
            linhas.append({
                'nome': 'Preço direto para ganhar',
                'tipo': 'PRECO_DIRETO',
                'chave_externa': 'PRECO_DIRETO',
                'status': None,
                'vigencia': None,
                'preco_original': preco_sem_promocao,
                'preco_promocional': price_to_win,
                'tem_rebate': False,
                'meli_percentage': None,
                'seller_percentage': None,
                'rebate_valor_reais': Decimal('0'),
                'margem_com_rebate': margem_preco_direto,
                'margem_sem_rebate': margem_preco_direto,
                'margem_real': margem_preco_direto,
                'diferenca': round(margem_preco_direto['margem_percentual'] - margem_atual['margem_percentual'], 2) if margem_atual else None,
                'ganha_catalogo': True,
            })

    if not eh_catalogo and margem_original:
        linhas.append({
            'nome': 'Preço original (sem promoção)',
            'tipo': 'PRECO_ATUAL',
            'chave_externa': 'PRECO_ATUAL',
            'status': None,
            'vigencia': None,
            'preco_original': preco_sem_promocao,
            'preco_promocional': preco_sem_promocao,
            'tem_rebate': False,
            'meli_percentage': None,
            'seller_percentage': None,
            'rebate_valor_reais': Decimal('0'),
            'margem_com_rebate': margem_original,
            'margem_sem_rebate': margem_original,
            'margem_real': margem_original,
            'diferenca': round(margem_original['margem_percentual'] - margem_atual['margem_percentual'], 2) if margem_atual else None,
            'ganha_catalogo': None,
        })

    for promo in variacao.promocoes.all():
        preco_avaliado = promo.preco_avaliado
        if not preco_avaliado:
            continue

        tem_rebate = promo.meli_percentage is not None
        margem_com_rebate = calcular_margem(
            produto, preco_avaliado,
            rebate_percentual=promo.meli_percentage if tem_rebate else None,
            preco_original=promo.preco_original if tem_rebate else None,
            config_tipo=config_tipo, fixo=fixo, faixas_frete=faixas_produto,
        )
        if not margem_com_rebate:
            continue

        margem_sem_rebate = calcular_margem(
            produto, preco_avaliado,
            config_tipo=config_tipo, fixo=fixo, faixas_frete=faixas_produto,
        )

        diferenca = round(margem_com_rebate['margem_percentual'] - margem_atual['margem_percentual'], 2) if margem_atual else None

        ganha_catalogo = None
        if eh_catalogo and price_to_win:
            ganha_catalogo = preco_avaliado <= price_to_win

        vigencia = None
        if promo.inicio_vigencia:
            vigencia = {
                'inicio': promo.inicio_vigencia.strftime('%Y-%m-%d'),
                'fim': promo.fim_vigencia.strftime('%Y-%m-%d') if promo.fim_vigencia else '?',
            }

        linhas.append({
            'nome': promo.nome or promo.tipo,
            'tipo': promo.tipo,
            'chave_externa': promo.chave_externa,
            'status': promo.status,
            'vigencia': vigencia,
            'preco_original': promo.preco_original,
            'preco_promocional': preco_avaliado,
            'tem_rebate': tem_rebate,
            'meli_percentage': promo.meli_percentage,
            'seller_percentage': promo.seller_percentage,
            'rebate_valor_reais': margem_com_rebate['rebate_valor'],
            'margem_com_rebate': margem_com_rebate,
            'margem_sem_rebate': margem_sem_rebate,
            'margem_real': margem_com_rebate,
            'diferenca': diferenca,
            'ganha_catalogo': ganha_catalogo,
        })

    return linhas, eh_catalogo, margem_minima, margem_atual, config_tipo, margem_original