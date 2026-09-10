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


@dataclass
class PassoDenominador:
    taxa_percentual: object
    margem_alvo_percentual: object
    resultado: object


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
    )
    passo_6 = PassoDenominador(
        taxa_percentual=dec(i.get('taxa_percentual')), margem_alvo_percentual=dec(e.get('margem_alvo_percentual')),
        resultado=dec(i.get('denominador')),
    )
    return passo_1, passo_2, passo_3, passo_4, passo_5, passo_6


# Função Objetivo: Monta o bloco de saída (5 linhas) — comum a qualquer marketplace.
def montar_saida(i, s, dec):
    return [
        LinhaSaida('Preço exato', dec(i.get('preco_exato_antes_arredondar')), 'reais'),
        LinhaSaida('Margem exata', dec(s.get('margem_exata_percentual')), 'percentual'),
        LinhaSaida('Preço final (arredondado pra ,90)', dec(s.get('preco_final')), 'reais', destaque=True),
        LinhaSaida('Margem final', dec(s.get('margem_percentual_obtida')), 'percentual', destaque=True),
        LinhaSaida('Custo de frete final', dec(s.get('frete_usado')), 'reais'),
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
        if sem_custo and