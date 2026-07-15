# * [RESUMO] → Ponte entre o motor genérico (goal_seek.py) e o mundo
#              real do Mercado Livre. Monta fixo, taxa e as faixas de
#              frete candidatas a partir de Produto +
#              ConfiguracaoTipoAnuncioMercadoLivre — reaproveitando
#              calcular_fixo (já validado, mesmo usado no cálculo "pra
#              frente"), sem duplicar essa lógica.

from decimal import Decimal
from django.db.models import Q


def preparar_fixo_e_faixas(produto, frete_todas, config_geral=None, faixas_armazenagem=None):
    """FIXO e as faixas de frete candidatas NÃO dependem de tipo de
    anúncio nem de margem-alvo — só do produto. Calcule 1 VEZ por
    produto e reaproveite nas 8 combinações (margem × Clássico/
    Premium) — nunca recalcular por combinação.

    frete_todas: TODA a tabela FreteML, já carregada em memória 1 vez
    (fora do loop de produtos, por quem chama) — filtra por peso aqui
    em Python, sem nenhuma query nova por produto.

    config_geral, faixas_armazenagem: opcionais — repassados direto
    pra calcular_fixo, mesma lógica (evita 1 query nova por produto).

    Retorna (fixo, faixas, peso) — peso devolvido pra quem chama poder
    guardar no detalhamento sem recalcular a mesma conta de novo."""
    from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_fixo

    fixo = calcular_fixo(produto, config_geral=config_geral, faixas_armazenagem=faixas_armazenagem)

    peso_cubado = produto.peso_cubado or Decimal('0')
    peso_normal = produto.peso or Decimal('0')
    peso = max(peso_normal, peso_cubado)

    faixas = sorted(
        (f for f in frete_todas if f.peso_min <= peso and (f.peso_max is None or f.peso_max >= peso)),
        key=lambda f: f.preco_min,
    )
    return fixo, faixas, peso


def _montar_taxa_e_custo(produto, config_tipo):
    """Peça comum reaproveitada pelos 2 caminhos (frete de tabela e
    frete real) — evita duplicar a mesma conta 2 vezes."""
    comissao = config_tipo.comissao / 100
    icms_saida = (produto.icms_saida_media or Decimal('0')) / 100
    pis = (produto.pis_cofins or Decimal('0')) / 100
    taxa_percentual = comissao + icms_saida + pis
    custo_produto = produto.custo_com_boni or produto.custo
    return taxa_percentual, custo_produto


def _enriquecer_detalhamento(resultado, produto, config_tipo, peso, frete_origem):
    """Complementa o detalhamento com o que só ESSA camada sabe
    (comissão/ICMS/PIS separados, peso, tipo de anúncio, origem do
    frete) — o motor genérico (goal_seek.py) só devolve a taxa já
    somada, sem saber o que é 'comissão' ou 'ICMS' separadamente."""
    if resultado is None:
        return resultado
    resultado['detalhamento'].update({
        'tipo_anuncio': config_tipo.get_tipo_anuncio_display(),
        'peso_usado': peso,
        'comissao_percentual': config_tipo.comissao,
        'icms_saida_percentual': produto.icms_saida_media or Decimal('0'),
        'pis_cofins_percentual': produto.pis_cofins or Decimal('0'),
        'frete_origem': frete_origem,
    })
    return resultado


def calcular_preco_grade_ml(produto, config_tipo, margem_alvo_percentual, fixo, faixas_frete, peso):
    """FRETE DE TABELA — busca de faixa (Goal Seek completo, com a
    circularidade preço↔faixa). Retorna None se a meta for
    inatingível, ou se nenhuma faixa de frete servir.

    config_tipo: instância de ConfiguracaoTipoAnuncioMercadoLivre JÁ
    ESCOLHIDA (não precisa buscar via um anúncio real).

    fixo, faixas_frete, peso: JÁ CALCULADOS por preparar_fixo_e_faixas()
    — não recalcula aqui, evita repetir a mesma conta/query por
    produto.

    margem_alvo_percentual: número em PERCENTUAL (ex: 15, não 0.15)."""
    from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_por_margem

    if not faixas_frete:
        return None

    taxa_percentual, custo_produto = _montar_taxa_e_custo(produto, config_tipo)
    margem_alvo_fracao = Decimal(str(margem_alvo_percentual)) / 100

    resultado = resolver_preco_por_margem(
        fixo=fixo,
        taxa_percentual=taxa_percentual,
        margem_alvo_fracao=margem_alvo_fracao,
        custo_produto=custo_produto,
        faixas_frete_candidatas=faixas_frete,
    )
    return _enriquecer_detalhamento(resultado, produto, config_tipo, peso, frete_origem='tabela')


def calcular_preco_com_frete_real(produto, config_tipo, margem_alvo_percentual, fixo, peso, frete_real):
    """FRETE REAL — vindo de medição física do Mercado Livre (API).
    Sem busca de faixa (o motor genérico já resolve direto, já que
    não há circularidade preço↔faixa aqui — o frete já é um número
    fechado). Retorna None se a meta for inatingível.

    fixo, peso: JÁ CALCULADOS por preparar_fixo_e_faixas() — mesmo
    padrão dos outros caminhos, não recalcula por combinação.

    margem_alvo_percentual: número em PERCENTUAL (ex: 15, não 0.15)."""
    from precificacao.funcoes_auxiliares.goal_seek import resolver_preco_com_frete_fixo

    taxa_percentual, custo_produto = _montar_taxa_e_custo(produto, config_tipo)
    margem_alvo_fracao = Decimal(str(margem_alvo_percentual)) / 100

    resultado = resolver_preco_com_frete_fixo(
        fixo=fixo,
        taxa_percentual=taxa_percentual,
        margem_alvo_fracao=margem_alvo_fracao,
        frete=frete_real,
    )
    if resultado is not None:
        resultado['detalhamento']['custo_produto'] = custo_produto
    return _enriquecer_detalhamento(resultado, produto, config_tipo, peso, frete_origem='real')