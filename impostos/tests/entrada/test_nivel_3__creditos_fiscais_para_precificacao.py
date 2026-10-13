# impostos/tests/entrada/test_nivel_3__creditos_fiscais_para_precificacao.py

# Função Objetivo: Nível 3 (banco real) de montar_creditos_fiscais_para_
# precificacao() — cobre a regra de diferimento do ICMS ST: produto sem
# ICMS ST usa o crédito normal; produto com ICMS ST usa o líquido (ST
# bruto − ICMS normal) NO LUGAR do crédito normal, nunca os 2 somados.

from decimal import Decimal

import pytest

from produtos.models import Produto
from impostos.models import ImpostosECustosXMLEntradaProduto
from impostos.funcoes_auxiliares.entrada.sincronizacao_impostos_entrada import sincronizar_impostos_entrada_do_xml
from impostos.funcoes_auxiliares.entrada.creditos_fiscais_para_precificacao import montar_creditos_fiscais_para_precificacao
from integracao_sysemp.servicos.dados_xml_nf import (
    ClassificacaoFiscalItem, Cofins, Custos, DadosXmlNF, Icms, IcmsRet, IcmsSt,
    IdentificacaoNF, IdentificacaoProduto, Ipi, Pis,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — Créditos Fiscais para Precificação'

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])


def _criar_produto(ean: str) -> Produto:
    return Produto.objects.create(ean=ean, titulo=f'Produto Teste {ean}')


def _dados_xml_nf_padrao(**overrides) -> DadosXmlNF:
    valores = {
        'identificacao_produto': IdentificacaoProduto(
            id_produto_sysemp=1, nome_produto='Produto Teste', codigo_barras='0000000000000',
            codigo_auxiliar='', codigo_fabricante='', quantidade_nota=1.0,
        ),
        'identificacao_nf': IdentificacaoNF(
            numero_nf='1001', chave_acesso_nf='chave-teste', fornecedor='Fornecedor Padrao Ltda',
            empresa_fantasia='Empresa Padrao Fantasia',
            data_emissao_nf='2026-07-30', data_entrada_nf='2026-08-01',
        ),
        'classificacao_fiscal': ClassificacaoFiscalItem(
            natureza_operacao_cadastro='Compra', ncm_xml='00000000', ncm_cadastro='00000000',
            cfop_xml='1102', cfop_cadastro='1102',
            origem_mercadoria_xml='0', origem_mercadoria_cadastro='0',
            descricao_origem_mercadoria_xml='Nacional', descricao_origem_mercadoria_cadastro='Nacional',
            tes_saida_cadastro=1,
        ),
        'icms_st': IcmsSt(base_calculo=0.0, aliquota=0.0, reducao=0.0, valor=0.0, aliquota_fcp=0.0, valor_fcp=0.0),
        'icms': Icms(cst_xml='00', cst_cadastro='00', base_calculo=100.0, aliquota=18.1, reducao=0.0, valor=18.1),
        'icms_ret': IcmsRet(base_calculo=0.0, valor=0.0),
        'ipi': Ipi(cst_xml='00', cst_cadastro='00', base_calculo=100.0, aliquota=5.0, valor=5.0),
        'pis': Pis(cst_xml='00', cst_cadastro='00', base_calculo=90.0, aliquota=1.65, reducao=10.0, valor=1.5),
        'cofins': Cofins(cst_xml='00', cst_cadastro='00', base_calculo=90.0, aliquota=7.6, reducao=10.0, valor=6.9),
        'custos': Custos(total=100.0, unitario=10.0),
    }
    valores.update(overrides)
    return DadosXmlNF(**valores)


def test_produto_sem_icms_st_usa_credito_normal(tabela_resultados):
    # Setup: ICMS ST zerado (padrão da fixture) — produto sem substituição
    # tributária.
    produto = _criar_produto('7900000000020')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert: icms = crédito normal (18.1), sem nenhum ajuste de ST.
    bateu = (
        creditos.icms == Decimal('18.1')
        and creditos.ipi == Decimal('5.0')
        and creditos.pis == Decimal('1.5')
        and creditos.cofins == Decimal('6.9')
    )
    registrar_resultado(
        tabela_resultados, 'sem_icms_st_usa_credito_normal',
        'ICMS ST valor=0, ICMS normal valor=18.1',
        'icms=18.1 (crédito normal, sem ajuste)',
        'Produto sem substituição tributária não tem diferimento — crédito de ICMS entrada aplica direto',
        f'icms={creditos.icms}, ipi={creditos.ipi}, pis={creditos.pis}, cofins={creditos.cofins}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_produto_com_icms_st_usa_liquido_sem_dobrar_credito(tabela_resultados):
    # Setup: ICMS ST com valor real (25.0) — produto sob substituição
    # tributária. ICMS normal continua informado na nota (18.1), mas não
    # pode ser creditado separadamente.
    produto = _criar_produto('7900000000021')
    dados = _dados_xml_nf_padrao(
        icms_st=IcmsSt(base_calculo=50.0, aliquota=18.0, reducao=0.0, valor=25.0, aliquota_fcp=0.0, valor_fcp=0.0),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert: icms = líquido (25.0 - 18.1 = 6.9) — nunca 18.1 sozinho, nem
    # 18.1 + 6.9 somados (isso creditaria o mesmo imposto 2 vezes).
    bateu = creditos.icms == Decimal('6.9')
    registrar_resultado(
        tabela_resultados, 'com_icms_st_usa_liquido',
        'ICMS ST valor=25.0, ICMS normal valor=18.1',
        'icms=6.9 (líquido: 25.0 - 18.1)',
        'Diferimento: crédito de ICMS normal já foi absorvido dentro do líquido do ST — nunca soma os 2',
        f'icms={creditos.icms}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_sem_quantidade_nota_devolve_none_em_tudo(tabela_resultados):
    # Setup: sincroniza normalmente, depois simula produto sincronizado
    # antes de quantidade_nota existir (campo fica None no banco).
    produto = _criar_produto('7900000000022')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    guarda_chuva.quantidade_nota = None
    guarda_chuva.save()
    guarda_chuva.refresh_from_db()

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert
    bateu = (
        creditos.icms is None and creditos.ipi is None
        and creditos.pis is None and creditos.cofins is None
    )
    registrar_resultado(
        tabela_resultados, 'sem_quantidade_nota_devolve_none',
        'quantidade_nota=None',
        'os 4 créditos vêm None',
        'Sem quantidade não dá pra confiar no valor por unidade — nunca finge um crédito que não existe',
        f'icms={creditos.icms}, ipi={creditos.ipi}, pis={creditos.pis}, cofins={creditos.cofins}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('cst', ['02', '04', '06'])
def test_cst_pis_cofins_tributo_ja_pago_zera_credito(tabela_resultados, cst):
    # Setup: XML do fornecedor com CST de PIS/COFINS 02/04/06 — tributo já pago antes
    # pelo fornecedor (regra de Matheus, 01/10/2026). A nota ainda traz valor de PIS (1.5) e
    # COFINS (6.9) — o zero vale "independente do que vier do fornecedor".
    produto = _criar_produto(f'79000000003{cst}')
    dados = _dados_xml_nf_padrao(
        pis=Pis(cst_xml=cst, cst_cadastro='00', base_calculo=90.0, aliquota=1.65, reducao=10.0, valor=1.5),
        cofins=Cofins(cst_xml=cst, cst_cadastro='00', base_calculo=90.0, aliquota=7.6, reducao=10.0, valor=6.9),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert: PIS e COFINS = 0; ICMS e IPI seguem o crédito normal da nota.
    bateu = (
        creditos.pis == Decimal('0') and creditos.cofins == Decimal('0')
        and creditos.icms == Decimal('18.1') and creditos.ipi == Decimal('5.0')
    )
    registrar_resultado(
        tabela_resultados, f'cst_{cst}_zera_credito_pis_cofins',
        f'CST PIS/COFINS no XML={cst}, valor PIS=1.5, valor COFINS=6.9',
        'pis=0, cofins=0 (icms=18.1 e ipi=5.0 intactos)',
        'Tributo já pago antes pelo fornecedor — não há crédito de PIS/COFINS na entrada, mesmo com valor na nota',
        f'icms={creditos.icms}, ipi={creditos.ipi}, pis={creditos.pis}, cofins={creditos.cofins}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('cst', ['01', '03', '49'])
def test_cst_pis_cofins_fora_da_regra_mantem_credito_da_nota(tabela_resultados, cst):
    # Setup: CST fora de 02/04/06 — a regra do tributo já pago NÃO pode disparar.
    produto = _criar_produto(f'79000000004{cst}')
    dados = _dados_xml_nf_padrao(
        pis=Pis(cst_xml=cst, cst_cadastro='00', base_calculo=90.0, aliquota=1.65, reducao=10.0, valor=1.5),
        cofins=Cofins(cst_xml=cst, cst_cadastro='00', base_calculo=90.0, aliquota=7.6, reducao=10.0, valor=6.9),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert
    bateu = creditos.pis == Decimal('1.5') and creditos.cofins == Decimal('6.9')
    registrar_resultado(
        tabela_resultados, f'cst_{cst}_mantem_credito_pis_cofins',
        f'CST PIS/COFINS no XML={cst}, valor PIS=1.5, valor COFINS=6.9',
        'pis=1.5, cofins=6.9 (crédito normal da nota)',
        'Só 02/04/06 zeram o crédito — qualquer outro CST segue o valor do XML',
        f'pis={creditos.pis}, cofins={creditos.cofins}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_cst_tributo_ja_pago_so_no_pis_nao_zera_cofins(tabela_resultados):
    # Setup: PIS com CST 04, COFINS com CST 00 — cada imposto olha o PRÓPRIO cst_xml.
    produto = _criar_produto('7900000000501')
    dados = _dados_xml_nf_padrao(
        pis=Pis(cst_xml='04', cst_cadastro='00', base_calculo=90.0, aliquota=1.65, reducao=10.0, valor=1.5),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert
    bateu = creditos.pis == Decimal('0') and creditos.cofins == Decimal('6.9')
    registrar_resultado(
        tabela_resultados, 'cst_tributo_ja_pago_so_no_pis',
        'CST PIS=04, CST COFINS=00 (valor COFINS=6.9)',
        'pis=0, cofins=6.9',
        'A regra é por imposto: o zero do PIS não arrasta o COFINS junto',
        f'pis={creditos.pis}, cofins={creditos.cofins}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_cst_tributo_ja_pago_zera_pis_cofins_mesmo_sem_quantidade_nota(tabela_resultados):
    # Setup: produto sincronizado antes de quantidade_nota existir (None), CST 04. Os outros
    # créditos continuam None (sem quantidade não dá pra dividir por unidade), mas o zero de
    # PIS/COFINS é regra fiscal — não depende de quantidade.
    produto = _criar_produto('7900000000502')
    dados = _dados_xml_nf_padrao(
        pis=Pis(cst_xml='04', cst_cadastro='00', base_calculo=90.0, aliquota=1.65, reducao=10.0, valor=1.5),
        cofins=Cofins(cst_xml='04', cst_cadastro='00', base_calculo=90.0, aliquota=7.6, reducao=10.0, valor=6.9),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    guarda_chuva.quantidade_nota = None
    guarda_chuva.save()
    guarda_chuva.refresh_from_db()

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert
    bateu = (
        creditos.pis == Decimal('0') and creditos.cofins == Decimal('0')
        and creditos.icms is None and creditos.ipi is None
    )
    registrar_resultado(
        tabela_resultados, 'cst_tributo_ja_pago_sem_quantidade_nota',
        'CST PIS/COFINS=04, quantidade_nota=None',
        'pis=0, cofins=0; icms e ipi None',
        'Zero por regra fiscal não precisa de quantidade; os demais créditos seguem None (dado insuficiente)',
        f'icms={creditos.icms}, ipi={creditos.ipi}, pis={creditos.pis}, cofins={creditos.cofins}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup
    produto = _criar_produto('7900000000023')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)

    # Exercise
    creditos = montar_creditos_fiscais_para_precificacao(guarda_chuva)

    # Assert: compara contra um valor errado de propósito.
    valor_errado_de_proposito = Decimal('999.99')
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{creditos.icms}', f'{valor_errado_de_proposito}',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{creditos.icms}', creditos.icms == valor_errado_de_proposito,
    )
    assert creditos.icms == valor_errado_de_proposito

    # TearDown: nada a desmontar.