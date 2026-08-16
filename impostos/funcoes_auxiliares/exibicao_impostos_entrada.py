# impostos/funcoes_auxiliares/exibicao_impostos_entrada.py

# Função Objetivo: Monta os dados de impostos de entrada de 1 produto já
# padronizados pra exibição (aba "Impostos" do modal de Produto, tela e
# planilha de Resumo de Impostos de Entrada).

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from impostos.descritores_impostos import DESCRITORES_IMPOSTOS
from impostos.funcoes_auxiliares.conversao_valores_impostos import valor_por_unidade
from impostos.models import ImpostosECustosXMLEntradaProduto


@dataclass
class LinhaImpostoEntrada:
    # Função Objetivo: 1 linha da tabela de exibição — 1 imposto.
    #
    # Nem todo imposto tem os mesmos campos (ex: ICMS Retido não tem
    # cst/alíquota/redução; IPI não tem redução; só ICMS ST tem FCP) —
    # campo ausente vem None. base_calculo e valor aqui já são POR
    # UNIDADE; os campos "_nota" e reducao_e_calculada só alimentam o
    # popover "como isso foi calculado" no modal.

    nome: str
    cst_xml: str | None
    cst_cadastro: str | None
    base_calculo: Decimal | None
    aliquota: Decimal | None
    reducao: Decimal | None
    valor: Decimal | None
    aliquota_fcp: Decimal | None
    valor_fcp: Decimal | None
    base_calculo_nota: Decimal | None
    valor_nota: Decimal | None
    valor_fcp_nota: Decimal | None
    reducao_e_calculada: bool


@dataclass
class DetalhesImpostosEntradaProduto:
    # Função Objetivo: Cabeçalho da nota + 1 linha por imposto, pronto pra
    # exibição.

    nr_nf: str
    data_entrada_nota: date | None
    emissao: date | None
    quantidade_nota: Decimal | None
    ncm_xml: str | None
    ncm_cadastro: str | None
    cfop_xml: str | None
    cfop_cadastro: str | None
    origem_mercadoria_xml: str | None
    origem_mercadoria_cadastro: str | None
    descricao_origem_mercadoria_xml: str | None
    descricao_origem_mercadoria_cadastro: str | None
    natureza_operacao_cadastro: str | None
    tes_saida_cadastro: int | None
    id_produto_sysemp: int | None
    codigo_auxiliar: str | None
    fornecedor: str
    empresa_fantasia: str | None
    custo_unitario: Decimal | None
    custo_total: Decimal
    linhas: list[LinhaImpostoEntrada]


def montar_detalhes_para_exibicao(impostos_entrada: ImpostosECustosXMLEntradaProduto) -> DetalhesImpostosEntradaProduto:
    linhas_de_impostos = []

    # 1 volta do loop = 1 dos 6 impostos: busca o registro já salvo no
    # banco (via related_name) e monta a linha só com os campos que esse
    # imposto realmente tem (segundo o descritor).
    for descritor_do_imposto in DESCRITORES_IMPOSTOS:
        imposto_ja_persistido = getattr(impostos_entrada, descritor_do_imposto.nome_do_related_name_no_banco)
        quantidade_nota = impostos_entrada.quantidade_nota

        linhas_de_impostos.append(LinhaImpostoEntrada(
            nome=descritor_do_imposto.nome_para_exibicao,
            cst_xml=imposto_ja_persistido.cst_xml if descritor_do_imposto.possui_cst else None,
            cst_cadastro=imposto_ja_persistido.cst_cadastro if descritor_do_imposto.possui_cst else None,
            base_calculo=valor_por_unidade(imposto_ja_persistido.base_calculo, quantidade_nota),
            aliquota=imposto_ja_persistido.aliquota if descritor_do_imposto.possui_aliquota else None,
            reducao=imposto_ja_persistido.reducao if descritor_do_imposto.possui_reducao else None,
            valor=valor_por_unidade(imposto_ja_persistido.valor, quantidade_nota),
            aliquota_fcp=imposto_ja_persistido.aliquota_fcp if descritor_do_imposto.possui_fcp else None,
            valor_fcp=valor_por_unidade(imposto_ja_persistido.valor_fcp, quantidade_nota) if descritor_do_imposto.possui_fcp else None,
            base_calculo_nota=imposto_ja_persistido.base_calculo,
            valor_nota=imposto_ja_persistido.valor,
            valor_fcp_nota=imposto_ja_persistido.valor_fcp if descritor_do_imposto.possui_fcp else None,
            reducao_e_calculada=descritor_do_imposto.a_reducao_e_calculada_no_sistema,
        ))

    return DetalhesImpostosEntradaProduto(
        nr_nf=impostos_entrada.nr_nf,
        data_entrada_nota=impostos_entrada.data_entrada_nota,
        emissao=impostos_entrada.emissao,
        quantidade_nota=impostos_entrada.quantidade_nota,
        ncm_xml=impostos_entrada.ncm_xml,
        ncm_cadastro=impostos_entrada.ncm_cadastro,
        cfop_xml=impostos_entrada.cfop_xml,
        cfop_cadastro=impostos_entrada.cfop_cadastro,
        origem_mercadoria_xml=impostos_entrada.origem_mercadoria_xml,
        origem_mercadoria_cadastro=impostos_entrada.origem_mercadoria_cadastro,
        descricao_origem_mercadoria_xml=impostos_entrada.descricao_origem_mercadoria_xml,
        descricao_origem_mercadoria_cadastro=impostos_entrada.descricao_origem_mercadoria_cadastro,
        natureza_operacao_cadastro=impostos_entrada.natureza_operacao_cadastro,
        tes_saida_cadastro=impostos_entrada.tes_saida_cadastro,
        id_produto_sysemp=impostos_entrada.id_produto_sysemp,
        codigo_auxiliar=impostos_entrada.codigo_auxiliar,
        fornecedor=impostos_entrada.fornecedor,
        empresa_fantasia=impostos_entrada.empresa_fantasia,
        custo_unitario=impostos_entrada.custo_unitario,
        custo_total=impostos_entrada.custo_total,
        linhas=linhas_de_impostos,
    )