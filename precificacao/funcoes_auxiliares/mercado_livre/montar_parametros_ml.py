# * [RESUMO] → Ponte entre o motor genérico (goal_seek.py) e o mundo
#              real do Mercado Livre. Monta fixo, taxa e as faixas de
#              frete candidatas a partir de Produto +
#              ConfiguracaoTipoAnuncioMercadoLivre — reaproveitando
#              calcular_fixo (já validado, mesmo usado no cálculo "pra
#              frente"), sem duplicar essa lógica.

from decimal import Decimal
from django.db.models import Q


def preparar_fixo_e_faixas(produto, frete_todas):
    """FIXO e as faixas de frete candidatas NÃO dependem de tipo de
    anúncio nem de margem-alvo — só do produto. Calcule 1 VEZ por
    produto e reaproveite nas 8 combinações (margem × Clássico/
    Premium) — nunca recalcular por combinação.

    frete_todas: TODA a tabela FreteML, já carregada em memória 1 vez
    (fora do loop de produtos, por quem chama) — filtra por peso aqui
    em Python, sem nenhuma query nova por produto.

    Retorna (fixo, faixas, peso) — peso devolvido pra quem chama poder
    guardar no detalhamento sem recalcular a mesma conta de novo."""
    from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_fixo

    fixo = calcular_fixo(produto)

    peso_cubado = produto.peso_cubado or Decimal('0')
    peso_normal = produto.peso or Decimal('0')
    peso = max(peso_normal, peso_cubado)

    faixas = sorted(
        (f for f in frete_todas if f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)),
        key=lambda f: f.preco_min,
    )
    return fixo, faixas, peso


def calcular_preco_grade_ml(produto, config_tipo, margem_alvo_percentual, fixo, faixas_frete, peso):
    """Retorna o dict de resolver_preco_por_margem() (preco_calculado,
    frete_usado, margem_percentual_obtida, faixa_frete, detalhamento)
    pra essa combinação de Produto + configuração + margem-alvo.
    Retorna None se a meta for inatingível, ou se nenhuma faixa de
    frete servir.

    config_tipo: instância de ConfiguracaoTipoAnuncioMercadoLivre JÁ
    ESCOLHIDA (a Grade sabe exatamente qual das 8 combinações quer —
    não precisa buscar via um anúncio real, diferente do cálculo "pra
    frente", que parte de 1 MLB específico).

    fixo, faixas_frete, peso: JÁ CALCULADOS por preparar_fixo_e_faixas()
    — não recalcula aqui, evita repetir a mesma conta/query por
    produto.

    margem_alvo_percentual: número em PERCENTUAL (ex: 15, não 0.15) —
    mesma convenção usada em ConfiguracaoTipoAnuncioMercadoLivre."""
    from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_margem

    if not faixas_frete:
        return None

    comissao = config_tipo.comissao / 100
    icms_saida = (produto.icms_saida_media or Decimal('0')) / 100
    pis = (produto.pis_cofins or Decimal('0')) / 100
    taxa_percentual = comissao + icms_saida + pis

    custo_produto = produto.custo_com_boni or produto.custo
    margem_alvo_fracao = Decimal(str(margem_alvo_percentual)) / 100

    resultado = resolver_preco_por_margem(
        fixo=fixo,
        taxa_percentual=taxa_percentual,
        margem_alvo_fracao=margem_alvo_fracao,
        custo_produto=custo_produto,
        faixas_frete_candidatas=faixas_frete,
    )

    # * [EXPLICAÇÃO] → Complementa o detalhamento com o que só ESSA
    #                  camada sabe (comissão/ICMS/PIS separados, peso,
    #                  qual tipo de anúncio) — o motor genérico só
    #                  devolveu a taxa já somada.
    if resultado is not None:
        resultado['detalhamento'].update({
            'tipo_anuncio': config_tipo.get_tipo_anuncio_display(),
            'peso_usado': peso,
            'comissao_percentual': config_tipo.comissao,
            'icms_saida_percentual': produto.icms_saida_media or Decimal('0'),
            'pis_cofins_percentual': produto.pis_cofins or Decimal('0'),
        })

    return resultado