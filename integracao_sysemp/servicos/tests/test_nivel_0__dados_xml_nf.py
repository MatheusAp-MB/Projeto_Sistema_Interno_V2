# integracao_sysemp/servicos/tests/test_nivel_0__dados_xml_nf.py

# Função Objetivo: Nível 0 (dataclasses puras, sem dependência) de
# dados_xml_nf — cobre a decisão do usuário (10/08/2026): campo de IMPOSTO
# que vem null da API vira 0 explicitamente (_float_ou_zero/_int_ou_zero),
# nunca estoura float(None)/int(None) nem propaga null pro resto do
# pipeline. Custo Total/Unitário e Qtde ficam de fora de propósito — não
# usam esse tratamento, null ali é caso mais grave, não deve ser mascarado.
#
# Atualizado (14/08/2026) pra API nova (campos em par XML/Cadastro) — 2
# testes novos garantem que o parser nunca troca um lado pelo outro
# (ClassificacaoFiscalItem e o CST de 1 imposto), motivados pelo quase-erro
# real que aconteceu na migração do banco (Django quase renomeou "ncm" pra
# "ncm_cadastro" em vez de "ncm_xml").

import pytest

from integracao_sysemp.servicos.dados_xml_nf import (
    ClassificacaoFiscalItem, Cofins, DadosXmlNF, Icms, IcmsRet, IcmsSt, Ipi, Pis,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — dados_xml_nf'


def _registro_icms(overrides=None):
    base = {
        'CST ICMS': 0, 'CST ICMS Cadastro': 0, 'Base Calculo ICMS': 100.0,
        'Aliquota ICMS': 18.0, 'Redução ICMS': 0.0, 'Valor ICMS': 18.0,
    }
    base.update(overrides or {})
    return base


def _registro_icms_st(overrides=None):
    base = {
        'Base Calculo ICMS ST': 100.0, 'Aliquota ICMS ST': 18.0,
        'Redução ICMS ST': 0.0, 'Valor ICMS ST': 18.0,
    }
    base.update(overrides or {})
    return base


def _registro_icms_ret(overrides=None):
    base = {'Base ICMS Ret': 100.0, 'Valor ICMS Ret': 10.0}
    base.update(overrides or {})
    return base


def _registro_ipi(overrides=None):
    base = {
        'CST IPI': 0, 'CST IPI Cadastro': 0, 'Base Calculo IPI': 100.0,
        'Aliquota IPI': 5.0, 'Valor IPI': 5.0,
    }
    base.update(overrides or {})
    return base


def _registro_pis(overrides=None):
    base = {
        'CST PIS': 0, 'CST PIS Cadastro': 0, 'Base Calculo PIS': 100.0,
        'Aliquota PIS': 1.65, 'Valor PIS': 1.65,
    }
    base.update(overrides or {})
    return base


def _registro_cofins(overrides=None):
    base = {
        'CST COFINS': 0, 'CST COFINS Cadastro': 0, 'Base Calculo COFINS': 100.0,
        'Aliquota COFINS': 7.6, 'Valor COFINS': 7.6,
    }
    base.update(overrides or {})
    return base


def _registro_completo(overrides=None):
    # * [EXPLICAÇÃO] → registro cru completo, com todos os campos que
    #                  DadosXmlNF.a_partir_do_registro() precisa — usado nos
    #                  cenários de ponta a ponta e nos 2 testes de não
    #                  confusão XML×Cadastro.
    base = {
        'ID Produto': 1, 'Produto': 'Produto Teste', 'Código Barras': '7900000000000',
        'Código Auxiliar': 'AUX-1', 'Código Fabricante': 'FAB-1', 'Qtde': 10.0,
        'NR NF': '1001', 'Entrada NF': '2026-08-01', 'Emissão': '2026-07-31',
        'Fornecedor': 'Fornecedor Teste', 'Chave': 'CHAVE-TESTE',
        'CFOP XML': '1.102', 'CFOP Cadastro': '1.102',
        'Natureza da Operacao Cadastro': 'Compra para revenda',
        'TES Saida Cadastro': 1,
        'NCM XML': '12345678', 'NCM Cadastro': '12345678',
        'Origem XML': '0', 'Origem Cadastro': '0',
        'Origem Descrição XML': 'Nacional', 'Origem Descrição Cadastro': 'Nacional',
        'Custo Total': 1000.0, 'Custo Unitário': 100.0,
        **_registro_icms_st(), **_registro_icms(), **_registro_icms_ret(),
        **_registro_ipi(), **_registro_pis(), **_registro_cofins(),
    }
    base.update(overrides or {})
    return base


def test_registro_sem_nenhum_null_mantem_comportamento_original(tabela_resultados):
    # Setup: registro completo, nenhum campo null — comportamento anterior
    # à decisão do null->0 precisa continuar idêntico.
    registro = _registro_completo()

    # Exercise
    dados = DadosXmlNF.a_partir_do_registro(registro)

    # Assert
    bateu = (
        dados.icms.valor == 18.0 and dados.icms_st.valor == 18.0
        and dados.ipi.valor == 5.0 and dados.pis.valor == 1.65
        and dados.cofins.valor == 7.6 and dados.icms_ret.valor == 10.0
    )
    registrar_resultado(
        tabela_resultados, 'registro_sem_null_comportamento_original',
        'registro completo, nenhum imposto null', 'valores exatos do registro, sem zerar nada',
        'null->0 não pode alterar o caminho normal (sem null nenhum)',
        f'icms={dados.icms.valor}, icms_st={dados.icms_st.valor}, ipi={dados.ipi.valor}, '
        f'pis={dados.pis.valor}, cofins={dados.cofins.valor}, icms_ret={dados.icms_ret.valor}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_icms_com_campos_null_vira_zero(tabela_resultados):
    # Setup: os 6 campos de ICMS vêm null (mesmo padrão real do achado no
    # vault — imposto vem incompleto da Sysemp).
    registro = _registro_icms({
        'CST ICMS': None, 'CST ICMS Cadastro': None, 'Base Calculo ICMS': None,
        'Aliquota ICMS': None, 'Redução ICMS': None, 'Valor ICMS': None,
    })

    # Exercise
    icms = Icms.a_partir_do_registro(registro)

    # Assert
    bateu = (
        icms.cst_xml, icms.cst_cadastro, icms.base_calculo, icms.aliquota, icms.reducao, icms.valor
    ) == (0, 0, 0.0, 0.0, 0.0, 0.0)
    registrar_resultado(
        tabela_resultados, 'icms_campos_null_vira_zero',
        '6 campos de ICMS (cst_xml/cst_cadastro/base/aliquota/reducao/valor) null', 'todos 0/0.0, sem exceção',
        'Imposto incompleto da origem não pode estourar float(None)/int(None)',
        f'{(icms.cst_xml, icms.cst_cadastro, icms.base_calculo, icms.aliquota, icms.reducao, icms.valor)}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_icms_st_com_campos_null_vira_zero(tabela_resultados):
    # Setup: os 4 campos de ICMS ST vêm null.
    registro = _registro_icms_st({
        'Base Calculo ICMS ST': None, 'Aliquota ICMS ST': None,
        'Redução ICMS ST': None, 'Valor ICMS ST': None,
    })

    # Exercise
    icms_st = IcmsSt.a_partir_do_registro(registro)

    # Assert
    bateu = (icms_st.base_calculo, icms_st.aliquota, icms_st.reducao, icms_st.valor) == (0.0, 0.0, 0.0, 0.0)
    registrar_resultado(
        tabela_resultados, 'icms_st_campos_null_vira_zero',
        '4 campos de ICMS ST (base/aliquota/reducao/valor) null', 'todos 0.0, sem exceção',
        'Imposto incompleto da origem não pode estourar float(None)',
        f'{(icms_st.base_calculo, icms_st.aliquota, icms_st.reducao, icms_st.valor)}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_icms_ret_com_campos_null_vira_zero(tabela_resultados):
    # Setup: os 2 campos de ICMS Ret vêm null.
    registro = _registro_icms_ret({'Base ICMS Ret': None, 'Valor ICMS Ret': None})

    # Exercise
    icms_ret = IcmsRet.a_partir_do_registro(registro)

    # Assert
    bateu = (icms_ret.base_calculo, icms_ret.valor) == (0.0, 0.0)
    registrar_resultado(
        tabela_resultados, 'icms_ret_campos_null_vira_zero',
        '2 campos de ICMS Ret (base_calculo/valor) null', 'ambos 0.0, sem exceção',
        'Imposto incompleto da origem não pode estourar float(None)',
        f'{(icms_ret.base_calculo, icms_ret.valor)}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_ipi_com_campos_null_vira_zero(tabela_resultados):
    # Setup: os 5 campos de IPI vêm null.
    registro = _registro_ipi({
        'CST IPI': None, 'CST IPI Cadastro': None, 'Base Calculo IPI': None,
        'Aliquota IPI': None, 'Valor IPI': None,
    })

    # Exercise
    ipi = Ipi.a_partir_do_registro(registro)

    # Assert
    bateu = (ipi.cst_xml, ipi.cst_cadastro, ipi.base_calculo, ipi.aliquota, ipi.valor) == (0, 0, 0.0, 0.0, 0.0)
    registrar_resultado(
        tabela_resultados, 'ipi_campos_null_vira_zero',
        '5 campos de IPI (cst_xml/cst_cadastro/base/aliquota/valor) null', 'todos 0/0.0, sem exceção',
        'Imposto incompleto da origem não pode estourar float(None)/int(None)',
        f'{(ipi.cst_xml, ipi.cst_cadastro, ipi.base_calculo, ipi.aliquota, ipi.valor)}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_pis_com_base_calculo_null_zera_e_reducao_fica_100(tabela_resultados):
    # Setup: PIS com todos os campos null, inclusive Base Calculo PIS (que
    # alimenta o cálculo de reducao) — custo_total real (não null, decisão
    # separada, mais grave).
    registro = _registro_pis({
        'CST PIS': None, 'CST PIS Cadastro': None, 'Base Calculo PIS': None,
        'Aliquota PIS': None, 'Valor PIS': None,
    })

    # Exercise
    pis = Pis.a_partir_do_registro(registro, custo_total=1000.0)

    # Assert: base zerada -> reducao = (1 - 0/1000)*100 = 100.0, sem exceção.
    bateu = (
        pis.cst_xml, pis.cst_cadastro, pis.base_calculo, pis.aliquota, pis.reducao, pis.valor
    ) == (0, 0, 0.0, 0.0, 100.0, 0.0)
    registrar_resultado(
        tabela_resultados, 'pis_base_null_zera_e_reducao_100',
        '5 campos de PIS null (inclusive Base Calculo)', 'cst_xml/cst_cadastro/base/aliquota/valor=0, reducao=100.0',
        'Base zerada precisa fluir pela fórmula de redução normalmente, sem tratamento especial',
        f'{(pis.cst_xml, pis.cst_cadastro, pis.base_calculo, pis.aliquota, pis.reducao, pis.valor)}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_cofins_com_base_calculo_null_zera_e_reducao_fica_100(tabela_resultados):
    # Setup: mesmo cenário do PIS, pra COFINS.
    registro = _registro_cofins({
        'CST COFINS': None, 'CST COFINS Cadastro': None, 'Base Calculo COFINS': None,
        'Aliquota COFINS': None, 'Valor COFINS': None,
    })

    # Exercise
    cofins = Cofins.a_partir_do_registro(registro, custo_total=1000.0)

    # Assert
    bateu = (
        cofins.cst_xml, cofins.cst_cadastro, cofins.base_calculo, cofins.aliquota, cofins.reducao, cofins.valor
    ) == (0, 0, 0.0, 0.0, 100.0, 0.0)
    registrar_resultado(
        tabela_resultados, 'cofins_base_null_zera_e_reducao_100',
        '5 campos de COFINS null (inclusive Base Calculo)', 'cst_xml/cst_cadastro/base/aliquota/valor=0, reducao=100.0',
        'Base zerada precisa fluir pela fórmula de redução normalmente, sem tratamento especial',
        f'{(cofins.cst_xml, cofins.cst_cadastro, cofins.base_calculo, cofins.aliquota, cofins.reducao, cofins.valor)}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_classificacao_fiscal_item_nao_confunde_xml_com_cadastro(tabela_resultados):
    # Setup: cada par XML/Cadastro com valor DIFERENTE dos 2 lados — se o
    # parser trocar um pelo outro (mesmo risco que quase aconteceu de
    # verdade na migração do banco), este teste pega na hora.
    registro = _registro_completo({
        'NCM XML': '11111111', 'NCM Cadastro': '22222222',
        'CFOP XML': '1.102', 'CFOP Cadastro': '5.102',
        'Origem XML': '0', 'Origem Cadastro': '1',
        'Origem Descrição XML': 'Nacional', 'Origem Descrição Cadastro': 'Nacional, adquirida no exterior',
        'TES Saida Cadastro': 7,
        'Natureza da Operacao Cadastro': 'Venda de mercadoria',
    })

    # Exercise
    classificacao = ClassificacaoFiscalItem.a_partir_do_registro(registro)

    # Assert
    bateu = (
        classificacao.ncm_xml == '11111111' and classificacao.ncm_cadastro == '22222222'
        and classificacao.cfop_xml == '1.102' and classificacao.cfop_cadastro == '5.102'
        and classificacao.origem_mercadoria_xml == '0' and classificacao.origem_mercadoria_cadastro == '1'
        and classificacao.descricao_origem_mercadoria_xml == 'Nacional'
        and classificacao.descricao_origem_mercadoria_cadastro == 'Nacional, adquirida no exterior'
        and classificacao.tes_saida_cadastro == 7
        and classificacao.natureza_operacao_cadastro == 'Venda de mercadoria'
    )
    registrar_resultado(
        tabela_resultados, 'classificacao_fiscal_nao_confunde_xml_cadastro',
        'NCM/CFOP/Origem/Origem Descrição com valores diferentes em XML e Cadastro',
        'cada valor cai no atributo correspondente, sem trocar',
        'Risco real — API entrega os 2 lados juntos, troca silenciosa não gera erro, só dado errado',
        f'ncm=({classificacao.ncm_xml}, {classificacao.ncm_cadastro}), '
        f'cfop=({classificacao.cfop_xml}, {classificacao.cfop_cadastro})',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_icms_cst_xml_e_cst_cadastro_nao_se_confundem(tabela_resultados):
    # Setup: CST XML e CST Cadastro com valores diferentes de propósito —
    # mesmo risco do teste acima, agora pro CST de 1 imposto.
    registro = _registro_icms({'CST ICMS': 0, 'CST ICMS Cadastro': 60})

    # Exercise
    icms = Icms.a_partir_do_registro(registro)

    # Assert
    bateu = icms.cst_xml == 0 and icms.cst_cadastro == 60
    registrar_resultado(
        tabela_resultados, 'icms_cst_xml_e_cadastro_nao_se_confundem',
        'CST ICMS=0 (XML), CST ICMS Cadastro=60', 'cst_xml=0, cst_cadastro=60',
        'Mesmo risco do NCM — CST vem em par, troca silenciosa não gera erro, só dado errado',
        f'cst_xml={icms.cst_xml}, cst_cadastro={icms.cst_cadastro}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_dados_xml_nf_completo_com_todos_os_impostos_null(tabela_resultados):
    # Setup: caso real documentado no vault (EAN 7909436946186, NF 188419)
    # — TODOS os campos de TODOS os 6 impostos vêm null ao mesmo tempo,
    # mas Custo Total/Unitário continuam reais (não são afetados pela
    # decisão do null->0).
    registro = _registro_completo({
        'CST ICMS': None, 'CST ICMS Cadastro': None, 'Base Calculo ICMS': None,
        'Aliquota ICMS': None, 'Redução ICMS': None, 'Valor ICMS': None,
        'Base Calculo ICMS ST': None, 'Aliquota ICMS ST': None,
        'Redução ICMS ST': None, 'Valor ICMS ST': None,
        'Base ICMS Ret': None, 'Valor ICMS Ret': None,
        'CST IPI': None, 'CST IPI Cadastro': None, 'Base Calculo IPI': None,
        'Aliquota IPI': None, 'Valor IPI': None,
        'CST PIS': None, 'CST PIS Cadastro': None, 'Base Calculo PIS': None,
        'Aliquota PIS': None, 'Valor PIS': None,
        'CST COFINS': None, 'CST COFINS Cadastro': None, 'Base Calculo COFINS': None,
        'Aliquota COFINS': None, 'Valor COFINS': None,
    })

    # Exercise
    dados = DadosXmlNF.a_partir_do_registro(registro)

    # Assert: monta sem exceção, os 6 impostos saem zerados, e o custo
    # (fora do escopo desta decisão) continua real.
    todos_zerados = (
        dados.icms.valor == 0.0 and dados.icms_st.valor == 0.0 and dados.icms_ret.valor == 0.0
        and dados.ipi.valor == 0.0 and dados.pis.valor == 0.0 and dados.cofins.valor == 0.0
    )
    bateu = todos_zerados and dados.custos.total == 1000.0
    registrar_resultado(
        tabela_resultados, 'dados_xml_nf_todos_impostos_null',
        'nota real com os 6 impostos null (caso do vault), custo real presente',
        '6 impostos zerados, DadosXmlNF monta sem exceção, custo intacto',
        'Reproduz o achado real (320 produtos com esse padrão na 1ª rodada) sem travar o pipeline',
        f'impostos zerados={todos_zerados}, custo_total={dados.custos.total}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup: valor esperado ERRADO de propósito.
    icms = Icms.a_partir_do_registro(_registro_icms({'Valor ICMS': None}))

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{icms.valor}', '99.0 (errado de propósito)',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{icms.valor}', icms.valor == 99.0,
    )
    assert icms.valor == 99.0

    # TearDown: nada a desmontar.