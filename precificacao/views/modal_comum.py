# precificacao/views/modal_comum.py

# Função Objetivo: Dataclasses de exibição do modal de auditoria — puro formato, sem
# nenhuma lógica de marketplace embutida. Reaproveitadas pelos modais de TODOS os
# marketplaces (ML, Magalu, e os que vierem depois).
#
# Taxonomia de proveniência (campo `origem` em LinhaPercentualValor/LinhaValorUnico) —
# 5 categorias, usadas pela tela de auditoria pra marcar "isso veio de onde":
#   'produto'   → cadastro do produto (custo, dimensão declarada, frete_cif_fob%...)
#   'nf'        → nota fiscal de entrada / crédito fiscal (ICMS/IPI/PIS/COFINS entrada)
#   'saida'     → imposto aplicado na venda (ICMS/PIS/COFINS saída)
#   'config'    → parâmetro operacional (fator de coleta, comissão, margem-alvo, faixas)
#   'calculado' → resultado de fórmula, não é dado bruto (default)
#
# Campos de prova (10/09, Camada 3) — ipi_valor_nota/icms_valor_nota/etc + quantidade_nota
# vêm de DadosEntrada.prova_fiscal (Camada 2). Todos opcionais (None em linha calculada
# ANTES da Camada 2) — o template só mostra a mini-fórmula quando o valor existe.

from dataclasses import dataclass


@dataclass
class LinhaPercentualValor:
    label: str
    percentual: object
    valor: object
    origem: str = 'calculado'


@dataclass
class LinhaValorUnico:
    label: str
    valor: object
    origem: str = 'produto'


# Função Objetivo: Bloco de PIS/COFINS (2 usos, bases diferentes) — usado pelos marketplaces
# que ainda não migraram pro padrão de campos separados do ML (Raia/Magalu/Shopee/TikTok/
# Amazon). Restaurado em 10/09: tinha sido removido junto com a Camada 3 do ML, mas
# modal_comum.py é compartilhado — os outros 5 marketplaces ainda chamam montar_pis_cofins()
# direto daqui, e a remoção quebrava o import deles (ImportError em cascata na app inteira).
@dataclass
class BlocoPisCofins:
    percentual: object
    credito_entrada: object
    taxa_saida: object


@dataclass
class DimensaoUsada:
    origem_label: str
    altura: object
    largura: object
    comprimento: object
    peso: object
    peso_fisico: object = None
    peso_cubico: object = None


@dataclass
class PassoCustoFinal:
    custo_com_boni: object
    ipi_valor: object
    frete_cif_fob_valor: object
    resultado: object
    ipi_valor_nota: object = None
    quantidade_nota: object = None


@dataclass
class PassoColeta:
    metro_cubico: object
    fator_coleta: object
    resultado: object


@dataclass
class PassoArmazenagem:
    origem: str
    periodo_dias: object
    resultado: object
    valor_diario: object = None


@dataclass
class PassoFixo:
    coleta: object
    armazenagem: object
    custo_final: object
    credito_icms: object
    credito_pis: object
    credito_cofins: object
    resultado: object
    icms_valor_nota: object = None
    icms_base_calculo: object = None
    icms_aliquota: object = None
    tem_icms_st: bool = False
    pis_valor_nota: object = None
    cofins_valor_nota: object = None
    quantidade_nota: object = None


@dataclass
class PassoTaxa:
    itens: list
    resultado: object
    # * [EXPLICAÇÃO] → R$ equivalente do resultado (% sobre o preço
    #                  final) — pedido explícito de auditoria: todo
    #                  percentual mostra o par em R$ ao lado (11/09).
    resultado_valor: object = None


@dataclass
class PassoDenominador:
    taxa_percentual: object
    margem_alvo_percentual: object
    resultado: object
    # * [EXPLICAÇÃO] → R$ dos 2 componentes do denominador — mesmo
    #                  motivo do PassoTaxa.resultado_valor acima. O
    #                  denominador em si (resultado) continua sem par
    #                  em R$: é um fator (0-1), não um valor monetário.
    taxa_valor: object = None
    margem_alvo_valor: object = None


# Função Objetivo: Passo 7 — faixa de frete escolhida (de PREÇO no ML, de PESO no Magalu).
@dataclass
class PassoFaixaFrete:
    peso: object
    faixa_min: object
    faixa_max: object
    resultado: object


@dataclass
class PassoPrecoExato:
    frete: object
    fixo: object
    rebate: object
    denominador: object
    resultado: object
    # * [EXPLICAÇÃO] → None por padrão — o ML não tem esse conceito
    #                  (nunca finge dado que não existe). Só o Magalu
    #                  preenche de verdade.
    taxa_unidade: object = None


@dataclass
class LinhaSaida:
    label: str
    valor: object
    tipo: str  # 'reais' ou 'percentual'
    destaque: bool = False
    # * [EXPLICAÇÃO] → par no OUTRO formato (R$ quando tipo='percentual',
    #                  e vice-versa) — pedido explícito de auditoria:
    #                  todo percentual mostra o R$ ao lado (11/09). None
    #                  quando o item não tem um par natural (ex: preço
    #                  final não tem "% de quê").
    valor_par: object = None


# Função Objetivo: 1 linha da Visão 2 (De onde vem o lucro) — desmontagem do preço final até
# sobrar o lucro. 'sinal' controla o símbolo e o estilo visual no template: 'inicio' (preço
# final, ponto de partida), 'menos'/'mais' (linhas normais de subtração/soma), 'checkpoint'
# (conferência interna, não soma na conta visual — só confirma que os componentes do FIXO
# batem com o FIXO da Visão 1) e 'final' (lucro, resultado).
@dataclass
class LinhaTeardown:
    label: str
    valor_reais: object
    valor_percentual: object
    sinal: str
    mini_explicacao: str = ''


# Função Objetivo: Resultado da contraprova da Visão 1 — chama calcular_margem() (calculo_margem.py,
# implementação independente) de verdade, com o preço final já persistido. 'disponivel=False'
# quando o produto não tem dados fiscais de entrada sincronizados ou não há faixa de frete pra
# esse preço (calcular_margem já devolve None nesses casos — nunca finge um número).
# 'bate' (14/09): antes o template mostrava "✓ Bate" fixo, sem comparar nada de verdade — agora
# 'bate' vem de uma comparação real (tolerância de R$ 0,05) entre esta margem e a oficial.
@dataclass
class ContraprovaVisao1:
    disponivel: bool
    margem_valor: object = None
    margem_percentual: object = None
    motivo_indisponivel: str = ''
    bate: bool = False
    diferenca_valor: object = None


# Função Objetivo: 1 item da tabela única de auditoria (Item | Como foi obtido | Valor | %).
@dataclass
class LinhaItemAuditoria:
    label: str
    origem: str  # 'produto' | 'nf' | 'saida' | 'config' | 'calculado'
    valor_reais: object = None
    valor_percentual: object = None
    mini_form: str = ''
    # unidade controla como o template formata `valor_reais`:
    # 'reais' (padrão, R$ 0,00) | 'reais_dia' (R$ 0,0000/dia) | 'cm' | 'kg' | 'm3' | 'dias' | 'fator' (número puro, sem sufixo)
    unidade: str = 'reais'


# Função Objetivo: 1 grupo (seção) da tabela única de auditoria — ex: "Comissão", "Taxas".
@dataclass
class GrupoItensAuditoria:
    titulo: str
    linhas: list


# Função Objetivo: Monta a tabela de valores de entrada (créditos de NF + saída + config) —
# comum a qualquer marketplace.
def montar_tabela_percentuais(e, i, dec, label_comissao='Comissão'):
    return [
        LinhaPercentualValor('IPI (crédito de entrada)', None, dec(i.get('ipi_valor')), origem='nf'),
        LinhaPercentualValor('Frete CIF/FOB', dec(e.get('frete_cif_fob_percentual')), dec(i.get('frete_cif_fob_valor')), origem='produto'),
        LinhaPercentualValor('Crédito ICMS (entrada)', None, dec(i.get('credito_icms_entrada')), origem='nf'),
        LinhaPercentualValor('Crédito PIS (entrada)', None, dec(i.get('credito_pis')), origem='nf'),
        LinhaPercentualValor('Crédito COFINS (entrada)', None, dec(i.get('credito_cofins')), origem='nf'),
        LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor')), origem='saida'),
        LinhaPercentualValor(label_comissao, dec(e.get('comissao_percentual')), dec(i.get('comissao_valor')), origem='config'),
        LinhaPercentualValor('Margem-alvo', dec(e.get('margem_alvo_percentual')), dec(i.get('margem_alvo_valor')), origem='config'),
    ]


# Função Objetivo: Monta o bloco de PIS/COFINS (2 usos, bases diferentes) — usado pelos
# marketplaces que ainda não migraram pro padrão de campos separados do ML. Nota: 'percentual'
# e 'taxa_saida' já vinham sempre em branco antes da Camada 3 também (pis_cofins_percentual/
# pis_cofins_valor não existem em NENHUMA das 6 fórmulas — mesma causa raiz do Duble antigo
# quebrado); só 'credito_entrada' é dado real. Restaurado tal como estava — corrigir isso de
# verdade é migrar os outros 5 marketplaces pro padrão do ML, fora de escopo por ora.
def montar_pis_cofins(e, i, dec):
    return BlocoPisCofins(
        percentual=dec(e.get('pis_cofins_percentual')),
        credito_entrada=dec(i.get('credito_pis')),
        taxa_saida=dec(i.get('pis_cofins_valor')),
    )


# Função Objetivo: Monta a lista de valores soltos (custo, fator de coleta...) — comum.
def montar_valores_soltos(e, dec):
    return [
        LinhaValorUnico('Custo do produto', dec(e.get('custo')), origem='produto'),
        LinhaValorUnico('Custo com bonificação', dec(e.get('custo_com_boni')), origem='produto'),
        LinhaValorUnico('Fator de coleta', dec(e.get('fator_coleta')), origem='config'),
        LinhaValorUnico('Período de armazenagem (dias)', dec(e.get('periodo_armazenagem')), origem='config'),
    ]


# Função Objetivo: Monta a dimensão usada — comum, só a origem_label varia por chamador.
def montar_dimensao(e, dec, origem_label):
    return DimensaoUsada(
        origem_label=origem_label,
        altura=dec(e.get('altura')), largura=dec(e.get('largura')),
        comprimento=dec(e.get('comprimento')), peso=dec(e.get('peso')),
        peso_fisico=dec(e.get('peso_fisico')), peso_cubico=dec(e.get('peso_cubico')),
    )


# Função Objetivo: Lê 1 imposto de dentro de DadosEntrada.prova_fiscal — (valor, base, alíquota).
# Explicação em detalhe: None nos 3 quando prova_fiscal não existe (linha calculada antes da
# Camada 2) ou quando o imposto específico não existe (só acontece com icms_st, quando o
# produto não é ST — nunca finge um ICMS ST que não existe).
def _prova_imposto(e, nome):
    prova = e.get('prova_fiscal') or {}
    imposto = prova.get(nome)
    if not imposto:
        return None, None, None
    return imposto.get('valor'), imposto.get('base_calculo'), imposto.get('aliquota')


def _quantidade_nota(e):
    prova = e.get('prova_fiscal') or {}
    return prova.get('quantidade_nota')


# Função Objetivo: Monta os passos 1-6 (custo final até denominador) — IDÊNTICOS entre
# marketplaces. Passos 7/8 (frete + preço exato) ficam por conta de quem chama, já que
# o significado da faixa (preço vs peso) e a existência de rebate diferem por canal.
def montar_passos_1_a_6(e, i, dec, label_comissao='Comissão'):
    qtd_nota = dec(_quantidade_nota(e))

    ipi_valor_nota, _, _ = _prova_imposto(e, 'ipi')
    passo_1 = PassoCustoFinal(
        custo_com_boni=dec(e.get('custo_com_boni')), ipi_valor=dec(i.get('ipi_valor')),
        frete_cif_fob_valor=dec(i.get('frete_cif_fob_valor')),
        resultado=dec(i.get('custo_final')),
        ipi_valor_nota=dec(ipi_valor_nota), quantidade_nota=qtd_nota,
    )
    passo_2 = PassoColeta(
        metro_cubico=dec(i.get('metro_cubico')), fator_coleta=dec(e.get('fator_coleta')),
        resultado=dec(i.get('coleta')),
    )
    passo_3 = PassoArmazenagem(
        origem=i.get('armazenagem_origem'), periodo_dias=dec(e.get('periodo_armazenagem')),
        resultado=dec(i.get('armazenagem')), valor_diario=dec(i.get('armazenagem_valor_diario')),
    )

    icms_valor_nota, icms_base, icms_aliquota = _prova_imposto(e, 'icms')
    pis_valor_nota, _, _ = _prova_imposto(e, 'pis')
    cofins_valor_nota, _, _ = _prova_imposto(e, 'cofins')
    tem_icms_st = bool((e.get('prova_fiscal') or {}).get('tem_icms_st', False))
    passo_4 = PassoFixo(
        coleta=dec(i.get('coleta')), armazenagem=dec(i.get('armazenagem')),
        custo_final=dec(i.get('custo_final')), credito_icms=dec(i.get('credito_icms_entrada')),
        credito_pis=dec(i.get('credito_pis')), credito_cofins=dec(i.get('credito_cofins')),
        resultado=dec(i.get('fixo')),
        icms_valor_nota=dec(icms_valor_nota), icms_base_calculo=dec(icms_base), icms_aliquota=dec(icms_aliquota),
        tem_icms_st=tem_icms_st, pis_valor_nota=dec(pis_valor_nota), cofins_valor_nota=dec(cofins_valor_nota),
        quantidade_nota=qtd_nota,
    )

    passo_5 = PassoTaxa(
        itens=[
            LinhaPercentualValor(label_comissao, dec(e.get('comissao_percentual')), dec(i.get('comissao_valor')), origem='config'),
            LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor')), origem='saida'),
            LinhaPercentualValor('PIS saída', dec(e.get('pis_saida_percentual')), dec(i.get('pis_saida_valor')), origem='saida'),
            LinhaPercentualValor('COFINS saída', dec(e.get('cofins_saida_percentual')), dec(i.get('cofins_saida_valor')), origem='saida'),
        ],
        resultado=dec(i.get('taxa_percentual')),
        resultado_valor=dec(i.get('taxa_valor')),
    )
    passo_6 = PassoDenominador(
        taxa_percentual=dec(i.get('taxa_percentual')), margem_alvo_percentual=dec(e.get('margem_alvo_percentual')),
        resultado=dec(i.get('denominador')),
        taxa_valor=dec(i.get('taxa_valor')), margem_alvo_valor=dec(i.get('margem_alvo_valor')),
    )
    return passo_1, passo_2, passo_3, passo_4, passo_5, passo_6


# Função Objetivo: Monta o bloco de saída (5 linhas) — comum a qualquer marketplace.
def montar_saida(i, s, dec):
    return [
        LinhaSaida('Preço exato', dec(i.get('preco_exato_antes_arredondar')), 'reais'),
        LinhaSaida('Margem exata', dec(s.get('margem_exata_percentual')), 'percentual', valor_par=dec(s.get('margem_exata_valor'))),
        LinhaSaida('Preço final (arredondado pra ,90)', dec(s.get('preco_final')), 'reais', destaque=True),
        LinhaSaida('Margem final', dec(s.get('margem_percentual_obtida')), 'percentual', destaque=True, valor_par=dec(s.get('margem_valor'))),
        LinhaSaida('Custo de frete final', dec(s.get('frete_usado')), 'reais'),
    ]


# Função Objetivo: Monta a tabela única de auditoria (Item | Como foi obtido | R$ | %),
# TODOS os itens que a fórmula usa, agrupados por tipo em ordem lógica — pra bater linha a
# linha com uma planilha de referência que usa cada valor solto. Só ML por enquanto (usa
# faixa_frete_peso_min/max, que é conceito específico do ML — Magalu usa faixa por peso).
def montar_tabela_itens_agrupada(e, i, s, dec):
    qtd_nota = dec(_quantidade_nota(e))
    # * [CORREÇÃO] → _prova_imposto devolve os valores CRUS do JSON
    #                (string, não Decimal) — precisa passar por dec()
    #                aqui, igual montar_passos_1_a_6 já fazia no ponto
    #                de uso. Sem isso, o f'{valor:.2f}' de mini() quebra
    #                com ValueError pra qualquer produto que tenha prova
    #                fiscal com alíquota (ex: crédito ICMS normal, não-ST).
    ipi_valor_nota_raw, _, _ = _prova_imposto(e, 'ipi')
    icms_valor_nota_raw, _, icms_aliquota_raw = _prova_imposto(e, 'icms')
    pis_valor_nota_raw, _, pis_aliquota_raw = _prova_imposto(e, 'pis')
    cofins_valor_nota_raw, _, cofins_aliquota_raw = _prova_imposto(e, 'cofins')

    ipi_valor_nota = dec(ipi_valor_nota_raw)
    icms_valor_nota, icms_aliquota = dec(icms_valor_nota_raw), dec(icms_aliquota_raw)
    pis_valor_nota, pis_aliquota = dec(pis_valor_nota_raw), dec(pis_aliquota_raw)
    cofins_valor_nota, cofins_aliquota = dec(cofins_valor_nota_raw), dec(cofins_aliquota_raw)

    def mini(valor_nota, aliquota):
        if valor_nota is None or qtd_nota is None:
            return ''
        if aliquota is not None:
            return f'R$ {valor_nota:.2f} nota × {aliquota:.2f}% ÷ {qtd_nota:.0f} unid.'
        return f'R$ {valor_nota:.2f} nota ÷ {qtd_nota:.0f} unid.'

    return [
        GrupoItensAuditoria('1. Produto / Custo base', [
            LinhaItemAuditoria('Custo do produto', 'produto', valor_reais=dec(e.get('custo'))),
            LinhaItemAuditoria('Custo com bonificação', 'produto', valor_reais=dec(e.get('custo_com_boni'))),
        ]),
        GrupoItensAuditoria('2. Dimensões e peso', [
            LinhaItemAuditoria('Altura', 'produto', valor_reais=dec(e.get('altura')), unidade='cm'),
            LinhaItemAuditoria('Largura', 'produto', valor_reais=dec(e.get('largura')), unidade='cm'),
            LinhaItemAuditoria('Comprimento', 'produto', valor_reais=dec(e.get('comprimento')), unidade='cm'),
            LinhaItemAuditoria('Peso físico', 'produto', valor_reais=dec(e.get('peso_fisico')), unidade='kg'),
            LinhaItemAuditoria('Peso cúbico', 'calculado', valor_reais=dec(e.get('peso_cubico')), unidade='kg'),
            LinhaItemAuditoria('Peso usado (maior entre físico e cúbico)', 'calculado', valor_reais=dec(e.get('peso')), unidade='kg'),
        ]),
        GrupoItensAuditoria('3. Créditos fiscais de entrada (NF)', [
            LinhaItemAuditoria('IPI', 'nf', valor_reais=dec(i.get('ipi_valor')), mini_form=mini(ipi_valor_nota, None)),
            LinhaItemAuditoria('Crédito ICMS entrada', 'nf', valor_reais=dec(i.get('credito_icms_entrada')), valor_percentual=dec(icms_aliquota), mini_form=mini(icms_valor_nota, icms_aliquota)),
            LinhaItemAuditoria('Crédito PIS entrada', 'nf', valor_reais=dec(i.get('credito_pis')), valor_percentual=dec(pis_aliquota), mini_form=mini(pis_valor_nota, pis_aliquota)),
            LinhaItemAuditoria('Crédito COFINS entrada', 'nf', valor_reais=dec(i.get('credito_cofins')), valor_percentual=dec(cofins_aliquota), mini_form=mini(cofins_valor_nota, cofins_aliquota)),
        ]),
        GrupoItensAuditoria('4. Frete de entrada (CIF/FOB)', [
            LinhaItemAuditoria('Frete CIF/FOB', 'produto', valor_reais=dec(i.get('frete_cif_fob_valor')), valor_percentual=dec(e.get('frete_cif_fob_percentual'))),
        ]),
        GrupoItensAuditoria('5. Coleta e armazenagem', [
            LinhaItemAuditoria('Metro cúbico', 'calculado', valor_reais=dec(i.get('metro_cubico')), unidade='m3'),
            LinhaItemAuditoria('Fator de coleta', 'config', valor_reais=dec(e.get('fator_coleta')), unidade='fator'),
            LinhaItemAuditoria('Coleta', 'calculado', valor_reais=dec(i.get('coleta'))),
            LinhaItemAuditoria('Faixa de armazenagem (valor/dia)', 'config', valor_reais=dec(i.get('armazenagem_valor_diario')), unidade='reais_dia'),
            LinhaItemAuditoria('Período de armazenagem', 'config', valor_reais=dec(e.get('periodo_armazenagem')), unidade='dias'),
            LinhaItemAuditoria('Armazenagem', 'calculado', valor_reais=dec(i.get('armazenagem'))),
        ]),
        GrupoItensAuditoria('6. Comissão', [
            LinhaItemAuditoria('Comissão', 'config', valor_reais=dec(i.get('comissao_valor')), valor_percentual=dec(e.get('comissao_percentual'))),
        ]),
        GrupoItensAuditoria('7. Impostos de saída', [
            LinhaItemAuditoria('ICMS saída', 'saida', valor_reais=dec(i.get('icms_saida_valor')), valor_percentual=dec(e.get('icms_saida_percentual'))),
            LinhaItemAuditoria('PIS saída', 'saida', valor_reais=dec(i.get('pis_saida_valor')), valor_percentual=dec(e.get('pis_saida_percentual'))),
            LinhaItemAuditoria('COFINS saída', 'saida', valor_reais=dec(i.get('cofins_saida_valor')), valor_percentual=dec(e.get('cofins_saida_percentual'))),
        ]),
        GrupoItensAuditoria('8. Taxas (soma)', [
            LinhaItemAuditoria('Taxa total', 'calculado', valor_reais=dec(i.get('taxa_valor')), valor_percentual=dec(i.get('taxa_percentual'))),
            LinhaItemAuditoria('Margem-alvo', 'config', valor_reais=dec(i.get('margem_alvo_valor')), valor_percentual=dec(e.get('margem_alvo_percentual'))),
            LinhaItemAuditoria('Denominador', 'calculado', mini_form='1 − taxa − margem-alvo (fator, sem R$/% próprio)'),
        ]),
        GrupoItensAuditoria('9. Frete de saída (Mercado Livre)', [
            LinhaItemAuditoria('Peso usado pra faixa', 'calculado', valor_reais=dec(e.get('peso')), unidade='kg'),
            LinhaItemAuditoria('Frete final usado (faixa FreteML)', 'config', valor_reais=dec(s.get('frete_usado'))),
        ]),
        GrupoItensAuditoria('10. Resultado', [
            LinhaItemAuditoria('Custo final', 'calculado', valor_reais=dec(i.get('custo_final'))),
            LinhaItemAuditoria('FIXO', 'calculado', valor_reais=dec(i.get('fixo'))),
            LinhaItemAuditoria('Rebate de promoção', 'calculado', valor_reais=dec(i.get('rebate_valor')), valor_percentual=dec(e.get('rebate_percentual'))),
            LinhaItemAuditoria('Preço exato (antes de arredondar)', 'calculado', valor_reais=dec(i.get('preco_exato_antes_arredondar'))),
            LinhaItemAuditoria('Preço final (arredondado ,90)', 'calculado', valor_reais=dec(s.get('preco_final'))),
            LinhaItemAuditoria('Margem exata (antes de arredondar)', 'calculado', valor_reais=dec(s.get('margem_exata_valor')), valor_percentual=dec(s.get('margem_exata_percentual'))),
            LinhaItemAuditoria('Margem final', 'calculado', valor_reais=dec(s.get('margem_valor')), valor_percentual=dec(s.get('margem_percentual_obtida'))),
        ]),
    ]


# Função Objetivo: Monta a lista de alertas do veredito (topo da tela) — comum a qualquer
# marketplace, já que FIXO/custo/dimensão/margem são conceitos universais entre canais.
# Explicação em detalhe: cada alerta carrega 'alvo' (número do passo ou 'produto') pro
# clique da lista rolar e expandir o passo certo. Os FLAGS visuais em cada passo (borda
# vermelha) são calculados direto no template por comparação simples — isso aqui só
# gera o TEXTO da lista do topo.
def montar_alertas(fixo, custo, custo_com_boni, altura, largura, comprimento, margem_alvo, margem_obtida):
    alertas = []

    sem_custo = not custo and not custo_com_boni
    sem_dimensao = not altura and not largura and not comprimento
    if sem_custo or sem_dimensao:
        if sem_custo and sem_dimensao:
            texto = 'Produto sem custo e sem dimensões cadastrados'
        elif sem_custo:
            texto = 'Produto sem custo cadastrado (custo e custo com bonificação zerados)'
        else:
            texto = 'Produto sem dimensões cadastradas (altura/largura/comprimento zerados)'
        alertas.append({'texto': texto, 'alvo': 'produto'})

    if fixo is not None and fixo < 0:
        alertas.append({
            'texto': f'Crédito fiscal de entrada maior que o custo final — FIXO negativo (R$ {fixo:.2f})',
            'alvo': 4,
        })

    if margem_alvo is not None and margem_obtida is not None and margem_obtida < margem_alvo:
        alertas.append({
            'texto': f'Margem obtida ({margem_obtida:.2f}%) abaixo da margem-alvo ({margem_alvo:.2f}%)',
            'alvo': 8,
        })

    return alertas


# Função Objetivo: Monta a Visão 2 (De onde vem o lucro) — mesmo preço final e mesmos dados
# da Visão 1, só que de trás pra frente: parte do preço de venda e vai subtraindo cada custo,
# 1 de cada vez (inclusive os que valem R$ 0,00), até sobrar só o lucro. Pedido explícito
# (14/09): nada resumido em bloco — cada componente do FIXO também vira linha própria aqui,
# na mesma ordem das camadas 1/2/3 da Visão 1 (custo final → coleta → armazenagem). Não
# recalcula nada — só reapresenta de trás pra frente os mesmos passos 1-8 já calculados.
def montar_visao_2_teardown(passo_1, passo_2, passo_3, passo_4, passo_5, passo_8, preco_final, margem_valor, margem_percentual, dec):
    def pct(valor):
        if valor is None or not preco_final:
            return None
        return (valor / preco_final) * 100

    linhas = [
        LinhaTeardown('Preço final de venda', preco_final, dec('100'), 'inicio'),
    ]

    for item in passo_5.itens:
        linhas.append(LinhaTeardown(item.label, item.valor, item.percentual, 'menos'))

    linhas.append(LinhaTeardown('Frete', passo_8.frete, pct(passo_8.frete), 'menos'))

    linhas.append(LinhaTeardown('Custo do produto', passo_1.custo_com_boni, pct(passo_1.custo_com_boni), 'menos'))
    linhas.append(LinhaTeardown('IPI (crédito da nota de entrada)', passo_1.ipi_valor, pct(passo_1.ipi_valor), 'menos'))
    linhas.append(LinhaTeardown('Frete CIF/FOB', passo_1.frete_cif_fob_valor, pct(passo_1.frete_cif_fob_valor), 'menos'))
    linhas.append(LinhaTeardown('Coleta', passo_2.resultado, pct(passo_2.resultado), 'menos'))
    linhas.append(LinhaTeardown('Armazenagem', passo_3.resultado, pct(passo_3.resultado), 'menos'))

    linhas.append(LinhaTeardown(
        'Crédito de ICMS (nota de entrada)', passo_4.credito_icms, pct(passo_4.credito_icms), 'mais',
        'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))
    linhas.append(LinhaTeardown(
        'Crédito de PIS (nota de entrada)', passo_4.credito_pis, pct(passo_4.credito_pis), 'mais',
        'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))
    linhas.append(LinhaTeardown(
        'Crédito de COFINS (nota de entrada)', passo_4.credito_cofins, pct(passo_4.credito_cofins), 'mais',
        'Crédito reduz o custo a recuperar — por isso soma de volta aqui.',
    ))

    linhas.append(LinhaTeardown(
        'Conferência: soma dos 8 itens acima', passo_4.resultado, pct(passo_4.resultado), 'checkpoint',
        'Deve bater com o FIXO da Visão 1 (Passo 4).',
    ))

    linhas.append(LinhaTeardown(
        'Rebate', passo_8.rebate, pct(passo_8.rebate), 'mais',
        'Desconto de promoção que o ML devolve — soma de volta ao preço.',
    ))

    linhas.append(LinhaTeardown('Lucro (margem valor)', margem_valor, margem_percentual, 'final'))

    return linhas