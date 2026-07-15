# * [RESUMO] → Cálculo de margem "pra frente" (dado um preço, retorna a
#              margem) — direção contrária ao Goal Seek do PDF (que
#              parte de uma meta de margem e acha o preço). Aqui o
#              preço já é conhecido, então o frete é uma consulta
#              direta na FreteML, sem busca por faixa/circularidade.
#
#              Comissão, acréscimo Premium e as 4 margens (mínima/
#              padrão/máxima/competição) vêm de
#              ConfiguracaoTipoAnuncioMercadoLivre, por combinação real
#              do anúncio (tipo_anuncio × tipo_logistico × catálogo) —
#              não mais fixas em código.
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

from decimal import Decimal
from django.db.models import Q


def calcular_metro_cubico(produto):
    return (produto.altura / 100) * (produto.largura / 100) * (produto.profundidade / 100)


def selecionar_faixa_armazenagem(produto):
    """Acha a primeira faixa (em ordem crescente) onde TODAS as
    dimensões do produto cabem; se nenhuma comportar, usa a maior
    (fallback). Só usada quando o produto ainda não tem
    armazenagem_planilha (sem histórico na planilha validada)."""
    from mercado_livre.models import FaixaArmazenagemMercadoLivre

    faixas = list(FaixaArmazenagemMercadoLivre.objects.filter(ativo=True).order_by('ordem'))
    if not faixas:
        return None

    for faixa in faixas:
        if (produto.altura <= faixa.max_altura
                and produto.largura <= faixa.max_largura
                and produto.profundidade <= faixa.max_profundidade):
            return faixa

    return faixas[-1]


def buscar_configuracao_tipo_anuncio(tipo_anuncio_obj):
    """Busca a configuração (comissão, margens) só pelo tipo de anúncio
    (Clássico/Premium) — simplificado em 27/07: logística e catálogo
    não afetam mais comissão/margem (confirmado com o usuário/superior),
    só essa distinção importa pra precificação agora."""
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre

    return ConfiguracaoTipoAnuncioMercadoLivre.objects.filter(
        tipo_anuncio=tipo_anuncio_obj.tipo_anuncio,
    ).first()


def calcular_fixo(produto):
    from mercado_livre.models import ConfiguracaoMercadoLivre

    config = ConfiguracaoMercadoLivre.obter()

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
    coleta = calcular_metro_cubico(produto) * config.fator_coleta

    # * [EXPLICAÇÃO] → armazenagem_planilha já é o valor MENSAL real
    #                  (vem pronto da planilha validada) — só cai na
    #                  faixa dinâmica (por dimensão) se o produto ainda
    #                  não tiver passado por essa importação. Esse é o
    #                  caminho que vai permitir abandonar a planilha no
    #                  futuro (objetivo de longo prazo confirmado com o
    #                  usuário).
    if produto.armazenagem_planilha is not None:
        armazenagem = produto.armazenagem_planilha
    else:
        faixa = selecionar_faixa_armazenagem(produto)
        armazenagem = (faixa.valor_diario * config.periodo_armazenagem) if faixa else Decimal('0')

    return coleta + armazenagem + custo_final - (produto.custo * (icms_entrada + pis))


def buscar_frete(produto, preco, faixas_candidatas=None):
    """Se faixas_candidatas for passado (já filtradas por peso, em
    memória — sem query nova), busca o frete em Python. Sem isso,
    cai no comportamento original (1 query por chamada) — mantém
    compatibilidade com quem já chama sem esse parâmetro."""
    if faixas_candidatas is not None:
        for faixa in faixas_candidatas:
            if faixa.preco_min <= preco and (faixa.preco_max is None or faixa.preco_max >= preco):
                return faixa.valor
        return None

    from mercado_livre.models import FreteML

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

def calcular_margem(produto, preco, tipo_anuncio_obj=None, rebate_percentual=None, preco_original=None, config_tipo=None, fixo=None, faixas_frete=None):
    """Dado um preço de venda, calcula a margem resultante.
    tipo_anuncio_obj é o TipoDeAnuncioMercadoLivre REAL do anúncio (não
    mais uma string 'classico'/'premium') — decide a comissão certa pela
    combinação completa (tipo × logística × catálogo). Retorna None se
    não achar faixa de frete, ou se não existir configuração pra essa
    combinação (não deveria acontecer, as 8 já estão seedadas).

    * [EXPLICAÇÃO] → config_tipo: passe a ConfiguracaoTipoAnuncioMercadoLivre
    já pronta quando não existir um anúncio real por trás (ex: Grade de
    Precificação, que calcula direto por combinação, sem MLB nenhum) —
    pula a busca via tipo_anuncio_obj. Se os dois vierem None, retorna
    None (precisa de pelo menos 1 dos 2)."""
    preco = Decimal(str(preco))
    if preco <= 0:
        return None

    if config_tipo is None:
        if tipo_anuncio_obj is None:
            return None
        config_tipo = buscar_configuracao_tipo_anuncio(tipo_anuncio_obj)
    if not config_tipo:
        return None

    comissao = config_tipo.comissao / 100
    icms_saida = (produto.icms_saida_media or Decimal('0')) / 100
    pis = (produto.pis_cofins or Decimal('0')) / 100
    taxa = comissao + icms_saida + pis

    if fixo is None:
        fixo = calcular_fixo(produto)
    frete = buscar_frete(produto, preco, faixas_candidatas=faixas_frete)
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
        # * [EXPLICAÇÃO] → Devolve a config usada nesse cálculo — evita
        #                  o chamador (recomendação de preço) ter que
        #                  buscar de novo só pra ler margem_minima etc.
        'config_tipo': config_tipo,
    }