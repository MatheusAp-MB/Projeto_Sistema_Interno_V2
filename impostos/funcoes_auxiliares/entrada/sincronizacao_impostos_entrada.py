# impostos/funcoes_auxiliares/sincronizacao_impostos_entrada.py

# Função Objetivo: Grava no banco o retrato de impostos/custos de entrada
# de 1 produto, a partir do XML da nota já parseado (DadosXmlNF).
#
# Único ponto de escrita deste retrato inteiro — sempre sobrescreve o
# anterior (sem histórico) e sempre grava as 6 tabelas de imposto juntas,
# mesmo as com valor zero (nunca deixa 1 delas ausente).

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from impostos.descritores_impostos import DESCRITORES_IMPOSTOS
from impostos.models import ImpostosECustosXMLEntradaProduto
from produtos.models import Produto

if TYPE_CHECKING:
    from integracao_sysemp.servicos.dados_xml_nf import DadosXmlNF


def _converter_para_decimal(valor: float | None) -> Decimal | None:
    # Nunca Decimal(valor) direto num float — captura o valor binário
    # exato (ex: 18.100000000000001...), não o número que o XML de fato
    # informou. Decimal(str(valor)) converte pela representação textual,
    # que é a decimal correta.
    #
    # None passa direto — quem decide se None é válido pra aquele campo
    # é o próprio model (ex: quantidade_nota é nullable; um valor de
    # imposto inesperadamente None ainda falha, só que na constraint do
    # banco, não numa conversão de string que nunca deveria ser a
    # responsável por essa checagem.
    if valor is None:
        return None
    return Decimal(str(valor))


def sincronizar_impostos_entrada_do_xml(produto: Produto, dados: 'DadosXmlNF') -> ImpostosECustosXMLEntradaProduto:

    data_entrada = date.fromisoformat(dados.identificacao_nf.data_entrada_nf) \
        if dados.identificacao_nf.data_entrada_nf else None

    emissao = date.fromisoformat(dados.identificacao_nf.data_emissao_nf) \
        if dados.identificacao_nf.data_emissao_nf else None

    with transaction.atomic():
        guarda_chuva, _ = ImpostosECustosXMLEntradaProduto.objects.update_or_create(
            produto=produto,
            defaults={
                'nr_nf': dados.identificacao_nf.numero_nf,
                'data_entrada_nota': data_entrada,
                'emissao': emissao,
                'ncm_xml': dados.classificacao_fiscal.ncm_xml,
                'ncm_cadastro': dados.classificacao_fiscal.ncm_cadastro,
                'cfop_xml': dados.classificacao_fiscal.cfop_xml,
                'cfop_cadastro': dados.classificacao_fiscal.cfop_cadastro,
                'origem_mercadoria_xml': dados.classificacao_fiscal.origem_mercadoria_xml,
                'origem_mercadoria_cadastro': dados.classificacao_fiscal.origem_mercadoria_cadastro,
                'descricao_origem_mercadoria_xml': dados.classificacao_fiscal.descricao_origem_mercadoria_xml,
                'descricao_origem_mercadoria_cadastro': dados.classificacao_fiscal.descricao_origem_mercadoria_cadastro,
                'natureza_operacao_cadastro': dados.classificacao_fiscal.natureza_operacao_cadastro,
                'tes_saida_cadastro': dados.classificacao_fiscal.tes_saida_cadastro,
                'id_produto_sysemp': dados.identificacao_produto.id_produto_sysemp,
                'codigo_auxiliar': dados.identificacao_produto.codigo_auxiliar,
                'fornecedor': dados.identificacao_nf.fornecedor,
                'empresa_fantasia': dados.identificacao_nf.empresa_fantasia,
                'custo_total': _converter_para_decimal(dados.custos.total),
                'quantidade_nota': _converter_para_decimal(dados.identificacao_produto.quantidade_nota),
                'custo_unitario': _converter_para_decimal(dados.custos.unitario),
            },
        )

        # 1 volta do loop = 1 dos 6 impostos: pega o pedaço correspondente
        # dentro do XML já parseado, monta só os campos que esse imposto
        # realmente tem (segundo o descritor), e grava.
        for descritor_do_imposto in DESCRITORES_IMPOSTOS:
            dados_deste_imposto_no_xml = getattr(dados, descritor_do_imposto.nome_do_atributo_em_dados_xml)

            campos_para_gravar = {
                'base_calculo': _converter_para_decimal(dados_deste_imposto_no_xml.base_calculo),
                'valor': _converter_para_decimal(dados_deste_imposto_no_xml.valor),
            }

            if descritor_do_imposto.possui_aliquota:
                campos_para_gravar['aliquota'] = _converter_para_decimal(dados_deste_imposto_no_xml.aliquota)

            if descritor_do_imposto.possui_cst:
                campos_para_gravar['cst_xml'] = dados_deste_imposto_no_xml.cst_xml
                campos_para_gravar['cst_cadastro'] = dados_deste_imposto_no_xml.cst_cadastro

            if descritor_do_imposto.possui_reducao:
                campos_para_gravar['reducao'] = _converter_para_decimal(dados_deste_imposto_no_xml.reducao)

            if descritor_do_imposto.possui_fcp:
                campos_para_gravar['aliquota_fcp'] = _converter_para_decimal(dados_deste_imposto_no_xml.aliquota_fcp)
                campos_para_gravar['valor_fcp'] = _converter_para_decimal(dados_deste_imposto_no_xml.valor_fcp)

            descritor_do_imposto.classe_do_model_no_banco.objects.update_or_create(
                impostos_e_custos=guarda_chuva,
                defaults=campos_para_gravar,
            )

    return guarda_chuva