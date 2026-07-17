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
#
#              Renomeado (15/07) — Produto agora separa EXPLICITAMENTE
#              "produto sem embalar" (peso/dimensão do item puro) de
#              "produto após embalado" (a caixa REAL enviada/coletada).
#              Confirmado com o usuário: Coleta e Frete DEVEM usar
#              EMBALAGEM (nunca o produto puro, que sistematicamente
#              subestimaria os dois). Faixa de Armazenagem (fallback,
#              quando não há armazenagem_planilha) continua usando
#              produto SEM EMBALAR por enquanto — não foi confirmado
#              se deveria virar embalagem também; ver comentário na
#              função selecionar_faixa_armazenagem.

from decimal import Decimal
from django.db.models import Q


def metro_cubico_de_dimensoes(altura, largura, comprimento):
    """Conta pura — m³ a partir de altura/largura/comprimento em CM.
    Reaproveitada tanto por calcular_metro_cubico (produto do ERP)
    quanto por FormulaPrecificacao (DimensoesEfetivas, que pode vir da
    Variação ML) — evita duplicar a mesma fórmula 2x."""
    if altura is None or largura is None or comprimento is None:
        return Decimal('0')
    return (altura / 100) * (largura / 100) * (comprimento / 100)


def calcular_metro_cubico(produto):
    """Custo de Coleta usa a EMBALAGEM (a caixa real coletada/
    despachada) — confirmado com o usuário. Se a embalagem ainda não
    foi cadastrada pra esse produto (campos None), retorna 0 — nunca
    finge um cálculo sem dado real."""
    return metro_cubico_de_dimensoes(
        produto.altura_produto_apos_embalado,
        produto.largura_produto_apos_embalado,
        produto.comprimento_produto_apos_embalado,
    )


def selecionar_faixa_por_dimensao(altura, largura, comprimento, faixas):
    """Conta pura — acha a primeira faixa (ordem crescente) onde TODAS
    as dimensões cabem; se nenhuma comportar, usa a maior (fallback).
    Reaproveitada tanto por selecionar_faixa_armazenagem (produto do
    ERP) quanto por FormulaPrecificacao (DimensoesEfetivas) — evita
    duplicar a mesma busca 2x."""
    if not faixas:
        return None

    altura = altura or Decimal('0')
    largura = largura or Decimal('0')
    comprimento = comprimento or Decimal('0')

    for faixa in faixas:
        if (altura <= faixa.max_altura
                and largura <= faixa.max_largura
                and comprimento <= faixa.max_profundidade):
            return faixa

    return faixas[-1]


def selecionar_faixa_armazenagem(produto, faixas_armazenagem=None):
    """Acha a primeira faixa (em ordem crescente) onde TODAS as
    dimensões do produto cabem; se nenhuma comportar, usa a maior
    (fallback). Só usada quando o produto ainda não tem
    armazenagem_planilha (sem histórico na planilha validada).

    Usa EMBALAGEM (confirmado com o usuário — mesma regra de Coleta/
    Frete: é a caixa real que ocupa espaço físico no estoque, não o
    produto puro). Se a embalagem ainda não tiver dimensão cadastrada,
    trata como 0 (mesma consistência de Coleta/Frete: nunca finge
    dado que não existe, nunca cai de volta pro produto sem embalar).

    faixas_armazenagem: opcional — lista já carregada em memória (só
    4 linhas no total, tabela pequena) por quem processa MUITOS
    produtos em lote, evitando 1 query nova por produto. Sem esse
    parâmetro, busca no banco normalmente (comportamento antigo,
    preservado pra quem chama 1 vez só, tipo a tela individual)."""
    if faixas_armazenagem is not None:
        faixas = faixas_armazenagem
    else:
        from mercado_livre.models import FaixaArmazenagemMercadoLivre
        faixas = list(FaixaArmazenagemMercadoLivre.objects.filter(ativo=True).order_by('ordem'))

    return selecionar_faixa_por_dimensao(
        produto.altura_produto_apos_embalado,
        produto.largura_produto_apos_embalado,
        produto.comprimento_produto_apos_embalado,
        faixas,
    )


def buscar_configuracao_tipo_anuncio(tipo_anuncio_obj):
    """Busca a configuração (comissão, margens) só pelo tipo de anúncio
    (Clássico/Premium) — simplificado em 27/07: logística e catálogo
    não afetam mais comissão/margem (confirmado com o usuário/superior),
    só essa distinção importa pra precificação agora."""
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre

    return ConfiguracaoTipoAnuncioMercadoLivre.objects.filter(
        tipo_anuncio=tipo_anuncio_obj.tipo_anuncio,
    ).first()


def calcular_fixo_detalhado(produto, config_geral=None, faixas_armazenagem=None):
    """Mesma conta de calcular_fixo(), mas devolve TAMBÉM cada pedaço
    isolado (dict 'componentes') — usado pelo modal "como chegamos
    nesse preço", que precisa mostrar cada parte do FIXO separada
    (custo, coleta, armazenagem, os 2 créditos), não só o número final
    já somado. calcular_fixo() continua igual pra todo mundo — só
    chama esta função por dentro e descarta os componentes.

    Coleta e Armazenagem (quando cai no fallback por dimensão) usam
    EMBALAGEM (confirmado com o usuário) — calcular_metro_cubico e
    selecionar_faixa_armazenagem já fazem isso internamente."""
    from mercado_livre.models import ConfiguracaoMercadoLivre

    config = config_geral if config_geral is not None else ConfiguracaoMercadoLivre.obter()

    custo_com_boni = produto.custo_com_boni or produto.custo
    ipi_percentual = produto.ipi or Decimal('0')
    frete_cif_fob_percentual = produto.frete_cif_fob or Decimal('0')
    st_valor = produto.st_valor or Decimal('0')
    icms_entrada_percentual = produto.icms_entrada or Decimal('0')
    pis_percentual = produto.pis_cofins or Decimal('0')

    ipi = ipi_percentual / 100
    frete_cif_fob = frete_cif_fob_percentual / 100
    icms_entrada = icms_entrada_percentual / 100
    pis = pis_percentual / 100

    ipi_valor = custo_com_boni * ipi
    frete_cif_fob_valor = custo_com_boni * frete_cif_fob
    custo_final = custo_com_boni + ipi_valor + frete_cif_fob_valor + st_valor

    metro_cubico = calcular_metro_cubico(produto)
    coleta = metro_cubico * config.fator_coleta

    # * [EXPLICAÇÃO] → armazenagem_planilha já é o valor MENSAL real
    #                  (vem pronto da planilha validada) — só cai na
    #                  faixa dinâmica (por dimensão, via embalagem) se
    #                  o produto ainda não tiver passado por essa
    #                  importação.
    faixa_usada = None
    if produto.armazenagem_planilha is not None:
        armazenagem = produto.armazenagem_planilha
    else:
        faixa_usada = selecionar_faixa_armazenagem(produto, faixas_armazenagem=faixas_armazenagem)
        armazenagem = (faixa_usada.valor_diario * config.periodo_armazenagem) if faixa_usada else Decimal('0')

    credito_icms_entrada = produto.custo * icms_entrada
    credito_pis = produto.custo * pis

    fixo = coleta + armazenagem + custo_final - (credito_icms_entrada + credito_pis)

    componentes = {
        'custo': produto.custo,
        'custo_com_boni': custo_com_boni,
        'ipi_percentual': ipi_percentual,
        'ipi_valor': ipi_valor,
        'frete_cif_fob_percentual': frete_cif_fob_percentual,
        'frete_cif_fob_valor': frete_cif_fob_valor,
        'st_valor': st_valor,
        'custo_final': custo_final,
        'metro_cubico': metro_cubico,
        'fator_coleta': config.fator_coleta,
        'coleta': coleta,
        'armazenagem_origem': 'planilha' if produto.armazenagem_planilha is not None else 'faixa_dimensao',
        'armazenagem': armazenagem,
        'icms_entrada_percentual': icms_entrada_percentual,
        'credito_icms_entrada': credito_icms_entrada,
        'pis_percentual': pis_percentual,
        'credito_pis': credito_pis,
        'fixo': fixo,
    }

    return fixo, componentes


def calcular_fixo(produto, config_geral=None, faixas_armazenagem=None):
    """config_geral, faixas_armazenagem: opcionais — já carregados em
    memória por quem processa MUITOS produtos em lote (a config geral
    é 1 linha só, nunca muda dentro da mesma execução do comando).
    Sem esses parâmetros, busca no banco normalmente (comportamento
    antigo, preservado — a tela individual continua chamando sem
    eles, sem nenhuma mudança de comportamento)."""
    fixo, _ = calcular_fixo_detalhado(produto, config_geral=config_geral, faixas_armazenagem=faixas_armazenagem)
    return fixo


def buscar_frete(produto, preco, faixas_candidatas=None):
    """Se faixas_candidatas for passado (já filtradas por peso, em
    memória — sem query nova), busca o frete em Python. Sem isso,
    cai no comportamento original (1 query por chamada) — mantém
    compatibilidade com quem já chama sem esse parâmetro.

    Frete usa EMBALAGEM (peso físico E peso cúbico, ambos da caixa
    real) — confirmado com o usuário. Se a embalagem não tiver peso
    cadastrado, usa 0 (nunca cai pro peso do produto puro, que
    subestimaria o frete real)."""
    if faixas_candidatas is not None:
        for faixa in faixas_candidatas:
            if faixa.preco_min <= preco and (faixa.preco_max is None or faixa.preco_max >= preco):
                return faixa.valor
        return None

    from mercado_livre.models import FreteML

    peso_cubado = produto.peso_cubado or Decimal('0')
    peso_embalagem = produto.peso_produto_apos_embalado or Decimal('0')
    peso = max(peso_embalagem, peso_cubado)

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