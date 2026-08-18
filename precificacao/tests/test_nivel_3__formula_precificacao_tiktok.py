# precificacao/tests/test_nivel_3__formula_precificacao_tiktok.py

# Função Objetivo: Nível 3 (banco real) de FormulaPrecificacaoTiktok — mesmo motor
# fiscal/custo das demais, com as diferenças exclusivas do TikTok cobertas aqui:
# frete direto por peso (sem faixa de reputação, diferente do Magalu), comissão por
# faixa de preço (resolver_preco_por_faixa_comissao, mesma função da Shopee), e
# margem de afiliado (8%) que só entra na taxa quando tipo='com_afiliado'.
# para_dict_auditoria() aqui só tem 3 seções (sem 'passos' — TikTok não implementa
# passos(), diferente de ML/Magalu/Raia).

from decimal import Decimal

import pytest

from produtos.models import Produto
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem, TabelaComissaoTiktok
from tiktok.models import ConfiguracaoTiktok, FreteTiktok
from precificacao.funcoes_auxiliares.tiktok.formula_precificacao_tiktok import FormulaPrecificacaoTiktok
from impostos.funcoes_auxiliares.sincronizacao_impostos_entrada import sincronizar_impostos_entrada_do_xml
from integracao_sysemp.servicos.dados_xml_nf import (
    ClassificacaoFiscalItem, Cofins, Custos, DadosXmlNF, Icms, IcmsRet, IcmsSt,
    IdentificacaoNF, IdentificacaoProduto, Ipi, Pis,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — FormulaPrecificacaoTiktok'

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


def _config_tiktok_padrao(**overrides) -> ConfiguracaoTiktok:
    dados = dict(margem_afiliado_percentual=Decimal('8.00'), desconto_vitrine_percentual=Decimal('20.00'))
    dados.update(overrides)
    return ConfiguracaoTiktok(**dados)


def _config_geral_padrao() -> ConfiguracaoOperacional:
    return ConfiguracaoOperacional(fator_coleta=Decimal('72.00'), periodo_armazenagem=30)


def _frete_padrao() -> list:
    return [FreteTiktok(peso_min=Decimal('0'), peso_max=Decimal('10'), valor=Decimal('20.00'))]


def _faixa_comissao_padrao(**overrides) -> list:
    dados = dict(preco_min=Decimal('0'), preco_max=None,
                 comissao_percentual=Decimal('20.00'), adicional_fixo=Decimal('0.00'))
    dados.update(overrides)
    return [TabelaComissaoTiktok(**dados)]


def test_produto_sem_icms_st_usa_credito_normal_ate_o_preco_final(tabela_resultados):
    # Setup: ICMS ST zerado — crédito normal (18.00). tipo=sem_afiliado (margem
    # de afiliado não entra na taxa).
    produto = _criar_produto('7930000000001')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: taxa = comissão 20% + ICMS saída 10% (afiliado=0) = 30%; fixo=199;
    # preço = (20+0+199)÷0,50 = 438,00 → RoundUp90 → 438,90.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.credito_icms_entrada == Decimal('18.00')
        and resultado.intermediarios.fixo == Decimal('199.00')
        and resultado.saida.frete_usado == Decimal('20.00')
        and resultado.saida.preco_final == Decimal('438.90')
    )
    registrar_resultado(
        tabela_resultados, 'sem_icms_st_credito_normal_ate_preco_final',
        'ICMS ST=0, ICMS normal=18, tipo=sem_afiliado',
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
    produto = _criar_produto('7930000000002')
    dados = _dados_xml_nf_padrao(
        icms_st=IcmsSt(base_calculo=150.0, aliquota=20.0, reducao=0.0, valor=30.0, aliquota_fcp=0.0, valor_fcp=0.0),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
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
    produto = _criar_produto('7930000000003')

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
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
    produto = _criar_produto('7930000000004')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    from impostos.models import ImpostosECustosXMLEntradaProduto
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    guarda_chuva.quantidade_nota = None
    guarda_chuva.save()
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
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
    produto = _criar_produto('7930000000005', armazenagem_planilha=None)
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
    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(), faixas_armazenagem=faixas,
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
    produto = _criar_produto('7930000000006', armazenagem_planilha=None)
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    FaixaArmazenagem.objects.create(
        nome='Grande', valor_diario=Decimal('3.00'),
        max_altura=Decimal('999'), max_largura=Decimal('999'), max_profundidade=Decimal('999'),
        ordem=1, ativo=True,
    )
    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
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


def test_frete_nao_encontrado_para_o_peso_nao_calcula_preco(tabela_resultados):
    # Setup: nenhuma faixa de frete cobre o peso do produto.
    produto = _criar_produto('7930000000007')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), frete_todas=[],
    )

    # Exercise
    resultado = formula.calcular()

    # Assert
    bateu = resultado.resolvida is False
    registrar_resultado(
        tabela_resultados, 'frete_nao_encontrado_nao_calcula',
        'frete_todas=[] (nenhuma faixa cobre o peso de 5kg)',
        'resolvida=False',
        'Sem faixa de frete pro peso do produto, a fórmula nunca finge um valor',
        f'resolvida={resultado.resolvida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_denominador_invalido_nao_calcula_preco(tabela_resultados):
    # Setup: faixa de comissão única com 85% + ICMS saída 10% + margem-alvo 10%
    # = denominador <= 0 — a faixa é pulada (continue), sem outra pra tentar.
    produto = _criar_produto('7930000000008')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('10'),
        'sem_afiliado', _faixa_comissao_padrao(comissao_percentual=Decimal('85.00')), _frete_padrao(),
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


def test_tipo_com_afiliado_soma_margem_de_afiliado_na_taxa(tabela_resultados):
    # Setup: tipo=com_afiliado — margem de afiliado (8%) entra na taxa, único
    # cenário onde isso acontece (sem_afiliado usa 0 sempre). Margem-alvo baixa
    # (2%) só pra manter os números do exemplo redondos.
    produto = _criar_produto('7930000000009')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('2'),
        'com_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: taxa = comissão 20% + ICMS saída 10% + afiliado 8% = 38%;
    # denom = 1 - 0,38 - 0,02 = 0,60; preço = (20+0+199)÷0,60 = 365,00 →
    # RoundUp90 → 365,90.
    bateu = (
        resultado.resolvida is True
        and resultado.entrada.margem_afiliado_percentual == Decimal('8.00')
        and resultado.saida.preco_final == Decimal('365.90')
    )
    registrar_resultado(
        tabela_resultados, 'tipo_com_afiliado_soma_margem_na_taxa',
        'tipo=com_afiliado, margem_afiliado=8%, comissão faixa=20%, margem-alvo=2%',
        'margem_afiliado_percentual=8.00, preço_final=365.90',
        'Margem de afiliado só entra na taxa quando tipo=com_afiliado — nunca em sem_afiliado',
        f'margem_afiliado={resultado.entrada.margem_afiliado_percentual}, preco_final={resultado.saida.preco_final}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_para_dict_auditoria_devolve_as_3_secoes(tabela_resultados):
    # Setup: mesmo cenário do 1º teste (sem ICMS ST, sem_afiliado). TikTok NÃO
    # implementa passos() — diferente de ML/Magalu/Raia, só 3 chaves aqui.
    produto = _criar_produto('7930000000010')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
    )
    resultado = formula.calcular()

    # Exercise
    dict_auditoria = resultado.para_dict_auditoria()

    # Assert
    bateu = (
        set(dict_auditoria.keys()) == {'entrada', 'intermediarios', 'saida'}
        and dict_auditoria['entrada']['sku'] == produto.sku
        and dict_auditoria['saida']['preco_final'] == Decimal('438.90')
    )
    registrar_resultado(
        tabela_resultados, 'para_dict_auditoria_3_secoes',
        'resultado já calculado (cenário sem ICMS ST, sem_afiliado)',
        'chaves={entrada,intermediarios,saida} (sem passos), preco_final=438.90',
        'TikTok não implementa passos() — para_dict_auditoria() tem só 3 chaves, diferente de ML/Magalu/Raia',
        f'chaves={set(dict_auditoria.keys())}, preco_final={dict_auditoria["saida"]["preco_final"]}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup
    produto = _criar_produto('7930000000011')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacaoTiktok(
        produto, _config_tiktok_padrao(), _config_geral_padrao(), Decimal('20'),
        'sem_afiliado', _faixa_comissao_padrao(), _frete_padrao(),
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