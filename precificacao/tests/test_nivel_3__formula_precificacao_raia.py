# precificacao/tests/test_nivel_3__formula_precificacao_raia.py

# Função Objetivo: Nível 3 (banco real) de FormulaPrecificacaoRaia — cobre
# o motor fiscal/custo compartilhado com as outras 5 fórmulas de
# marketplace (créditos → custo final → coleta → armazenagem → FIXO),
# migrado hoje pra consumir impostos_entrada em vez dos campos legados do
# Produto. Escolhida como piloto por ser a mais simples (frete e comissão
# fixos, sem faixa nenhuma) — os cenários fiscais valem igual pras outras
# 5, só muda a config de frete/comissão de cada uma.
#
# Números escolhidos de propósito pra dar resultado exato e conferível à
# mão (sem porcentagem "feia"): comissão=20%, ICMS saída=10%, PIS/COFINS
# de saída=0% (zerados aqui só pra isolar o que mudou — a composição da
# taxa de saída não é o foco deste arquivo), margem-alvo=20% — denominador
# fecha em 0,50 exato.

from decimal import Decimal

import pytest

from produtos.models import Produto
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from raia.models import ConfiguracaoRaia
from precificacao.funcoes_auxiliares.raia.formula_precificacao_raia import FormulaPrecificacaoRaia
from impostos.funcoes_auxiliares.sincronizacao_impostos_entrada import sincronizar_impostos_entrada_do_xml
from integracao_sysemp.servicos.dados_xml_nf import (
    ClassificacaoFiscalItem, Cofins, Custos, DadosXmlNF, Icms, IcmsRet, IcmsSt,
    IdentificacaoNF, IdentificacaoProduto, Ipi, Pis,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — FormulaPrecificacaoRaia'

pytestmark = pytest.mark.django_db


def _criar_produto(ean: str, **overrides) -> Produto:
    valores = dict(
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
    )
    valores.update(overrides)
    return Produto.objects.create(**valores)


def _dados_xml_nf_padrao(**overrides) -> DadosXmlNF:
    # * [EXPLICAÇÃO] → Constrói o DOC direto pelas dataclasses (mesmo
    #                  padrão do teste de impostos) — parsing do registro
    #                  cru não é responsabilidade deste arquivo.
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
        'icms': Icms(cst_xml='00', cst_cadastro='00', base_calculo=100.0, aliquota=18.0, reducao=0.0, valor=18.0),
        'icms_ret': IcmsRet(base_calculo=0.0, valor=0.0),
        'ipi': Ipi(cst_xml='00', cst_cadastro='00', base_calculo=100.0, aliquota=5.0, valor=5.0),
        'pis': Pis(cst_xml='00', cst_cadastro='00', base_calculo=100.0, aliquota=2.0, reducao=0.0, valor=2.0),
        'cofins': Cofins(cst_xml='00', cst_cadastro='00', base_calculo=100.0, aliquota=8.0, reducao=0.0, valor=8.0),
        'custos': Custos(total=100.0, unitario=100.0),
    }
    valores.update(overrides)
    return DadosXmlNF(**valores)


def _config_padrao():
    config_raia = ConfiguracaoRaia.objects.create(comissao_percentual=Decimal('20.00'), frete_fixo=Decimal('24.00'))
    config_geral = ConfiguracaoOperacional.objects.create(fator_coleta=Decimal('72.00'), periodo_armazenagem=30)
    return config_raia, config_geral


def _config_padrao_com_comissao(comissao_percentual: Decimal):
    config_raia = ConfiguracaoRaia.objects.create(comissao_percentual=comissao_percentual, frete_fixo=Decimal('24.00'))
    config_geral = ConfiguracaoOperacional.objects.create(fator_coleta=Decimal('72.00'), periodo_armazenagem=30)
    return config_raia, config_geral


# ===================================================================
# Sem ICMS ST — crédito de ICMS entrada é o valor normal da nota, sem
# nenhum ajuste. Prova que o motor migrado (créditos já resolvidos, IPI
# já em R$ pronto) chega no mesmo preço que a conta manual.
# ===================================================================

def test_produto_sem_icms_st_usa_credito_normal_ate_o_preco_final(tabela_resultados):
    # Setup
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000101')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)  # relê do banco antes de usar

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=[],
    ).calcular()

    # Assert
    i = formula.intermediarios
    s = formula.saida
    bateu = (
        formula.resolvida
        and i.credito_icms_entrada == Decimal('18.00')
        and i.custo_final == Decimal('105.00')
        and i.fixo == Decimal('199.00')
        and s.preco_final == Decimal('446.90')
    )
    registrar_resultado(
        tabela_resultados, 'raia_sem_icms_st_credito_normal',
        'ICMS=18, ICMS ST=0, IPI=5, PIS=2, COFINS=8, qtd_nota=1',
        'credito_icms=18 (normal), custo_final=105, fixo=199, preco_final=446.90',
        'Sem substituição tributária, o crédito de ICMS entrada é o valor normal da nota, sem ajuste',
        f'credito_icms={i.credito_icms_entrada}, custo_final={i.custo_final}, fixo={i.fixo}, preco_final={s.preco_final}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# Com ICMS ST — crédito de ICMS entrada tem que ser o LÍQUIDO (ICMS ST −
# ICMS normal), nunca os dois somados. Este é o cenário de maior risco
# (bug já corrigido no dublê) — prova que o diferimento chega inteiro
# até o preço final na fórmula real da Raia.
# ===================================================================

def test_produto_com_icms_st_usa_credito_liquido_sem_dobrar(tabela_resultados):
    # Setup
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000102')
    dados = _dados_xml_nf_padrao(
        icms_st=IcmsSt(base_calculo=150.0, aliquota=20.0, reducao=0.0, valor=30.0, aliquota_fcp=0.0, valor_fcp=0.0),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    produto = Produto.objects.get(pk=produto.pk)

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=[],
    ).calcular()

    # Assert
    i = formula.intermediarios
    s = formula.saida
    bateu = (
        formula.resolvida
        and i.credito_icms_entrada == Decimal('12.00')  # 30 (ST) - 18 (normal), nunca 18+12
        and i.custo_final == Decimal('105.00')
        and i.fixo == Decimal('205.00')
        and s.preco_final == Decimal('458.90')
    )
    registrar_resultado(
        tabela_resultados, 'raia_com_icms_st_credito_liquido',
        'ICMS=18, ICMS ST=30, IPI=5, PIS=2, COFINS=8, qtd_nota=1',
        'credito_icms=12 (líquido), custo_final=105, fixo=205, preco_final=458.90',
        'Produto ST: crédito de ICMS entrada é o líquido do ST — dar o normal E o ST creditaria o mesmo imposto 2x',
        f'credito_icms={i.credito_icms_entrada}, custo_final={i.custo_final}, fixo={i.fixo}, preco_final={s.preco_final}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# Sem impostos_entrada sincronizado — decisão "sem fallback": produto
# nunca precifica com dado antigo/incompleto, mesmo silenciosamente.
# ===================================================================

def test_sem_impostos_entrada_sincronizado_nao_calcula_preco(tabela_resultados):
    # Setup: produto criado, mas sem nenhuma nota de entrada vinculada.
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000103')

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=[],
    ).calcular()

    # Assert
    bateu = (
        formula.resolvida is False
        and formula.entrada is None
        and formula.intermediarios is None
        and formula.saida is None
    )
    registrar_resultado(
        tabela_resultados, 'raia_sem_impostos_entrada_nao_calcula',
        'Produto sem nenhum ImpostosECustosXMLEntradaProduto vinculado',
        'resolvida=False, entrada/intermediarios/saida=None',
        'Sem fallback — sem impostos_entrada, o produto nunca precifica com dado antigo',
        f'resolvida={formula.resolvida}, entrada={formula.entrada}, intermediarios={formula.intermediarios}, saida={formula.saida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# Crédito incompleto — nota sincronizada, mas sem quantidade_nota. Sem
# ela, nenhum dos 4 créditos consegue virar valor por unidade — mesma
# decisão de "sem fallback", só que o gatilho é outro (dado incompleto,
# não ausência total da nota).
# ===================================================================

def test_credito_incompleto_sem_quantidade_nota_nao_calcula(tabela_resultados):
    # Setup
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000104')
    dados = _dados_xml_nf_padrao(
        identificacao_produto=IdentificacaoProduto(
            id_produto_sysemp=1, nome_produto='Produto Teste', codigo_barras='0000000000000',
            codigo_auxiliar='', codigo_fabricante='', quantidade_nota=None,
        ),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    produto = Produto.objects.get(pk=produto.pk)

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=[],
    ).calcular()

    # Assert
    bateu = formula.resolvida is False and formula.intermediarios is None
    registrar_resultado(
        tabela_resultados, 'raia_credito_incompleto_sem_quantidade_nota',
        'impostos_entrada sincronizado, mas quantidade_nota=None',
        'resolvida=False, nenhum crédito calculado',
        'Sem quantidade_nota nenhum dos 4 créditos vira valor por unidade — sem fallback, mesmo com nota sincronizada',
        f'resolvida={formula.resolvida}, intermediarios={formula.intermediarios}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# Armazenagem por faixa de dimensão — os 2 sub-caminhos de quando
# armazenagem_planilha não existe: lista já carregada em memória (uso
# em lote) e busca direta no banco (uso individual).
# ===================================================================

def test_armazenagem_por_faixa_dimensao_com_lista_pronta(tabela_resultados):
    # Setup: sem armazenagem_planilha, faixa passada pronta (sem tocar o banco).
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000105', armazenagem_planilha=None)
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)
    faixa = FaixaArmazenagem(
        nome='Faixa Teste', valor_diario=Decimal('2.00'),
        max_altura=Decimal('200'), max_largura=Decimal('200'), max_profundidade=Decimal('200'),
        ordem=1, ativo=True,
    )

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=[faixa],
    ).calcular()

    # Assert
    i = formula.intermediarios
    bateu = (
        formula.resolvida
        and i.armazenagem_origem == 'faixa_dimensao'
        and i.armazenagem == Decimal('60.00')  # 2,00 (valor_diario) × 30 (periodo_armazenagem)
    )
    registrar_resultado(
        tabela_resultados, 'raia_armazenagem_faixa_lista_pronta',
        'armazenagem_planilha=None, faixas_armazenagem=[faixa 200cm/R$2,00]',
        'armazenagem_origem=faixa_dimensao, armazenagem=60.00',
        'Uso em lote passa a lista já carregada — nunca deveria bater no banco de novo por produto',
        f'origem={i.armazenagem_origem}, armazenagem={i.armazenagem}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_armazenagem_por_faixa_dimensao_busca_do_banco(tabela_resultados):
    # Setup: sem armazenagem_planilha e SEM lista pronta — força a busca real no banco.
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000106', armazenagem_planilha=None)
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)
    FaixaArmazenagem.objects.create(
        nome='Faixa Banco', valor_diario=Decimal('3.00'),
        max_altura=Decimal('200'), max_largura=Decimal('200'), max_profundidade=Decimal('200'),
        ordem=1, ativo=True,
    )

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=None,
    ).calcular()

    # Assert
    i = formula.intermediarios
    bateu = (
        formula.resolvida
        and i.armazenagem_origem == 'faixa_dimensao'
        and i.armazenagem == Decimal('90.00')  # 3,00 (valor_diario) × 30 (periodo_armazenagem)
    )
    registrar_resultado(
        tabela_resultados, 'raia_armazenagem_faixa_busca_banco',
        'armazenagem_planilha=None, faixas_armazenagem=None (1 faixa ativa real no banco)',
        'armazenagem_origem=faixa_dimensao, armazenagem=90.00',
        'Uso individual (tela) busca a faixa ativa direto do banco quando ninguém pré-carregou a lista',
        f'origem={i.armazenagem_origem}, armazenagem={i.armazenagem}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# Denominador inválido — comissão + ICMS saída + margem-alvo somando
# 100% ou mais não tem preço matemático possível. Prova que a fórmula
# devolve resolvida=False em vez de dividir por zero ou número negativo.
# ===================================================================

def test_denominador_invalido_nao_calcula_preco(tabela_resultados):
    # Setup: 85% comissão + 10% ICMS saída + 10% margem-alvo = 105%.
    config_raia, config_geral = _config_padrao_com_comissao(Decimal('85.00'))
    produto = _criar_produto('7900000000107')  # icms_saida_media=10 (padrão)
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=10, faixas_armazenagem=[],
    ).calcular()

    # Assert
    bateu = formula.resolvida is False and formula.saida is None
    registrar_resultado(
        tabela_resultados, 'raia_denominador_invalido',
        'comissão=85%, ICMS saída=10%, margem-alvo=10% (soma 105%)',
        'resolvida=False, saida=None',
        'Denominador (1 − taxa − margem-alvo) ficou ≤ 0 — sem preço matematicamente possível',
        f'resolvida={formula.resolvida}, saida={formula.saida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# para_dict_auditoria — devolve as 3 seções já serializadas, prontas
# pro JSONField. Reaproveita o cenário sem ICMS ST já validado acima.
# ===================================================================

def test_para_dict_auditoria_devolve_as_3_secoes(tabela_resultados):
    # Setup
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000108')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=[],
    ).calcular()

    # Exercise
    auditoria = formula.para_dict_auditoria()

    # Assert
    bateu = (
        set(auditoria.keys()) == {'entrada', 'intermediarios', 'saida'}
        and auditoria['intermediarios']['fixo'] == Decimal('199.00')
        and auditoria['saida']['preco_final'] == Decimal('446.90')
    )
    registrar_resultado(
        tabela_resultados, 'raia_para_dict_auditoria',
        'Mesmo cenário sem ICMS ST, já validado',
        "3 chaves ('entrada'/'intermediarios'/'saida'), fixo=199.00, preco_final=446.90",
        'para_dict_auditoria só serializa o que a fórmula já calculou — nunca recalcula nada',
        f'chaves={set(auditoria.keys())}, fixo={auditoria["intermediarios"]["fixo"]}, preco_final={auditoria["saida"]["preco_final"]}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


# ===================================================================
# Caso de falha proposital — obrigatório, nunca removido. Prova que a
# tabela mostra FALHOU corretamente e que o pytest distingue falha
# esperada (xfailed) de falha real (failed).
# ===================================================================

@pytest.mark.xfail(reason='Falha de propósito — prova visual de como fica a linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup: mesmo cenário sem ICMS ST, com valor esperado ERRADO de propósito.
    config_raia, config_geral = _config_padrao()
    produto = _criar_produto('7900000000199')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    # Exercise
    formula = FormulaPrecificacaoRaia(
        produto=produto, config_raia=config_raia, config_geral=config_geral,
        margem_alvo_percentual=20, faixas_armazenagem=[],
    ).calcular()

    # Assert: preço real é R$ 446,90 — R$ 999,99 é errado de propósito.
    esperado_errado = Decimal('999.99')
    obtido = formula.saida.preco_final
    registrar_resultado(
        tabela_resultados, 'raia_caso_de_falha_proposital',
        'Mesmo cenário do teste sem ICMS ST',
        f'{esperado_errado} (errado de propósito)',
        'Propositalmente errado — preço real é R$ 446,90, nunca R$ 999,99. Prova que a tabela mostra FALHOU corretamente.',
        f'{obtido}',
        obtido == esperado_errado,
    )
    assert obtido == esperado_errado

    # TearDown: nada a desmontar.