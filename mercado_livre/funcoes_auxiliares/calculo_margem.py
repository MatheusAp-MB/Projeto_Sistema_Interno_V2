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
from produtos.funcoes_auxiliares.dimensoes_fisicas import (
    metro_cubico_de_dimensoes, selecionar_faixa_por_dimensao,
)


def calcular_metro_cubico(produto, dimensoes_efetivas=None):
    """Custo de Coleta usa a EMBALAGEM (a caixa real coletada/
    despachada) — confirmado com o usuário. Se a embalagem ainda não
    foi cadastrada pra esse produto (campos None), retorna 0 — nunca
    finge um cálculo sem dado real. Usa "_ordenada_cm" (não mais
    "_apos_embalado" direto, 21/07) — única fonte usada por qualquer
    cálculo que precise de eixos consistentes.

    dimensoes_efetivas (14/09): opcional — um DimensoesEfetivas já
    resolvido (mercado_livre/funcoes_auxiliares/dimensoes_efetivas.py),
    a mesma fonte que a fórmula real de precificação usa (dimensão
    declarada pelo vendedor no anúncio do ML, com fallback pro Produto
    ERP). Quando passado, usa altura/largura/comprimento de lá em vez
    de ler o Produto direto. Sem esse parâmetro, comportamento antigo
    preservado — quem já chama sem ele (ex: Hub de Promoções) continua
    exatamente igual."""
    if dimensoes_efetivas is not None:
        return metro_cubico_de_dimensoes(
            dimensoes_efetivas.altura, dimensoes_efetivas.largura, dimensoes_efetivas.comprimento,
        )
    return metro_cubico_de_dimensoes(
        produto.altura_ordenada_cm,
        produto.largura_ordenada_cm,
        produto.comprimento_ordenada_cm,
    )


def selecionar_faixa_armazenagem(produto, faixas_armazenagem=None, dimensoes_efetivas=None):
    """Acha a primeira faixa (em ordem crescente) onde TODAS as
    dimensões do produto cabem; se nenhuma comportar, usa a maior
    (fallback). Só usada quando o produto ainda não tem
    armazenagem_planilha (sem histórico na planilha validada).

    Usa EMBALAGEM (confirmado com o usuário — mesma regra de Coleta/
    Frete: é a caixa real que ocupa espaço físico no estoque, não o
    produto puro), sempre via "_ordenada_cm" (21/07) — nunca mais
    "_apos_embalado" direto, pra bater certo nas faixas sem depender
    de rótulo de eixo original. Se a embalagem ainda não tiver
    dimensão ordenada calculada, trata como 0 (mesma consistência de
    Coleta/Frete: nunca finge dado que não existe, nunca cai de volta
    pro produto sem embalar).

    faixas_armazenagem: opcional — lista já carregada em memória (só
    4 linhas no total, tabela pequena) por quem processa MUITOS
    produtos em lote, evitando 1 query nova por produto. Sem esse
    parâmetro, busca no banco normalmente (comportamento antigo,
    preservado pra quem chama 1 vez só, tipo a tela individual).

    dimensoes_efetivas (14/09): mesmo parâmetro e mesma regra de
    calcular_metro_cubico acima — dimensão já resolvida (variação do
    ML, com fallback pro Produto ERP) em vez do Produto direto, só
    quando passado."""
    if faixas_armazenagem is not None:
        faixas = faixas_armazenagem
    else:
        from precificacao.models import FaixaArmazenagem
        faixas = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

    if dimensoes_efetivas is not None:
        return selecionar_faixa_por_dimensao(
            dimensoes_efetivas.altura, dimensoes_efetivas.largura, dimensoes_efetivas.comprimento, faixas,
        )
    return selecionar_faixa_por_dimensao(
        produto.altura_ordenada_cm,
        produto.largura_ordenada_cm,
        produto.comprimento_ordenada_cm,
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


def calcular_fixo_detalhado(produto, config_geral=None, faixas_armazenagem=None, dimensoes_efetivas=None):
    """Mesma conta de calcular_fixo(), mas devolve TAMBÉM cada pedaço
    isolado (dict 'componentes') — usado pelo modal "como chegamos
    nesse preço", que precisa mostrar cada parte do FIXO separada
    (custo, coleta, armazenagem, os créditos), não só o número final
    já somado. calcular_fixo() continua igual pra todo mundo — só
    chama esta função por dentro e descarta os componentes.

    Sem impostos de entrada sincronizados (ou sem quantidade_nota pra
    calcular por unidade), devolve (None, None) — este produto não
    precifica, nunca finge um crédito que não existe.

    Coleta e Armazenagem (quando cai no fallback por dimensão) usam
    EMBALAGEM (confirmado com o usuário) — calcular_metro_cubico e
    selecionar_faixa_armazenagem já fazem isso internamente.

    dimensoes_efetivas (14/09): opcional — repassado direto pra
    calcular_metro_cubico e selecionar_faixa_armazenagem (mesma regra:
    dimensão já resolvida via variação do ML, com fallback pro Produto
    ERP, no lugar do Produto direto). Sem esse parâmetro, nada muda."""
    from django.core.exceptions import ObjectDoesNotExist
    from precificacao.models import ConfiguracaoOperacional
    from impostos.funcoes_auxiliares.entrada.creditos_fiscais_para_precificacao import montar_creditos_fiscais_para_precificacao

    try:
        impostos_entrada = produto.impostos_entrada
    except ObjectDoesNotExist:
        return None, None

    creditos = montar_creditos_fiscais_para_precificacao(impostos_entrada)
    if None in (creditos.icms, creditos.ipi, creditos.pis, creditos.cofins):
        return None, None

    config = config_geral if config_geral is not None else ConfiguracaoOperacional.obter()

    frete_cif_fob_percentual = produto.frete_cif_fob or Decimal('0')
    frete_cif_fob = frete_cif_fob_percentual / 100

    # IPI já vem em R$ pronto (dividido por unidade em impostos_entrada) —
    # nunca recalculado aqui a partir de percentual.
    ipi_valor = creditos.ipi
    frete_cif_fob_valor = produto.custo * frete_cif_fob
    # Decisão do Matheus (14/09/2026): custo_com_boni nunca é preenchido na
    # prática — parou de ser lido. custo_final usa sempre produto.custo direto.
    custo_final = produto.custo + ipi_valor + frete_cif_fob_valor

    metro_cubico = calcular_metro_cubico(produto, dimensoes_efetivas=dimensoes_efetivas)
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
        faixa_usada = selecionar_faixa_armazenagem(
            produto, faixas_armazenagem=faixas_armazenagem, dimensoes_efetivas=dimensoes_efetivas,
        )
        armazenagem = (faixa_usada.valor_diario * config.periodo_armazenagem) if faixa_usada else Decimal('0')

    # creditos.icms já vem certo pra qualquer regime (líquido do ST
    # quando o produto é ST, normal quando não é) — nunca soma os 2.
    fixo = coleta + armazenagem + custo_final - (creditos.icms + creditos.pis + creditos.cofins)

    componentes = {
        'custo': produto.custo,
        'custo_com_boni': produto.custo,  # sempre igual a 'custo' agora — sem fallback
        'ipi_valor': ipi_valor,
        'frete_cif_fob_percentual': frete_cif_fob_percentual,
        'frete_cif_fob_valor': frete_cif_fob_valor,
        'custo_final': custo_final,
        'metro_cubico': metro_cubico,
        'fator_coleta': config.fator_coleta,
        'coleta': coleta,
        'armazenagem_origem': 'planilha' if produto.armazenagem_planilha is not None else 'faixa_dimensao',
        'armazenagem': armazenagem,
        'credito_icms': creditos.icms,
        'credito_pis': creditos.pis,
        'credito_cofins': creditos.cofins,
        'fixo': fixo,
    }

    return fixo, componentes


def calcular_fixo(produto, config_geral=None, faixas_armazenagem=None, dimensoes_efetivas=None):
    """config_geral, faixas_armazenagem: opcionais — já carregados em
    memória por quem processa MUITOS produtos em lote (a config geral
    é 1 linha só, nunca muda dentro da mesma execução do comando).
    Sem esses parâmetros, busca no banco normalmente (comportamento
    antigo, preservado — a tela individual continua chamando sem
    eles, sem nenhuma mudança de comportamento).

    dimensoes_efetivas (14/09): opcional — repassado direto pra
    calcular_fixo_detalhado (ver docstring de lá).

    None quando o produto não tem impostos de entrada sincronizados —
    nunca cai pro dado antigo do Produto (decisão: sem fallback)."""
    fixo, _ = calcular_fixo_detalhado(
        produto, config_geral=config_geral, faixas_armazenagem=faixas_armazenagem,
        dimensoes_efetivas=dimensoes_efetivas,
    )
    return fixo


def buscar_frete(produto, preco, faixas_candidatas=None, dimensoes_efetivas=None):
    """Se faixas_candidatas for passado (já filtradas por peso, em
    memória — sem query nova), busca o frete em Python. Sem isso,
    cai no comportamento original (1 query por chamada) — mantém
    compatibilidade com quem já chama sem esse parâmetro.

    Frete usa EMBALAGEM (peso físico E peso cúbico, ambos da caixa
    real) — confirmado com o usuário. Se a embalagem não tiver peso
    cadastrado, usa 0 (nunca cai pro peso do produto puro, que
    subestimaria o frete real).

    dimensoes_efetivas (14/09): opcional — quando passado, usa o peso
    já resolvido ali (variação do ML, com fallback pro Produto ERP —
    mesma fonte que a fórmula real de precificação usa) em vez de
    recalcular o peso a partir dos campos do Produto direto. Só se
    aplica no caminho de query nova (abaixo) — quando faixas_candidatas
    já vem pronto, o peso já foi usado por quem filtrou antes de
    chamar esta função, fora daqui."""
    if faixas_candidatas is not None:
        for faixa in faixas_candidatas:
            if faixa.preco_min <= preco and (faixa.preco_max is None or faixa.preco_max >= preco):
                return faixa.valor
        return None

    from mercado_livre.models import FreteML

    if dimensoes_efetivas is not None:
        peso = dimensoes_efetivas.peso
    else:
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

def calcular_margem(produto, preco, tipo_anuncio_obj=None, rebate_percentual=None, preco_original=None, config_tipo=None, fixo=None, faixas_frete=None, variacao=None):
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
    None (precisa de pelo menos 1 dos 2).

    * [EXPLICAÇÃO] → variacao (14/09): opcional — a VariacaoAnuncioMercadoLivre
    real por trás do preço, quando existir. Quando passada, resolve a
    dimensão efetiva (mercado_livre/funcoes_auxiliares/dimensoes_efetivas.py
    — a MESMA função que a fórmula real de precificação usa: dimensão
    declarada pelo vendedor no anúncio do ML, com fallback pro Produto
    ERP) e usa ela pra Coleta/Armazenagem/Frete, em vez de ler sempre o
    Produto ERP direto. Corrige a divergência real encontrada em
    14/09/2026: sem isso, esta função sempre lia a dimensão do ERP,
    mesmo quando o preço oficial foi calculado com a dimensão declarada
    no ML — produzindo uma margem diferente da Visão 1 pra qualquer
    produto com dimensão/peso do ML diferente do ERP. Retorna None
    também quando a dimensão não resolve (nem variação nem Produto ERP
    têm dado suficiente) — nunca finge um cálculo sem dado real. Sem
    esse parâmetro (comportamento antigo, preservado pra quem já chama
    sem ele — ex: Hub de Promoções), nada muda."""
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
    pis_saida = (produto.pis_percentual or Decimal('0')) / 100
    cofins_saida = (produto.cofins_percentual or Decimal('0')) / 100
    taxa = comissao + icms_saida + pis_saida + cofins_saida

    dimensoes_efetivas = None
    if variacao is not None:
        from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
        dimensoes_efetivas = resolver_dimensoes_efetivas(produto, variacao)
        if dimensoes_efetivas is None:
            return None

    if fixo is None:
        fixo = calcular_fixo(produto, dimensoes_efetivas=dimensoes_efetivas)
    if fixo is None:
        return None
    frete = buscar_frete(produto, preco, faixas_candidatas=faixas_frete, dimensoes_efetivas=dimensoes_efetivas)
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