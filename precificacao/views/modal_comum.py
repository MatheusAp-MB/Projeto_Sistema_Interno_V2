# precificacao/views/modal_comum.py

# Função Objetivo: Dataclasses de exibição do modal de auditoria — puro formato, sem
# nenhuma lógica de marketplace embutida. Reaproveitadas pelos modais de TODOS os
# marketplaces (ML, Magalu, e os que vierem depois).

from dataclasses import dataclass


@dataclass
class LinhaPercentualValor:
    label: str
    percentual: object
    valor: object


@dataclass
class LinhaValorUnico:
    label: str
    valor: object


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


@dataclass
class PassoCustoFinal:
    custo_com_boni: object
    ipi_valor: object
    frete_cif_fob_valor: object
    st_valor: object
    resultado: object


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


@dataclass
class PassoFixo:
    coleta: object
    armazenagem: object
    custo_final: object
    credito_icms: object
    credito_pis: object
    resultado: object


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


# Função Objetivo: Monta a tabela dos 6 percentuais com par direto em R$ — comum a qualquer marketplace.
def montar_tabela_percentuais(e, i, dec, label_comissao='Comissão'):
    return [
        LinhaPercentualValor('IPI', dec(e.get('ipi_percentual')), dec(i.get('ipi_valor'))),
        LinhaPercentualValor('Frete CIF/FOB', dec(e.get('frete_cif_fob_percentual')), dec(i.get('frete_cif_fob_valor'))),
        LinhaPercentualValor('ICMS entrada', dec(e.get('icms_entrada_percentual')), dec(i.get('credito_icms_entrada'))),
        LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor'))),
        LinhaPercentualValor(label_comissao, dec(e.get('comissao_percentual')), dec(i.get('comissao_valor'))),
        LinhaPercentualValor('Margem-alvo', dec(e.get('margem_alvo_percentual')), dec(i.get('margem_alvo_valor'))),
    ]


# Função Objetivo: Monta o bloco de PIS/COFINS (2 usos, bases diferentes) — comum.
def montar_pis_cofins(e, i, dec):
    return BlocoPisCofins(
        percentual=dec(e.get('pis_cofins_percentual')),
        credito_entrada=dec(i.get('credito_pis')),
        taxa_saida=dec(i.get('pis_cofins_valor')),
    )


# Função Objetivo: Monta a lista de valores soltos (custo, ST, fator de coleta...) — comum.
def montar_valores_soltos(e, dec):
    return [
        LinhaValorUnico('Custo do produto', dec(e.get('custo'))),
        LinhaValorUnico('Custo com bonificação', dec(e.get('custo_com_boni'))),
        LinhaValorUnico('Substituição tributária (ST)', dec(e.get('st_valor'))),
        LinhaValorUnico('Fator de coleta', dec(e.get('fator_coleta'))),
        LinhaValorUnico('Período de armazenagem (dias)', dec(e.get('periodo_armazenagem'))),
    ]


# Função Objetivo: Monta a dimensão usada — comum, só a origem_label varia por chamador.
def montar_dimensao(e, dec, origem_label):
    return DimensaoUsada(
        origem_label=origem_label,
        altura=dec(e.get('altura')), largura=dec(e.get('largura')),
        comprimento=dec(e.get('comprimento')), peso=dec(e.get('peso')),
    )


# Função Objetivo: Monta os passos 1-6 (custo final até denominador) — IDÊNTICOS entre
# marketplaces. Passos 7/8 (frete + preço exato) ficam por conta de quem chama, já que
# o significado da faixa (preço vs peso) e a existência de rebate diferem por canal.
def montar_passos_1_a_6(e, i, dec, label_comissao='Comissão'):
    passo_1 = PassoCustoFinal(
        custo_com_boni=dec(e.get('custo_com_boni')), ipi_valor=dec(i.get('ipi_valor')),
        frete_cif_fob_valor=dec(i.get('frete_cif_fob_valor')), st_valor=dec(e.get('st_valor')),
        resultado=dec(i.get('custo_final')),
    )
    passo_2 = PassoColeta(
        metro_cubico=dec(i.get('metro_cubico')), fator_coleta=dec(e.get('fator_coleta')),
        resultado=dec(i.get('coleta')),
    )
    passo_3 = PassoArmazenagem(
        origem=i.get('armazenagem_origem'), periodo_dias=dec(e.get('periodo_armazenagem')),
        resultado=dec(i.get('armazenagem')),
    )
    passo_4 = PassoFixo(
        coleta=dec(i.get('coleta')), armazenagem=dec(i.get('armazenagem')),
        custo_final=dec(i.get('custo_final')), credito_icms=dec(i.get('credito_icms_entrada')),
        credito_pis=dec(i.get('credito_pis')), resultado=dec(i.get('fixo')),
    )
    passo_5 = PassoTaxa(
        itens=[
            LinhaPercentualValor(label_comissao, dec(e.get('comissao_percentual')), dec(i.get('comissao_valor'))),
            LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor'))),
            LinhaPercentualValor('PIS/COFINS (saída)', dec(e.get('pis_cofins_percentual')), dec(i.get('pis_cofins_valor'))),
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