# precificacao/tests/test_nivel_3__formula_precificacao_ml.py

# Função Objetivo: Nível 3 (banco real) de FormulaPrecificacao (Mercado Livre) —
# mesmo motor fiscal/custo das demais (obter_creditos_fiscais, calcular_custo_final,
# calcular_coleta, calcular_armazenagem, calcular_fixo), com as 3 diferenças
# exclusivas do ML cobertas aqui: DimensoesEfetivas recebida pronta (não resolvida
# dentro da classe), frete por matriz peso×preço (resolver_preco_por_margem, com
# busca de faixa que respeita o preço final calculado) e rebate opcional.

from decimal import Decimal

import pytest

from produtos.models import Produto
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import DimensoesEfetivas, OrigemDimensao
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao
from impostos.funcoes_auxiliares.sincronizacao_impostos_entrada import sincronizar_impostos_entrada_do_xml
from integracao_sysemp.servicos.dados_xml_nf import (
    ClassificacaoFiscalItem, Cofins, Custos, DadosXmlNF, Icms, IcmsRet, IcmsSt,
    IdentificacaoNF, IdentificacaoProduto, Ipi, Pis,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — FormulaPrecificacao (Mercado Livre)'

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
    )
    dados.update(overrides)
    return Produto.objects.create(**dados)


def _dim_padrao(**overrides) -> DimensoesEfetivas:
    dados = dict(
        altura=Decimal('100'), largura=Decimal('100'), comprimento=Decimal('100'),
        peso=Decimal('5.000'), origem=OrigemDimensao.PRODUTO_ERP,
    )
    dados.update(overrides)
    return DimensoesEfetivas(**dados)


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


def _config_tipo_padrao(**overrides) -> ConfiguracaoTipoAnuncioMercadoLivre:
    dados = dict(
        tipo_anuncio=TipoDeAnuncioMercadoLivre.TipoAnuncio.CLASSICO,
        comissao=Decimal('20.00'),
        margem_minima=Decimal('10.00'), margem_padrao=Decimal('20.00'),
        margem_maxima=Decimal('30.00'), margem_competicao=Decimal('5.00'),
    )
    dados.update(overrides)
    return ConfiguracaoTipoAnuncioMercadoLivre(**dados)


def _config_geral_padrao() -> ConfiguracaoOperacional:
    return ConfiguracaoOperacional(fator_coleta=Decimal('72.00'), periodo_armazenagem=30)


def _frete_flat_padrao() -> list:
    # Faixa única, sem limite de peso nem de preço — cobre qualquer cenário simples.
    return [FreteML(peso_min=Decimal('0'), peso_max=Decimal('10'),
                     preco_min=Decimal('0'), preco_max=None, valor=Decimal('20.00'))]


def test_produto_sem_icms_st_usa_credito_normal_ate_o_preco_final(tabela_resultados):
    # Setup: ICMS ST zerado — crédito normal (18.00). Faixa de frete única, sem
    # limite de preço — a busca de faixa acerta de primeira.
    produto = _criar_produto('7920000000001')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: fixo = 72+50+105-(18+2+8) = 199; preço = (20+199)÷0,50 = 438,00 →
    # RoundUp90 → 438,90.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.credito_icms_entrada == Decimal('18.00')
        and resultado.intermediarios.fixo == Decimal('199.00')
        and resultado.saida.frete_usado == Decimal('20.00')
        and resultado.saida.preco_final == Decimal('438.90')
    )
    registrar_resultado(
        tabela_resultados, 'sem_icms_st_credito_normal_ate_preco_final',
        'ICMS ST=0, ICMS normal=18, faixa de frete única sem limite de preço',
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
    produto = _criar_produto('7920000000002')
    dados = _dados_xml_nf_padrao(
        icms_st=IcmsSt(base_calculo=150.0, aliquota=20.0, reducao=0.0, valor=30.0, aliquota_fcp=0.0, valor_fcp=0.0),
    )
    sincronizar_impostos_entrada_do_xml(produto, dados)
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
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
    produto = _criar_produto('7920000000003')

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
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
    produto = _criar_produto('7920000000004')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    from impostos.models import ImpostosECustosXMLEntradaProduto
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    guarda_chuva.quantidade_nota = None
    guarda_chuva.save()
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
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
    produto = _criar_produto('7920000000005', armazenagem_planilha=None)
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
    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(), faixas_armazenagem=faixas,
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
    produto = _criar_produto('7920000000006', armazenagem_planilha=None)
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    FaixaArmazenagem.objects.create(
        nome='Grande', valor_diario=Decimal('3.00'),
        max_altura=Decimal('999'), max_largura=Decimal('999'), max_profundidade=Decimal('999'),
        ordem=1, ativo=True,
    )
    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
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
    produto = _criar_produto('7920000000007')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), frete_todas=[],
    )

    # Exercise
    resultado = formula.calcular()

    # Assert
    bateu = resultado.resolvida is False
    registrar_resultado(
        tabela_resultados, 'frete_nao_encontrado_nao_calcula',
        'frete_todas=[] (nenhuma faixa cobre o peso de 5kg)',
        'resolvida=False',
        'Sem faixa candidata, resolver_preco_por_margem nunca finge um frete',
        f'resolvida={resultado.resolvida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_denominador_invalido_nao_calcula_preco(tabela_resultados):
    # Setup: comissão 85% + ICMS saída 10% + margem-alvo 10% = denominador <= 0.
    produto = _criar_produto('7920000000008')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    config_tipo = _config_tipo_padrao(comissao=Decimal('85.00'))
    formula = FormulaPrecificacao(
        produto, _dim_padrao(), config_tipo, _config_geral_padrao(),
        Decimal('10'), _frete_flat_padrao(),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: 1 - 0,95 - 0,10 = -0,05 <= 0 — verificado ANTES de testar qualquer
    # faixa (checagem global, diferente da comissão por faixa de preço).
    bateu = resultado.resolvida is False
    registrar_resultado(
        tabela_resultados, 'denominador_invalido_nao_calcula',
        'comissão=85%, ICMS saída=10%, margem-alvo=10%',
        'resolvida=False',
        'denominador = 1 - 0,95 - 0,10 = -0,05 <= 0 — meta inatingível',
        f'resolvida={resultado.resolvida}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_selecao_de_faixa_de_frete_pelo_preco_calculado(tabela_resultados):
    # Setup: 2 faixas de frete com o MESMO peso, faixas de PREÇO diferentes —
    # a 1ª (mais barata) gera um preço que não cabe no seu próprio teto, então
    # a busca precisa cair pra 2ª faixa (mecânica exclusiva do ML — matriz
    # peso × preço, nenhum outro marketplace faz essa busca em 2 dimensões).
    produto = _criar_produto('7920000000009')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    frete_todas = [
        FreteML(peso_min=Decimal('0'), peso_max=Decimal('10'),
                preco_min=Decimal('0'), preco_max=Decimal('100.00'), valor=Decimal('10.00')),
        FreteML(peso_min=Decimal('0'), peso_max=Decimal('10'),
                preco_min=Decimal('100.01'), preco_max=None, valor=Decimal('25.00')),
    ]
    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), frete_todas,
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: 1ª faixa (frete 10,00) geraria 418,90 — não cabe no teto de 100,00
    # dela mesma. 2ª faixa (frete 25,00) gera 448,90 — cabe no piso 100,01 dela.
    bateu = (
        resultado.resolvida is True
        and resultado.saida.frete_usado == Decimal('25.00')
        and resultado.saida.preco_final == Decimal('448.90')
        and resultado.intermediarios.faixa_frete_preco_min == Decimal('100.01')
    )
    registrar_resultado(
        tabela_resultados, 'selecao_faixa_frete_pelo_preco_calculado',
        '2 faixas mesmo peso: [R$0-100→frete 10], [R$100,01+→frete 25]',
        'frete_usado=25.00, preco_final=448.90, faixa_min=100.01',
        'Faixa mais barata gera preço fora do próprio teto — busca avança pra próxima',
        f'frete={resultado.saida.frete_usado}, preco_final={resultado.saida.preco_final}, '
        f'faixa_min={resultado.intermediarios.faixa_frete_preco_min}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_rebate_reduz_o_numerador_antes_de_dividir(tabela_resultados):
    # Setup: rebate 5% sobre um preço original de R$ 500,00 = R$ 25,00 de
    # crédito no numerador — nunca cria circularidade nova (depende do preço
    # ORIGINAL, já conhecido, nunca do preço sendo resolvido agora).
    produto = _criar_produto('7920000000010')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
        rebate_percentual=Decimal('5.00'), preco_original=Decimal('500.00'),
    )

    # Exercise
    resultado = formula.calcular()

    # Assert: rebate_valor = 500,00 × 5% = 25,00; preço = (20+199-25)÷0,50 =
    # 388,00 → RoundUp90 → 388,90.
    bateu = (
        resultado.resolvida is True
        and resultado.intermediarios.rebate_valor == Decimal('25.00')
        and resultado.saida.preco_final == Decimal('388.90')
    )
    registrar_resultado(
        tabela_resultados, 'rebate_reduz_numerador_antes_de_dividir',
        'rebate=5%, preço_original=500,00',
        'rebate_valor=25.00, preço_final=388.90',
        'Rebate é crédito no numerador — depende só do preço original, não do preço sendo resolvido',
        f'rebate_valor={resultado.intermediarios.rebate_valor}, preco_final={resultado.saida.preco_final}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_para_dict_auditoria_devolve_as_3_secoes(tabela_resultados):
    # Setup: mesmo cenário do 1º teste (sem ICMS ST).
    produto = _criar_produto('7920000000011')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
    )
    resultado = formula.calcular()

    # Exercise
    dict_auditoria = resultado.para_dict_auditoria()

    # Assert
    bateu = (
        set(dict_auditoria.keys()) == {'entrada', 'intermediarios', 'saida', 'passos'}
        and dict_auditoria['entrada']['sku'] == produto.sku
        and dict_auditoria['saida']['preco_final'] == Decimal('438.90')
        and len(dict_auditoria['passos']) == 10
    )
    registrar_resultado(
        tabela_resultados, 'para_dict_auditoria_3_secoes',
        'resultado já calculado (cenário sem ICMS ST)',
        'chaves={entrada,intermediarios,saida,passos}, 10 passos, preco_final=438.90',
        'para_dict_auditoria() precisa devolver tudo pronto pro JSONField do modal',
        f'chaves={set(dict_auditoria.keys())}, passos={len(dict_auditoria["passos"])}, '
        f'preco_final={dict_auditoria["saida"]["preco_final"]}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_formula_abstrata_e_preenchida_devolvem_texto_pronto_pro_modal(tabela_resultados):
    # Setup: mesmo cenário do 1º teste (sem ICMS ST, sem rebate) — valores já
    # validados numericamente antes; aqui só a formatação de texto.
    produto = _criar_produto('7920000000013')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
    )
    resultado = formula.calcular()

    # Exercise
    abstrata = resultado.formula_abstrata()
    preenchida = resultado.formula_preenchida()

    # Assert: sem rebate, rebate_valor é o literal Decimal('0') — aparece
    # como "0" no texto, não "0.00" (mesmo comportamento real do código).
    esperado_preenchida = 'preço = (R$ 20.00 + R$ 199.00 − R$ 0) ÷ 0.50 = R$ 438.90'
    bateu = (
        abstrata == 'preço = (frete + FIXO − rebate) ÷ (1 − taxa − margem-alvo)'
        and preenchida == esperado_preenchida
    )
    registrar_resultado(
        tabela_resultados, 'formula_abstrata_e_preenchida',
        'resultado já calculado (cenário sem ICMS ST, sem rebate)',
        f'abstrata=texto fixo, preenchida="{esperado_preenchida}"',
        'Textos usados direto no modal de auditoria — nunca recalculados fora da fórmula',
        f'abstrata="{abstrata}", preenchida="{preenchida}"',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup
    produto = _criar_produto('7920000000012')
    sincronizar_impostos_entrada_do_xml(produto, _dados_xml_nf_padrao())
    produto = Produto.objects.get(pk=produto.pk)

    formula = FormulaPrecificacao(
        produto, _dim_padrao(), _config_tipo_padrao(), _config_geral_padrao(),
        Decimal('20'), _frete_flat_padrao(),
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