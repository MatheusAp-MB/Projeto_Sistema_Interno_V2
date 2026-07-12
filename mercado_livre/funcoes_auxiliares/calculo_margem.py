# * [RESUMO] → Cálculo de margem "pra frente" (dado um preço, retorna a
#              margem) — direção contrária ao Goal Seek do PDF (que
#              parte de uma meta de margem e acha o preço). Aqui o
#              preço já é conhecido, então o frete é uma consulta
#              direta na FreteML, sem busca por faixa/circularidade.
#
#              Fórmula (mesma derivação do Goal Seek Analítico):
#                  taxa  = comissão% + icms_saída% + pis%
#                  FIXO  = coleta + armazenagem + custo_final
#                          - custo×(icms_entrada% + pis%)
#                  margem_valor = preço×(1-taxa) - FIXO - frete + rebate
#                  margem%      = margem_valor ÷ preço × 100
#
#              Rebate: o ML abate parte da comissão que cobraria —
#              rebate_valor = preço_original × (meli_percentage/100).
#              Isso soma direto na margem (é dinheiro que deixa de sair
#              do seu bolso em comissão).
#
#              TESTE — 2 constantes ainda não modeladas em tabela:
#              coleta (R$/m³) e armazenagem (R$/dia) são fixas por
#              enquanto, confirmadas com o usuário. Formalizar como
#              model/tabela de faixas é pendência futura, se isso virar
#              produção.

from decimal import Decimal
from django.db.models import Q

TAXA_COLETA_POR_METRO_CUBICO = Decimal('72')

# * [EXPLICAÇÃO] → Fallback só usado se o produto não tiver
#                  armazenagem_planilha (ainda não passou pela
#                  importação da planilha validada). Nesse caso o
#                  resultado é uma aproximação, não o número oficial.
VALOR_ARMAZENAGEM_DIARIA_FALLBACK = Decimal('0.015')
DIAS_ARMAZENAGEM = 30

COMISSAO_POR_TIPO = {
    'classico': Decimal('0.12'),
    'premium': Decimal('0.17'),
}

# * [EXPLICAÇÃO] → Margem mínima aceitável antes de considerar uma
#                  opção "segura". Fixa por enquanto — vira configurável
#                  (por produto/categoria) no futuro.
MARGEM_MINIMA_PADRAO = Decimal('15')


def calcular_metro_cubico(produto):
    return (produto.altura / 100) * (produto.largura / 100) * (produto.profundidade / 100)


def calcular_fixo(produto):
    custo_com_boni = produto.custo_com_boni or produto.custo
    ipi = (produto.ipi or Decimal('0')) / 100
    frete_cif_fob = (produto.frete_cif_fob or Decimal('0')) / 100
    st_valor = produto.st_valor or Decimal('0')
    icms_entrada = (produto.icms_entrada or Decimal('0')) / 100
    pis = (produto.pis_cofins or Decimal('0')) / 100

    custo_final = (
        custo_com_boni
        + (custo_com_boni * ipi)
        + (custo_com_boni * frete_cif_fob)
        + st_valor
    )
    coleta = calcular_metro_cubico(produto) * TAXA_COLETA_POR_METRO_CUBICO

    # * [EXPLICAÇÃO] → armazenagem_planilha já é o valor MENSAL real
    #                  (vem pronto da coluna BH), não precisa multiplicar
    #                  por dias. Só cai no fallback fixo se o produto
    #                  ainda não tiver passado pela planilha validada.
    if produto.armazenagem_planilha is not None:
        armazenagem = produto.armazenagem_planilha
    else:
        armazenagem = VALOR_ARMAZENAGEM_DIARIA_FALLBACK * DIAS_ARMAZENAGEM

    return coleta + armazenagem + custo_final - (produto.custo * (icms_entrada + pis))


def buscar_frete(produto, preco):
    from mercado_livre.models import FreteML

    # * [EXPLICAÇÃO] → peso_cubado pode vir vazio (nem todo produto tem
    #                  dado do relatório completo do ERP ainda) — trata
    #                  como 0 nesse caso, em vez de quebrar o max().
    peso_cubado = produto.peso_cubado or Decimal('0')
    peso_normal = produto.peso or Decimal('0')
    peso = max(peso_normal, peso_cubado)

    frete = FreteML.objects.filter(
        peso_min__lte=peso,
        preco_min__lte=preco,
    ).filter(
        Q(peso_max__gte=peso) | Q(peso_max__isnull=True)
    ).filter(
        Q(preco_max__gte=preco) | Q(preco_max__isnull=True)
    ).first()

    return frete.valor if frete else None


def calcular_margem(produto, preco, tipo_anuncio='classico', rebate_percentual=None, preco_original=None):
    """Dado um preço de venda, calcula a margem resultante. Se
    rebate_percentual + preco_original forem informados, soma o abatimento
    do ML na comissão. Retorna None se não achar faixa de frete pro
    preço/peso (situação rara, mas possível fora do range da tabela)."""
    preco = Decimal(str(preco))
    if preco <= 0:
        return None

    comissao = COMISSAO_POR_TIPO.get(tipo_anuncio, COMISSAO_POR_TIPO['classico'])
    icms_saida = (produto.icms_saida_media or Decimal('0')) / 100
    pis = (produto.pis_cofins or Decimal('0')) / 100
    taxa = comissao + icms_saida + pis

    fixo = calcular_fixo(produto)
    frete = buscar_frete(produto, preco)
    if frete is None:
        return None

    rebate_valor = Decimal('0')
    if rebate_percentual is not None and preco_original:
        rebate_valor = Decimal(str(preco_original)) * (Decimal(str(rebate_percentual)) / 100)

    margem_valor = preco * (1 - taxa) - fixo - frete + rebate_valor
    margem_percentual = (margem_valor / preco) * 100

    return {
        'preco': preco,
        'frete': frete,
        'fixo': fixo,
        'rebate_valor': rebate_valor,
        'margem_valor': margem_valor,
        'margem_percentual': margem_percentual,
    }