# precificacao/tests/test_nivel_3__formula_precificacao_shopee.py

# Função Objetivo: Nível 3 (banco real) de FormulaPrecificacaoShopee — mesmo motor
# fiscal/custo das demais. É a mais simples dos 6: frete é um número fixo de
# configuração (config_shopee.frete_padrao, nunca busca por peso/faixa), e quem
# varia por faixa de preço é a comissão + adicional fixo JUNTOS (mesma função de
# busca do TikTok). Sem "tipo" (DBA/FBA, com/sem afiliado) — só 1 fluxo.
# para_dict_auditoria() aqui também só tem 3 seções (sem 'passos').

from decimal import Decimal

import pytest

from produtos.models import Produto
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem, TabelaComissaoShopee
from shopee.models import ConfiguracaoShopee
from precificacao.funcoes_auxiliares.shopee.formula_precificacao_shopee import FormulaPrecificacaoShopee
from impostos.funcoes_auxiliares.sincronizacao_impostos_entrada import sincronizar_impostos_entrada_do_xml
from integracao_sysemp.servicos.dados_xml_nf import (
    ClassificacaoFiscalItem, Cofins, Custos, DadosXmlNF, Icms, IcmsRet, IcmsSt,
    IdentificacaoNF, IdentificacaoProduto, Ipi, Pis,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — FormulaPrecificacaoShopee'

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])


def _criar_produto(ean: str, **overrides) -> Produto:
    dados = dict(
        ean=ean,
        sku=f'SKU-{ean}',
        titulo=f'Produto Teste {ean}',
        custo=Decimal('100.00'),
        icms_saida_media=Decimal('10.00'),
        pis_percentual=Decimal('0'),
        cofins_percentual=Decimal('0'),
        armazenagem_planilha=Decimal('50.00'),
        altura_ordenada_cm=Decimal('100'),
        largura_ordenada_cm=Decimal('100'),
        comprimento_ordenada_cm=Decimal('100'),
        peso_produto_apos_embalado=Decimal('5.000'),
        peso_cubado=Decimal('0'),
    )
    dados.update(overrides)
    return Produto.objects.create(**dados)


def _dados_xml_nf_padrao(**overrides) -> DadosXmlNF:
    valores = {
        'identificacao_produto': IdentificacaoProduto(
            id_produto_sysemp=1, nome_produto='Produto Teste', codigo_barras='0000000000000',
            codigo_auxiliar='', codigo_fabricante='', quantidade_nota=1.0,
        ),
        'identificacao_nf': IdentificacaoNF(
            numero_nf='1001', chave_acesso_nf='chave-teste', fornecedor='Fornecedor Padrao Ltda',
            empresa_fantasia='Empresa Padrao Fantasia',
            data_emissao_nf='2026-08-01', data_entrada_nf='2026-08-02',
        ),
        'classificacao_fiscal': ClassificacaoFiscalItem(
            natureza_operacao_cadastro='Compra', ncm_xml='00000000', ncm_cadastro='00000000',
            cfop_xml='1102', cfop_cadastro='1102',
            origem_mercadoria_xml='0', origem_mercadoria_cadastro='0',
            descricao_origem_mercadoria_xml='Nacional', descricao_origem_mercadoria_cadastro='Nacional',
            tes_saida_cadastro=1,
        ),
        'icms_st': IcmsSt(base_calculo=0.0, aliquota=0.0, reducao=0.0, valor=0.0, aliquota_fcp=0.0, valor_fcp=0.0),
        'icms': Icms(cst_xml='00', cst_cadastro='00', base_calculo=100.0, aliquota=18.0, reducao=0.0, valor=18.0),
        'icms_ret': IcmsRet(base_calculo=0.0, valor=0.0),
        'ipi': Ipi(cst_xml='50', cst_cadastro='50', base_calculo=100.0, aliquota=5.0, valor=5.0),
        'pis': Pis(cst_xml='01', cst_cadastro='01', base_calculo=100.0, aliquota=2.0, reducao=0.0, valor=2.0),
        'cofins': Cofins(cst_xml='01', cst_cadastro='01', base_calculo=100.0, aliquota=8.0, reducao=0.0, valor=8.0),
        'custos': Custos(total=100.0, unitario=100.0),
    }
    valores.update(overrides)
    return DadosXmlNF(**valores)


def _config_shopee_padrao(**overrides) -> ConfiguracaoShopee:
    dados = dict(frete_padrao=Decimal('20.00'), desconto_vitrine_percentual=Decimal('20.00'))
    dados.update(overrides)
    return ConfiguracaoShopee(**dados)


def _config_geral_padrao() -> ConfiguracaoOperacional:
    return ConfiguracaoOperacional(fator_coleta=Decimal('72.00'), periodo_armazenagem=30)


def _faixa_comissao_padrao(**overrides) -> list:
    dados = dict(preco_min=Decimal('0'), preco_max=None,
                 comissao_percentual=Decimal('20.00'), adicional_fixo=Decimal('0.00'))
    dados.update(overrides)
    return [TabelaComissaoShopee(**dados)]


def test_produto_sem_icms_st_usa_credito_normal_ate_o_preco_final(tabela_resultados):
    # Setup: ICMS ST zerado — crédito normal (18.00). Frete padrão (fixo) = 20,00.
    produto = _criar_produto('7950000000001')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: taxa = comissão 20% + ICMS saída 10% = 30%; fixo=199; preço =
    # (20+0+199)÷0,50 = 438,00 → RoundUp90 → 438,90.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.credito_icms_entrada == Decimal('18.00')
        and resultado.intermediarios.fixo == Decimal('199.00')
        and resultado.saida.frete_usado == Decimal('20.00')
        and resultado.saida.preco_final == Decimal('438.90')
    )
    registrar_resultado(
        tabela_resultados, 'sem_icms_st_credito_normal_ate_preco_final',
        'ICMS ST=0, ICMS normal=18, frete_padrao=20',
        'credito_icms=18.00, fixo=199.00, frete=20.00, preço_final=438.90',
        'Sem ST não tem diferimento — crédito normal aplica direto até o preço final',
        f'credito_icms={resultado.intermediarios.credito_icms_entrada}, '
        f'fixo={resultado.intermediarios.fixo}, preco_final={resultado.saida.preco_final}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_produto_com_icms_st_usa_credito_liquido_sem_dobrar(tabela_resultados):
    # Setup: ICMS ST com valor real (30.00) — crédito líquido = 30 - 18 = 12.
    produto = _criar_produto('7950000000002')
    dados = _dados_xml_nf_padrao(
        icms_st=IcmsSt(base_calculo=150.0, aliquota=20.0, reducao=0.0, valor=30.0, aliquota_fcp=0.0, valor_fcp=0.0),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: fixo = 72+50+105-(12+2+8) = 205; preço = (20+205)÷0,50 = 450,00 →
    # RoundUp90 → 450,90.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.credito_icms_entrada == Decimal('12.00')
        and resultado.intermediarios.fixo == Decimal('205.00')
        and resultado.saida.preco_final == Decimal('450.90')
    )
    registrar_resultado(
        tabela_resultados, 'com_icms_st_credito_liquido_sem_dobrar',
        'ICMS ST valor=30, ICMS normal valor=18',
        'credito_icms=12.00 (líquido), fixo=205.00, preço_final=450.90',
        'Diferimento: ICMS normal já absorvido dentro do líquido do ST — nunca soma os 2',
        f'credito_icms={resultado.intermediarios.credito_icms_entrada}, '
        f'fixo={resultado.intermediarios.fixo}, preco_final={resultado.saida.preco_final}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_sem_impostos_entrada_sincronizado_nao_calcula_preco(tabela_resultados):
    # Setup: produto criado, mas nunca sincronizado com impostos_entrada.
    produto = _criar_produto('7950000000003')

    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert
    bateu = (
        resultado.resolvida is False
        and resultado.entrada is None
        and resultado.saida is None
    )
    registrar_resultado(
        tabela_resultados, 'sem_impostos_entrada_nao_calcula',
        'produto sem ImpostosECustosXMLEntradaProduto',
        'resolvida=False, entrada/saida=None',
        'Sem sincronizar impostos de entrada, a fórmula nunca finge um crédito',
        f'resolvida={resultado.resolvida}, entrada={resultado.entrada}, saida={resultado.saida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_credito_incompleto_sem_quantidade_nota_nao_calcula(tabela_resultados):
    # Setup: sincroniza normalmente, depois simula produto sincronizado antes de
    # quantidade_nota existir (campo fica None no banco).
    produto = _criar_produto('7950000000004')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    from impostos.models import ImpostosECustosXMLEntradaProduto
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    guarda_chuva.quantidade_nota = None
    guarda_chuva.save()
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert
    bateu = resultado.resolvida is False
    registrar_resultado(
        tabela_resultados, 'credito_incompleto_sem_quantidade_nota',
        'quantidade_nota=None',
        'resolvida=False',
        'Sem quantidade não dá pra ratear valor por unidade — nunca finge um crédito parcial',
        f'resolvida={resultado.resolvida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_armazenagem_por_faixa_dimensao_com_lista_pronta(tabela_resultados):
    # Setup: sem armazenagem_planilha — cai na faixa por dimensão, lista já pronta.
    produto = _criar_produto('7950000000005', armazenagem_planilha=None)
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    faixas = [
        FaixaArmazenagem(nome='P', valor_diario=Decimal('1.00'),
                          max_altura=Decimal('50'), max_largura=Decimal('50'), max_profundidade=Decimal('50'),
                          ordem=1, ativo=True),
        FaixaArmazenagem(nome='M', valor_diario=Decimal('2.00'),
                          max_altura=Decimal('150'), max_largura=Decimal('150'), max_profundidade=Decimal('150'),
                          ordem=2, ativo=True),
    ]
    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(), faixas_armazenagem=faixas,
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: dimensão 100x100x100 cabe na faixa M (max 150) → 2,00 × 30 = 60,00.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.armazenagem_origem == 'faixa_dimensao'
        and resultado.intermediarios.armazenagem == Decimal('60.00')
    )
    registrar_resultado(
        tabela_resultados, 'armazenagem_faixa_lista_pronta',
        'sem armazenagem_planilha, dims 100x100x100, faixas [P max=50, M max=150]',
        'armazenagem=60.00 (faixa M: 2,00 × 30 dias)',
        'Sem planilha, usa a 1ª faixa onde todas as dimensões cabem',
        f'origem={resultado.intermediarios.armazenagem_origem}, armazenagem={resultado.intermediarios.armazenagem}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_armazenagem_por_faixa_dimensao_busca_do_banco(tabela_resultados):
    # Setup: sem armazenagem_planilha e sem lista pronta — força a busca real no banco.
    produto = _criar_produto('7950000000006', armazenagem_planilha=None)
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    FaixaArmazenagem.objects.create(
        nome='Grande', valor_diario=Decimal('3.00'),
        max_altura=Decimal('999'), max_largura=Decimal('999'), max_profundidade=Decimal('999'),
        ordem=1, ativo=True,
    )
    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: valor_diario 3,00 × periodo 30 = 90,00.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.armazenagem_origem == 'faixa_dimensao'
        and resultado.intermediarios.armazenagem == Decimal('90.00')
    )
    registrar_resultado(
        tabela_resultados, 'armazenagem_faixa_busca_do_banco',
        'sem armazenagem_planilha, sem lista pronta, 1 FaixaArmazenagem real no banco',
        'armazenagem=90.00 (3,00 × 30 dias)',
        'faixas_armazenagem=None força a busca real no banco, não só em memória',
        f'origem={resultado.intermediarios.armazenagem_origem}, armazenagem={resultado.intermediarios.armazenagem}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_denominador_invalido_nao_calcula_preco(tabela_resultados):
    # Setup: faixa de comissão única com 85% + ICMS saída 10% + margem-alvo 10%
    # = denominador <= 0 — a faixa é pulada (continue), sem outra pra tentar.
    produto = _criar_produto('7950000000007')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('10'),
        _faixa_comissao_padrao(comissao_percentual=Decimal('85.00')),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert
    bateu = resultado.resolvida is False
    registrar_resultado(
        tabela_resultados, 'denominador_invalido_nao_calcula',
        'comissão=85%, ICMS saída=10%, margem-alvo=10%',
        'resolvida=False',
        'denominador = 1 - 0,95 - 0,10 = -0,05 <= 0 — faixa pulada, sem outra candidata',
        f'resolvida={resultado.resolvida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_selecao_de_faixa_de_comissao_e_adicional_fixo_por_preco(tabela_resultados):
    # Setup: 2 faixas de preço — comissão % igual nas 2, mas adicional_fixo
    # diferente (só a Shopee soma os 2 JUNTOS por faixa) — a 1ª faixa gera um
    # preço fora do próprio teto, a busca avança pra 2ª, que já embute o
    # adicional_fixo de R$ 5,00 no numerador.
    produto = _criar_produto('7950000000008')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    faixas = [
        TabelaComissaoShopee(preco_min=Decimal('0'), preco_max=Decimal('100.00'),
                              comissao_percentual=Decimal('20.00'), adicional_fixo=Decimal('0.00')),
        TabelaComissaoShopee(preco_min=Decimal('100.01'), preco_max=None,
                              comissao_percentual=Decimal('20.00'), adicional_fixo=Decimal('5.00')),
    ]
    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'), faixas,
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: 1ª faixa geraria 438,90 — fora do próprio teto de 100,00. 2ª
    # faixa: preço = (20+5+199)÷0,50 = 448,00 → RoundUp90 → 448,90.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.adicional_fixo == Decimal('5.00')
        and resultado.saida.preco_final == Decimal('448.90')
        and resultado.intermediarios.faixa_comissao_preco_min == Decimal('100.01')
    )
    registrar_resultado(
        tabela_resultados, 'selecao_faixa_comissao_adicional_fixo_por_preco',
        '2 faixas: [R$0-100→adicional 0], [R$100,01+→adicional 5,00]',
        'adicional_fixo=5.00, preco_final=448.90, faixa_min=100.01',
        'Comissão e adicional fixo variam JUNTOS por faixa — só a Shopee faz isso',
        f'adicional_fixo={resultado.intermediarios.adicional_fixo}, preco_final={resultado.saida.preco_final}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_para_dict_auditoria_devolve_as_3_secoes(tabela_resultados):
    # Setup: mesmo cenário do 1º teste (sem ICMS ST).
    produto = _criar_produto('7950000000009')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(),
    )
    resultado = formula.calcular()

    # Exercise
    dict_auditoria = resultado.para_dict_auditoria()

    # Assert: Shopee não implementa passos() — só 3 chaves, igual TikTok/Amazon.
    bateu = (
        set(dict_auditoria.keys()) == {'entrada', 'intermediarios', 'saida'}
        and dict_auditoria['entrada']['sku'] == produto.sku
        and dict_auditoria['saida']['preco_final'] == Decimal('438.90')
    )
    registrar_resultado(
        tabela_resultados, 'para_dict_auditoria_3_secoes',
        'resultado já calculado (cenário sem ICMS ST)',
        'chaves={entrada,intermediarios,saida} (sem passos), preco_final=438.90',
        'Shopee não implementa passos() — para_dict_auditoria() tem só 3 chaves',
        f'chaves={set(dict_auditoria.keys())}, preco_final={dict_auditoria["saida"]["preco_final"]}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup
    produto = _criar_produto('7950000000010')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoShopee(
        produto, _config_shopee_padrao(), _config_geral_padrao(), Decimal('20'),
        _faixa_comissao_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: compara contra um valor errado de propósito.
    valor_errado_de_proposito = Decimal('999.99')
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{resultado.saida.preco_final}', f'{valor_errado_de_proposito}',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{resultado.saida.preco_final}', resultado.saida.preco_final == valor_errado_de_proposito,
    )
    assert resultado.saida.preco_final == valor_errado_de_proposito

    # TearDown: nada a desmontar.