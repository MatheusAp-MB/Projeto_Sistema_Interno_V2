# * [RESUMO] → Motor GENÉRICO do Goal Seek — dado uma meta de margem,
#              acha o preço que bate nela. NÃO sabe o que é Mercado
#              Livre, Shopee ou qualquer marketplace — só recebe
#              números já prontos (fixo, taxa, margem-alvo, custo) e
#              uma lista de faixas de frete candidatas (qualquer objeto
#              com .preco_min / .preco_max / .valor serve, de qualquer
#              marketplace). Quem monta esses números a partir de
#              Produto + configuração real de cada marketplace é uma
#              camada separada (ex: precificacao/funcoes_auxiliares/
#              mercado_livre/).
#
#              Fórmula (mesma direção contrária de calcular_margem,
#              já validada e em produção):
#                  denominador = 1 − taxa − margem_alvo
#                  preço_exato = (frete + FIXO) ÷ denominador
#
#              O frete entra nos dois lados (é custo, mas também
#              depende do preço) — resolvido por busca finita e exata
#              entre as faixas candidatas (no máximo 8 no ML, geralmente
#              2-4 verificações na prática), nunca por aproximação
#              numérica. Documentado e validado pelo usuário.
#
#              RoundUp90: o preço final SEMPRE arredonda pra CIMA até
#              terminar em ",90" — nunca pra baixo. Isso garante
#              matematicamente que a margem final nunca fica abaixo da
#              meta (só igual ou acima) — validado com assert.

from decimal import Decimal, ROUND_CEILING


def arredondar_para_90(preco_exato):
    """Arredonda SEMPRE pra CIMA até terminar em ',90'. Nunca pra
    baixo — é isso que garante a margem final >= margem-alvo."""
    preco_exato = Decimal(str(preco_exato))
    k = (preco_exato - Decimal('0.90')).to_integral_value(rounding=ROUND_CEILING)
    return k + Decimal('0.90')


def resolver_preco_por_margem(fixo, taxa_percentual, margem_alvo_fracao, custo_produto,
                               faixas_frete_candidatas, rebate_valor=Decimal('0')):
    """Acha o preço que atinge (ou supera) a margem-alvo, resolvendo a
    circularidade do frete por busca finita entre as faixas candidatas.

    fixo: Decimal — custos que não dependem do preço (já calculado)
    taxa_percentual: Decimal — soma de comissão+ICMS+PIS, em FRAÇÃO (ex: 0.12)
    margem_alvo_fracao: Decimal — meta de margem, em FRAÇÃO (ex: 0.15)
    custo_produto: Decimal — só usado pra achar a faixa de frete inicial
                   (preço de venda nunca é menor que o custo)
    faixas_frete_candidatas: lista de objetos com .preco_min/.preco_max/
                   .valor, JÁ FILTRADOS pelo peso do produto, ordenados
                   por preco_min crescente (quem chama monta essa lista)
    rebate_valor: Decimal — opcional, valor em R$ que o marketplace abate
                   (ex: rebate do ML) — entra como crédito no numerador,
                   não cria circularidade nova porque depende do PREÇO
                   ORIGINAL (já conhecido), nunca do preço que está sendo
                   resolvido agora.

    Retorna dict com preco_calculado, frete_usado, margem_percentual_obtida,
    faixa_frete — ou None se a meta for matematicamente inatingível (
    denominador <= 0) ou nenhuma faixa gerar solução consistente."""
    denominador = Decimal('1') - taxa_percentual - margem_alvo_fracao
    if denominador <= 0:
        return None

    fixo = Decimal(str(fixo))
    custo_produto = Decimal(str(custo_produto))
    rebate_valor = Decimal(str(rebate_valor))
    margem_alvo_percentual = margem_alvo_fracao * 100

    # * [EXPLICAÇÃO] → Pula faixas cujo teto é menor que o custo do
    #                  produto — vender abaixo do custo nunca é uma
    #                  solução válida, e testar essas faixas seria
    #                  desperdício certo.
    faixas_validas = [
        f for f in faixas_frete_candidatas
        if f.preco_max is None or f.preco_max >= custo_produto
    ]

    for faixa in faixas_validas:
        frete = Decimal(str(faixa.valor))

        # * [EXPLICAÇÃO] → guarda FIXO Negativo (10/09) — a garantia do RoundUp90 (arredondar
        #                  pra cima só AUMENTA a margem) só vale quando (frete + fixo - rebate)
        #                  é positivo. Quando esse total fica negativo (ex: crédito fiscal de
        #                  entrada maior que o custo — produto com custo/custo_com_boni
        #                  zerados no cadastro, ver Bug Conhecido "FIXO Negativo"), a relação
        #                  margem×preço se INVERTE e arredondar pra cima DIMINUI a margem — o
        #                  assert abaixo quebraria por um problema de DADO, não de fórmula.
        #                  Pula a faixa (mesmo sinal de "não resolveu" que piso/teto já usam).
        if (frete + fixo - rebate_valor) < 0:
            continue

        preco_exato = (frete + fixo - rebate_valor) / denominador
        preco_90 = arredondar_para_90(preco_exato)

        dentro_do_piso = preco_90 >= faixa.preco_min
        dentro_do_teto = faixa.preco_max is None or preco_90 <= faixa.preco_max

        if dentro_do_piso and dentro_do_teto:
            # * [EXPLICAÇÃO] → Recalcula "pra frente" com o preço já
            #                  arredondado — validação cruzada real,
            #                  não confia cegamente na fórmula inversa.
            margem_valor = preco_90 * (1 - taxa_percentual) - fixo - frete + rebate_valor
            margem_percentual_obtida = (margem_valor / preco_90) * 100

            assert margem_percentual_obtida >= margem_alvo_percentual, (
                f'Margem obtida ({margem_percentual_obtida}%) ficou ABAIXO da margem-alvo '
                f'({margem_alvo_percentual}%) — RoundUp90 deveria garantir margem sempre >= '
                f'meta. Verificar a fórmula ou a busca de faixa de frete.'
            )

            return {
                'preco_calculado': preco_90,
                'frete_usado': frete,
                'margem_percentual_obtida': margem_percentual_obtida,
                'faixa_frete': faixa,
                # * [EXPLICAÇÃO] → Passo a passo completo, só pra
                #                  exibição/auditoria (modal "como
                #                  chegamos nesse preço") — nunca usado
                #                  em nenhuma decisão de cálculo daqui
                #                  pra frente. Quem chama essa função
                #                  pode complementar com o que só ELE
                #                  sabe (comissão/ICMS/PIS separados,
                #                  peso, etc.) antes de persistir.
                'detalhamento': {
                    'custo_produto': custo_produto,
                    'fixo': fixo,
                    'rebate_valor': rebate_valor,
                    'taxa_percentual': taxa_percentual * 100,
                    'margem_alvo_percentual': margem_alvo_percentual,
                    'faixa_preco_min': faixa.preco_min,
                    'faixa_preco_max': faixa.preco_max,
                    'frete_usado': frete,
                    'denominador': denominador,
                    'preco_exato_antes_arredondar': preco_exato,
                    'preco_calculado': preco_90,
                    'margem_valor': margem_valor,
                    'margem_percentual_obtida': margem_percentual_obtida,
                },
            }

    return None


def resolver_preco_com_frete_dinamico(fixo, taxa_percentual, margem_alvo_fracao, custo_produto,
                                       faixas_preco_candidatas, consultar_frete,
                                       rebate_valor=Decimal('0'), max_correcoes_por_faixa=3):
    """Resolve a circularidade preço↔frete quando o frete não vem de uma tabela fixa, mas de
    uma função externa que devolve o frete PRA UM PREÇO ESPECÍFICO (ex: simulação via API do
    Mercado Livre — ver FreteRealML.simular()). Mesmo espírito de resolver_preco_por_margem
    (busca finita, com faixas candidatas), mas em vez de ler faixa.valor da tabela, CONSULTA
    o frete a cada tentativa, com confirmação: chama consultar_frete() no piso da faixa
    candidata (estimativa), resolve o preço, confirma consultando de novo no preço resolvido
    — se bater, fechou; se não bater, corrige com o valor confirmado e tenta de novo (a mesma
    faixa), até max_correcoes_por_faixa vezes, antes de desistir dessa faixa e ir pra próxima.
    Mecanismo validado com produto real antes de virar código de produção (Checkpoint -
    Desenho da Frente A, seção 7 do vault).

    faixas_preco_candidatas: mesmo formato de resolver_preco_por_margem (.preco_min/
    .preco_max), usada só pelos LIMITES de preço pra saber onde testar — o .valor de cada
    faixa é ignorado aqui, o frete de verdade vem sempre de consultar_frete().

    consultar_frete: callable(item_price) -> tuple[Decimal, dict] | None. Devolve
    (valor_do_frete, detalhamento_cru_da_api) — o detalhamento é o mesmo dict que
    FreteRealML._extrair() monta (billable_weight/discount_type/discount_rate/
    discount_promoted_amount), repassado sem interpretação nenhuma, só pra fins de
    auditoria (Pendência #1, 28/09/2026) — nunca usado em nenhuma decisão de cálculo
    aqui dentro. None sinaliza falha (API fora, erro, timeout, ou sem dado suficiente)
    — nesse caso a função inteira devolve None, pra quem chamou cair no fallback (nunca
    mistura frete de fontes diferentes numa mesma resolução).

    Retorna o mesmo formato de resolver_preco_por_margem (dict com preco_calculado,
    frete_usado, margem_percentual_obtida, faixa_frete, detalhamento) — 'detalhamento'
    ganha a chave extra 'frete_detalhamento_api', com o detalhamento CONFIRMADO (da
    chamada que bateu com a estimativa, nunca de uma tentativa intermediária descartada)
    — ou None."""
    denominador = Decimal('1') - taxa_percentual - margem_alvo_fracao
    if denominador <= 0:
        return None

    fixo = Decimal(str(fixo))
    custo_produto = Decimal(str(custo_produto))
    rebate_valor = Decimal(str(rebate_valor))
    margem_alvo_percentual = margem_alvo_fracao * 100

    faixas_validas = [
        f for f in faixas_preco_candidatas
        if f.preco_max is None or f.preco_max >= custo_produto
    ]

    for faixa in faixas_validas:
        resultado_estimativa = consultar_frete(faixa.preco_min)
        if resultado_estimativa is None:
            return None
        frete, _ = resultado_estimativa

        for _ in range(max_correcoes_por_faixa):
            # * [EXPLICAÇÃO] → mesma guarda de FIXO Negativo das outras funções deste
            #                  módulo — pula a faixa em vez de deixar o RoundUp90 diminuir
            #                  a margem em vez de aumentar.
            if (frete + fixo - rebate_valor) < 0:
                break

            preco_exato = (frete + fixo - rebate_valor) / denominador
            preco_90 = arredondar_para_90(preco_exato)

            resultado_confirmacao = consultar_frete(preco_90)
            if resultado_confirmacao is None:
                return None
            frete_confirmado, detalhamento_confirmado = resultado_confirmacao

            if frete_confirmado == frete:
                margem_valor = preco_90 * (1 - taxa_percentual) - fixo - frete + rebate_valor
                margem_percentual_obtida = (margem_valor / preco_90) * 100

                assert margem_percentual_obtida >= margem_alvo_percentual, (
                    f'Margem obtida ({margem_percentual_obtida}%) ficou ABAIXO da margem-alvo '
                    f'({margem_alvo_percentual}%) com frete dinâmico — verificar a fórmula.'
                )

                return {
                    'preco_calculado': preco_90,
                    'frete_usado': frete,
                    'margem_percentual_obtida': margem_percentual_obtida,
                    'faixa_frete': faixa,
                    'detalhamento': {
                        'custo_produto': custo_produto,
                        'fixo': fixo,
                        'rebate_valor': rebate_valor,
                        'taxa_percentual': taxa_percentual * 100,
                        'margem_alvo_percentual': margem_alvo_percentual,
                        'faixa_preco_min': faixa.preco_min,
                        'faixa_preco_max': faixa.preco_max,
                        'frete_usado': frete,
                        'denominador': denominador,
                        'preco_exato_antes_arredondar': preco_exato,
                        'preco_calculado': preco_90,
                        'margem_valor': margem_valor,
                        'margem_percentual_obtida': margem_percentual_obtida,
                        # * [EXPLICAÇÃO] → Pendência #1 (28/09/2026) — detalhamento CRU
                        #                  da chamada que CONFIRMOU o frete (nunca de
                        #                  uma tentativa intermediária descartada).
                        #                  billable_weight/discount_type/discount_rate/
                        #                  discount_promoted_amount, do jeito que a API
                        #                  devolveu — repassado sem interpretação.
                        'frete_detalhamento_api': detalhamento_confirmado,
                    },
                }

            frete = frete_confirmado

        # esgotou as correções nesta faixa sem convergir — tenta a próxima

    return None


def resolver_preco_com_frete_fixo(fixo, taxa_percentual, margem_alvo_fracao, frete,
                                   taxa_unidade=Decimal('0'), rebate_valor=Decimal('0')):
    """Mesma fórmula de resolver_preco_por_margem, mas SEM busca de
    faixa — usado quando o frete já é um número fechado, sem tabela
    (ex: marketplace onde o comprador paga o frete — frete=0 — ou
    frete fixo de verdade, sem faixa peso×preço). NÃO usado hoje pelo
    Mercado Livre (lá o frete sempre passa por busca de faixa, mesmo
    quando o peso vem da dimensão declarada do ML) — mantido genérico
    pra outros marketplaces que vierem a usar esse motor.

    taxa_unidade: Decimal — opcional, taxa FIXA em R$ cobrada por
                  unidade vendida (ex: Magalu), na MESMA posição do
                  frete na fórmula — independente do preço. Default 0,
                  então quem não usa (ML) não muda nada."""
    denominador = Decimal('1') - taxa_percentual - margem_alvo_fracao
    if denominador <= 0:
        return None

    fixo = Decimal(str(fixo))
    frete = Decimal(str(frete))
    taxa_unidade = Decimal(str(taxa_unidade))
    rebate_valor = Decimal(str(rebate_valor))
    margem_alvo_percentual = margem_alvo_fracao * 100

    # * [EXPLICAÇÃO] → guarda FIXO Negativo (10/09) — mesma razão de resolver_preco_por_margem:
    #                  a garantia do RoundUp90 só vale com (frete + taxa_unidade + fixo -
    #                  rebate) positivo. Sem faixa pra tentar outra combinação (frete é fixo
    #                  aqui, ao contrário de resolver_preco_por_margem), quando viola devolve
    #                  None — mesmo sinal de "sem solução" que denominador <= 0 já usa acima.
    if (frete + taxa_unidade + fixo - rebate_valor) < 0:
        return None

    preco_exato = (frete + taxa_unidade + fixo - rebate_valor) / denominador
    preco_90 = arredondar_para_90(preco_exato)

    margem_valor = preco_90 * (1 - taxa_percentual) - fixo - frete - taxa_unidade + rebate_valor
    margem_percentual_obtida = (margem_valor / preco_90) * 100

    assert margem_percentual_obtida >= margem_alvo_percentual, (
        f'Margem obtida ({margem_percentual_obtida}%) ficou ABAIXO da margem-alvo '
        f'({margem_alvo_percentual}%) com frete real fixo — RoundUp90 deveria garantir '
        f'margem sempre >= meta. Verificar a fórmula.'
    )

    return {
        'preco_calculado': preco_90,
        'frete_usado': frete,
        'margem_percentual_obtida': margem_percentual_obtida,
        'detalhamento': {
            'custo_produto': None,  # preenchido por quem chama (só ele sabe)
            'fixo': fixo,
            'taxa_unidade': taxa_unidade,
            'rebate_valor': rebate_valor,
            'taxa_percentual': taxa_percentual * 100,
            'margem_alvo_percentual': margem_alvo_percentual,
            'faixa_preco_min': None,
            'faixa_preco_max': None,
            'frete_usado': frete,
            'frete_origem': 'real',
            'denominador': denominador,
            'preco_exato_antes_arredondar': preco_exato,
            'preco_calculado': preco_90,
            'margem_valor': margem_valor,
            'margem_percentual_obtida': margem_percentual_obtida,
        },
    }


def resolver_preco_por_faixa_comissao(fixo, margem_alvo_fracao, custo_produto, frete,
                                       faixas_comissao_candidatas, taxa_extra_fracao=Decimal('0'),
                                       rebate_valor=Decimal('0')):
    """Acha o preço que atinge (ou supera) a margem-alvo, resolvendo a
    circularidade da COMISSÃO por busca finita entre faixas de preço —
    inverso do que resolver_preco_por_margem faz (lá é o FRETE que varia
    por faixa com taxa fixa; aqui é a TAXA (comissão) + um adicional fixo
    em R$ que variam por faixa, com o FRETE fixo). Usado pela Shopee, cuja
    tabela de comissão muda (%+R$) conforme o valor do item.

    fixo: Decimal — custos que não dependem do preço (já calculado)
    margem_alvo_fracao: Decimal — meta de margem, em FRAÇÃO (ex: 0.15)
    custo_produto: Decimal — só usado pra pular faixas abaixo do custo
    frete: Decimal — fixo, não varia por faixa (diferente do ML)
    faixas_comissao_candidatas: lista de objetos com .preco_min/.preco_max/
                   .comissao_percentual (fração, ex: 0.20)/.adicional_fixo
                   (R$), ordenados por preco_min crescente
    taxa_extra_fracao: Decimal — soma adicional à comissão da faixa, ex:
                   ICMS saída + PIS/COFINS (impostos de governo, não varia
                   por faixa de preço — só a comissão da plataforma varia)
    rebate_valor: Decimal — opcional, mesmo papel de resolver_preco_por_margem

    Retorna dict com preco_calculado, frete_usado, margem_percentual_obtida,
    faixa_comissao — ou None se nenhuma faixa gerar solução consistente."""
    fixo = Decimal(str(fixo))
    custo_produto = Decimal(str(custo_produto))
    frete = Decimal(str(frete))
    rebate_valor = Decimal(str(rebate_valor))
    margem_alvo_percentual = margem_alvo_fracao * 100

    faixas_validas = [
        f for f in faixas_comissao_candidatas
        if f.preco_max is None or f.preco_max >= custo_produto
    ]

    for faixa in faixas_validas:
        comissao_percentual = Decimal(str(faixa.comissao_percentual)) / 100
        taxa_percentual = comissao_percentual + taxa_extra_fracao
        adicional_fixo = Decimal(str(faixa.adicional_fixo))

        denominador = Decimal('1') - taxa_percentual - margem_alvo_fracao
        if denominador <= 0:
            continue

        # * [EXPLICAÇÃO] → guarda FIXO Negativo (10/09) — mesma razão das outras 2 funções
        #                  deste módulo: a garantia do RoundUp90 só vale com (frete +
        #                  adicional_fixo + fixo - rebate) positivo. Pula a faixa.
        if (frete + adicional_fixo + fixo - rebate_valor) < 0:
            continue

        preco_exato = (frete + adicional_fixo + fixo - rebate_valor) / denominador
        preco_90 = arredondar_para_90(preco_exato)

        dentro_do_piso = preco_90 >= faixa.preco_min
        dentro_do_teto = faixa.preco_max is None or preco_90 <= faixa.preco_max

        if dentro_do_piso and dentro_do_teto:
            margem_valor = preco_90 * (1 - taxa_percentual) - fixo - frete - adicional_fixo + rebate_valor
            margem_percentual_obtida = (margem_valor / preco_90) * 100

            assert margem_percentual_obtida >= margem_alvo_percentual, (
                f'Margem obtida ({margem_percentual_obtida}%) ficou ABAIXO da margem-alvo '
                f'({margem_alvo_percentual}%) — RoundUp90 deveria garantir margem sempre >= '
                f'meta. Verificar a fórmula ou a busca de faixa de comissão.'
            )

            return {
                'preco_calculado': preco_90,
                'frete_usado': frete,
                'margem_percentual_obtida': margem_percentual_obtida,
                'faixa_comissao': faixa,
                'detalhamento': {
                    'custo_produto': custo_produto,
                    'fixo': fixo,
                    'rebate_valor': rebate_valor,
                    'comissao_percentual': comissao_percentual * 100,
                    'taxa_percentual': taxa_percentual * 100,
                    'adicional_fixo': adicional_fixo,
                    'margem_alvo_percentual': margem_alvo_percentual,
                    'faixa_preco_min': faixa.preco_min,
                    'faixa_preco_max': faixa.preco_max,
                    'frete_usado': frete,
                    'denominador': denominador,
                    'preco_exato_antes_arredondar': preco_exato,
                    'preco_calculado': preco_90,
                    'margem_valor': margem_valor,
                    'margem_percentual_obtida': margem_percentual_obtida,
                },
            }

    return None


