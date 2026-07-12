# * [RESUMO] → Monta a lista de linhas candidatas (promoções reais do
#              banco + "Preço Direto"/"Preço Atual") pra 1 variação.
#              Reaproveitado pelo cálculo em lote
#              (calcular_recomendacoes_precificacao.py) E pela tela
#              individual (que exibe a tabela completa) — por isso cada
#              linha carrega TODOS os campos que a tabela usa, não só
#              o mínimo que o cálculo em lote precisaria.

from decimal import Decimal
from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_margem, buscar_configuracao_tipo_anuncio


def montar_linhas_candidatas(variacao):
    """Retorna (linhas, eh_catalogo, margem_minima, margem_atual,
    config_tipo) pra uma variação. linhas é a lista pronta pra passar
    em recomendar_precificacao() OU pra exibir na tabela da tela
    individual. Retorna ([], False, None, None, None) se faltar dado
    essencial (produto ou configuração de tipo)."""
    anuncio = variacao.anuncio
    produto = variacao.produto
    tipo_anuncio_obj = anuncio.tipo_de_anuncio

    if not produto or not tipo_anuncio_obj:
        return [], False, None, None, None

    config_tipo = buscar_configuracao_tipo_anuncio(tipo_anuncio_obj)
    if not config_tipo:
        return [], False, None, None, None

    margem_minima = config_tipo.margem_padrao

    margem_atual = None
    if variacao.preco_atual:
        margem_atual = calcular_margem(produto, variacao.preco_atual, tipo_anuncio_obj)

    eh_catalogo = hasattr(anuncio, 'competicao')
    price_to_win = None
    if eh_catalogo:
        price_to_win = anuncio.competicao.price_to_win

    linhas = []

    if eh_catalogo and price_to_win:
        margem_preco_direto = calcular_margem(produto, price_to_win, tipo_anuncio_obj)
        if margem_preco_direto:
            linhas.append({
                'nome': 'Preço direto para ganhar',
                'tipo': 'PRECO_DIRETO',
                'chave_externa': 'PRECO_DIRETO',
                'status': None,
                'vigencia': None,
                'preco_original': variacao.preco_atual,
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

    if not eh_catalogo and margem_atual:
        linhas.append({
            'nome': 'Preço atual (sem promoção)',
            'tipo': 'PRECO_ATUAL',
            'chave_externa': 'PRECO_ATUAL',
            'status': None,
            'vigencia': None,
            'preco_original': variacao.preco_atual,
            'preco_promocional': variacao.preco_atual,
            'tem_rebate': False,
            'meli_percentage': None,
            'seller_percentage': None,
            'rebate_valor_reais': Decimal('0'),
            'margem_com_rebate': margem_atual,
            'margem_sem_rebate': margem_atual,
            'margem_real': margem_atual,
            'diferenca': Decimal('0'),
            'ganha_catalogo': None,
        })

    for promo in variacao.promocoes.all():
        preco_avaliado = promo.preco_avaliado
        if not preco_avaliado:
            continue

        tem_rebate = promo.meli_percentage is not None
        margem_com_rebate = calcular_margem(
            produto, preco_avaliado, tipo_anuncio_obj,
            rebate_percentual=promo.meli_percentage if tem_rebate else None,
            preco_original=promo.preco_original if tem_rebate else None,
        )
        if not margem_com_rebate:
            continue

        margem_sem_rebate = calcular_margem(produto, preco_avaliado, tipo_anuncio_obj)

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

    return linhas, eh_catalogo, margem_minima, margem_atual, config_tipo