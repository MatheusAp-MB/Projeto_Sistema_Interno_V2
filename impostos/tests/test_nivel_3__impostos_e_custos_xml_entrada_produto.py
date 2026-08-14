# impostos/tests/test_nivel_3__impostos_e_custos_xml_entrada_produto.py

# Função Objetivo: Nível 3 (banco real) de ImpostosECustosXMLEntradaProduto
# — cobre o único ponto de escrita, sincronizar_a_partir_de(): sempre
# sobrescreve (nunca duplica), sempre grava as 6 tabelas juntas (nunca
# deixa 1 de fora, mesmo zerada), e desfaz tudo se qualquer passo falhar.
# Usa DadosXmlNF real (DOC já rápido/determinístico — nunca dublê aqui, ver
# "Disciplina de Testes Automatizados" no vault).
#
# Atualizado (14/08/2026) pra API nova (campos em par XML/Cadastro,
# ClassificacaoFiscalItem consolidado) — 1 teste novo garante que ncm_xml e
# ncm_cadastro persistem em colunas distintas, motivado pelo quase-erro
# real que aconteceu na migração do banco.

from datetime import date
from decimal import Decimal

import pytest

from produtos.models import Produto
from impostos.models import (
    ImpostosECustosXMLEntradaProduto, IcmsEntradaProduto, IcmsStEntradaProduto,
    IcmsRetEntradaProduto, IpiEntradaProduto, PisEntradaProduto, CofinsEntradaProduto,
)
from integracao_sysemp.servicos.dados_xml_nf import (
    ClassificacaoFiscalItem, Cofins, Custos, DadosXmlNF, Icms, IcmsRet, IcmsSt,
    IdentificacaoNF, IdentificacaoProduto, Ipi, Pis,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — ImpostosECustosXMLEntradaProduto'

pytestmark = pytest.mark.django_db


def _criar_produto(ean: str) -> Produto:
    return Produto.objects.create(ean=ean, titulo=f'Produto Teste {ean}')


def _dados_xml_nf_padrao(**overrides) -> DadosXmlNF:
    # * [EXPLICAÇÃO] → Constrói o DOC direto pelas dataclasses (não pelo
    #                  a_partir_do_registro) — testar o parsing do registro
    #                  cru não é responsabilidade deste arquivo (já coberto
    #                  em test_nivel_0__dados_xml_nf.py).
    valores = {
        'identificacao_produto': IdentificacaoProduto(
            id_produto_sysemp=1, nome_produto='Produto Teste', codigo_barras='0000000000000',
            codigo_auxiliar='', codigo_fabricante='', quantidade_nota=1.0,
        ),
        'identificacao_nf': IdentificacaoNF(
            numero_nf='1001', chave_acesso_nf='chave-teste', fornecedor='Fornecedor Padrao Ltda',
            data_emissao_nf='2026-07-30', data_entrada_nf='2026-08-01',
        ),
        'classificacao_fiscal': ClassificacaoFiscalItem(
            natureza_operacao_cadastro='Compra', ncm_xml='00000000', ncm_cadastro='00000000',
            cfop_xml='1102', cfop_cadastro='1102',
            origem_mercadoria_xml='0', origem_mercadoria_cadastro='0',
            descricao_origem_mercadoria_xml='Nacional', descricao_origem_mercadoria_cadastro='Nacional',
            tes_saida_cadastro=1,
        ),
        'icms_st': IcmsSt(base_calculo=0.0, aliquota=0.0, reducao=0.0, valor=0.0),
        'icms': Icms(cst_xml=0, cst_cadastro=0, base_calculo=100.0, aliquota=18.1, reducao=0.0, valor=18.1),
        'icms_ret': IcmsRet(base_calculo=0.0, valor=0.0),
        'ipi': Ipi(cst_xml=0, cst_cadastro=0, base_calculo=100.0, aliquota=5.0, valor=5.0),
        'pis': Pis(cst_xml=0, cst_cadastro=0, base_calculo=90.0, aliquota=1.65, reducao=10.0, valor=1.5),
        'cofins': Cofins(cst_xml=0, cst_cadastro=0, base_calculo=90.0, aliquota=7.6, reducao=10.0, valor=6.9),
        'custos': Custos(total=100.0, unitario=10.0),
    }
    valores.update(overrides)
    return DadosXmlNF(**valores)


def test_primeira_sincronizacao_cria_guarda_chuva_e_as_6_tabelas(tabela_resultados):
    # Setup
    produto = _criar_produto('7900000000001')
    dados = _dados_xml_nf_padrao()

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert: relê tudo do banco antes de comparar.
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    icms = IcmsEntradaProduto.objects.get(impostos_e_custos=guarda_chuva)
    bateu = (
        guarda_chuva.nr_nf == '1001'
        and guarda_chuva.fornecedor == 'Fornecedor Padrao Ltda'
        and guarda_chuva.custo_total == Decimal('100.0')
        and icms.base_calculo == Decimal('100.0')
        and icms.aliquota == Decimal('18.1')
    )
    registrar_resultado(
        tabela_resultados, 'primeira_sincronizacao_cria_tudo',
        'DadosXmlNF padrão, produto novo',
        'guarda-chuva + ICMS criados com os valores certos',
        'Primeira sincronização precisa criar o retrato inteiro, sem faltar nada',
        f'nr_nf={guarda_chuva.nr_nf}, custo_total={guarda_chuva.custo_total}, icms.base_calculo={icms.base_calculo}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_segunda_sincronizacao_sobrescreve_nunca_duplica(tabela_resultados):
    # Setup: 1ª sincronização já aconteceu antes.
    produto = _criar_produto('7900000000002')
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, _dados_xml_nf_padrao())

    # Exercise: 2ª sincronização, nota diferente.
    dados_nova_nota = _dados_xml_nf_padrao(
        identificacao_nf=IdentificacaoNF(
            numero_nf='2002', chave_acesso_nf='chave-teste', fornecedor='Fornecedor Padrao Ltda',
            data_emissao_nf='2026-08-04', data_entrada_nf='2026-08-05',
        ),
    )
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados_nova_nota)

    # Assert
    total_guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.filter(produto=produto).count()
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    bateu = total_guarda_chuva == 1 and guarda_chuva.nr_nf == '2002'
    registrar_resultado(
        tabela_resultados, 'segunda_sincronizacao_sobrescreve',
        '2ª chamada com numero_nf=2002 (1ª tinha numero_nf=1001)',
        '1 registro só, com nr_nf=2002',
        'Sem histórico — a 2ª sincronização sobrescreve, nunca duplica',
        f'total={total_guarda_chuva}, nr_nf={guarda_chuva.nr_nf}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_data_entrada_nota_string_iso_vira_date_real(tabela_resultados):
    # Setup
    produto = _criar_produto('7900000000003')
    dados = _dados_xml_nf_padrao(
        identificacao_nf=IdentificacaoNF(
            numero_nf='1001', chave_acesso_nf='chave-teste', fornecedor='Fornecedor Padrao Ltda',
            data_emissao_nf='2026-07-30', data_entrada_nf='2026-08-01',
        ),
    )

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    bateu = guarda_chuva.data_entrada_nota == date(2026, 8, 1)
    registrar_resultado(
        tabela_resultados, 'data_entrada_nota_string_vira_date',
        "data_entrada_nf='2026-08-01' (string)",
        'date(2026, 8, 1)',
        'O dado bruto do XML vem como string — precisa virar date real no banco',
        f'{guarda_chuva.data_entrada_nota!r} ({type(guarda_chuva.data_entrada_nota).__name__})',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_data_entrada_nota_none_nao_quebra(tabela_resultados):
    # Setup: nota sem essa data (caso real já documentado no domínio).
    produto = _criar_produto('7900000000004')
    dados = _dados_xml_nf_padrao(
        identificacao_nf=IdentificacaoNF(
            numero_nf='1001', chave_acesso_nf='chave-teste', fornecedor='Fornecedor Padrao Ltda',
            data_emissao_nf='2026-07-30', data_entrada_nf=None,
        ),
    )

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    bateu = guarda_chuva.data_entrada_nota is None
    registrar_resultado(
        tabela_resultados, 'data_entrada_nota_none_nao_quebra',
        'data_entrada_nf=None', 'None',
        'Nota sem essa data é caso real conhecido — nunca pode quebrar a sincronização',
        f'{guarda_chuva.data_entrada_nota!r}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_reducao_pis_cofins_chega_intacta(tabela_resultados):
    # Setup: reducao já vem calculada na dataclass — o pipeline só repassa.
    produto = _criar_produto('7900000000005')
    dados = _dados_xml_nf_padrao(
        pis=Pis(cst_xml=0, cst_cadastro=0, base_calculo=90.0, aliquota=1.65, reducao=12.34, valor=1.5),
    )

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    pis = PisEntradaProduto.objects.get(impostos_e_custos=guarda_chuva)
    bateu = pis.reducao == Decimal('12.34')
    registrar_resultado(
        tabela_resultados, 'reducao_pis_chega_intacta',
        'Pis.reducao=12.34 (já calculada na dataclass)', 'Decimal(12.34) no banco',
        'sincronizar_a_partir_de nunca recalcula redução — só repassa o que já vem pronto',
        f'{pis.reducao}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_as_6_tabelas_sao_sempre_criadas_mesmo_icms_ret_zerado(tabela_resultados):
    # Setup: ICMS Ret zerado — caso real, nunca usado até hoje.
    produto = _criar_produto('7900000000006')
    dados = _dados_xml_nf_padrao(icms_ret=IcmsRet(base_calculo=0.0, valor=0.0))

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    todas_existem = (
        IcmsEntradaProduto.objects.filter(impostos_e_custos=guarda_chuva).exists()
        and IcmsStEntradaProduto.objects.filter(impostos_e_custos=guarda_chuva).exists()
        and IcmsRetEntradaProduto.objects.filter(impostos_e_custos=guarda_chuva).exists()
        and IpiEntradaProduto.objects.filter(impostos_e_custos=guarda_chuva).exists()
        and PisEntradaProduto.objects.filter(impostos_e_custos=guarda_chuva).exists()
        and CofinsEntradaProduto.objects.filter(impostos_e_custos=guarda_chuva).exists()
    )
    icms_ret = IcmsRetEntradaProduto.objects.get(impostos_e_custos=guarda_chuva)
    bateu = todas_existem and icms_ret.base_calculo == Decimal('0.0') and icms_ret.valor == Decimal('0.0')
    registrar_resultado(
        tabela_resultados, 'as_6_tabelas_sempre_criadas',
        'ICMS Ret zerado, resto padrão', 'as 6 existem, ICMS Ret com 0/0 (não ausente)',
        'Zero é dado real, não é "não sincronizado" — nenhuma das 6 pode ficar ausente',
        f'todas_existem={todas_existem}, icms_ret.base_calculo={icms_ret.base_calculo}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_ncm_xml_e_ncm_cadastro_persistem_distintos(tabela_resultados):
    # Setup: NCM XML e NCM Cadastro com valores diferentes de propósito —
    # mesmo risco real que quase aconteceu na migração (Django quase gravou
    # o dado do XML na coluna errada, "ncm" -> "ncm_cadastro" em vez de
    # "ncm_xml").
    produto = _criar_produto('7900000000009')
    dados = _dados_xml_nf_padrao(
        classificacao_fiscal=ClassificacaoFiscalItem(
            natureza_operacao_cadastro='Compra', ncm_xml='11111111', ncm_cadastro='22222222',
            cfop_xml='1102', cfop_cadastro='1102',
            origem_mercadoria_xml='0', origem_mercadoria_cadastro='0',
            descricao_origem_mercadoria_xml='Nacional', descricao_origem_mercadoria_cadastro='Nacional',
            tes_saida_cadastro=1,
        ),
    )

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert: relê do banco antes de comparar.
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    bateu = guarda_chuva.ncm_xml == '11111111' and guarda_chuva.ncm_cadastro == '22222222'
    registrar_resultado(
        tabela_resultados, 'ncm_xml_e_ncm_cadastro_persistem_distintos',
        'ncm_xml=11111111, ncm_cadastro=22222222 (valores diferentes)',
        'guarda-chuva grava cada um na coluna certa, sem trocar',
        'Regressão direta do quase-erro real da migração (Django quase renomeou ncm pra ncm_cadastro)',
        f'ncm_xml={guarda_chuva.ncm_xml}, ncm_cadastro={guarda_chuva.ncm_cadastro}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_falha_no_meio_desfaz_tudo_por_transacao(monkeypatch, tabela_resultados):
    # Setup: produto novo, sem nenhum retrato ainda.
    produto = _criar_produto('7900000000007')
    dados = _dados_xml_nf_padrao()

    def _levantar_erro_simulado(*args, **kwargs):
        raise RuntimeError('Falha simulada no último passo da gravação (COFINS)')

    monkeypatch.setattr(CofinsEntradaProduto.objects, 'update_or_create', _levantar_erro_simulado)

    # Exercise
    with pytest.raises(RuntimeError):
        ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert: nem o guarda-chuva nem nenhuma das 5 tabelas gravadas ANTES
    # do ponto de falha pode ter sobrado — transaction.atomic() desfaz tudo.
    nada_foi_salvo = (
        not ImpostosECustosXMLEntradaProduto.objects.filter(produto=produto).exists()
        and not IcmsEntradaProduto.objects.exists()
        and not IcmsStEntradaProduto.objects.exists()
        and not IcmsRetEntradaProduto.objects.exists()
        and not IpiEntradaProduto.objects.exists()
        and not PisEntradaProduto.objects.exists()
    )
    registrar_resultado(
        tabela_resultados, 'falha_no_meio_desfaz_tudo',
        'RuntimeError simulado no update_or_create do COFINS (último passo)',
        'nenhuma das 6 tabelas fica salva',
        'transaction.atomic() precisa desfazer TUDO se qualquer passo falhar — nunca fica pela metade',
        f'nada_foi_salvo={nada_foi_salvo}', nada_foi_salvo,
    )
    assert nada_foi_salvo

    # TearDown: nada a desmontar (monkeypatch desfaz sozinho).


def test_obter_detalhes_para_exibicao_calcula_por_unidade_e_usa_ncm_xml(tabela_resultados):
    # Setup: quantidade_nota=2.0 pra deixar a divisão "por unidade" visível
    # (diferente do valor bruto), e ncm_xml != ncm_cadastro pra confirmar
    # que a exibição usa sempre o XML (fonte única de verdade).
    produto = _criar_produto('7900000000011')
    dados = _dados_xml_nf_padrao(
        identificacao_produto=IdentificacaoProduto(
            id_produto_sysemp=1, nome_produto='Produto Teste', codigo_barras='0000000000000',
            codigo_auxiliar='', codigo_fabricante='', quantidade_nota=2.0,
        ),
        classificacao_fiscal=ClassificacaoFiscalItem(
            natureza_operacao_cadastro='Compra', ncm_xml='11111111', ncm_cadastro='22222222',
            cfop_xml='1102', cfop_cadastro='1102',
            origem_mercadoria_xml='0', origem_mercadoria_cadastro='0',
            descricao_origem_mercadoria_xml='Nacional', descricao_origem_mercadoria_cadastro='Nacional',
            tes_saida_cadastro=1,
        ),
    )
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)

    # Exercise
    detalhes = guarda_chuva.obter_detalhes_para_exibicao()
    icms = next(l for l in detalhes.linhas if l.nome == 'ICMS')
    icms_st = next(l for l in detalhes.linhas if l.nome == 'ICMS ST')
    icms_ret = next(l for l in detalhes.linhas if l.nome == 'ICMS Retido')
    ipi = next(l for l in detalhes.linhas if l.nome == 'IPI')

    # Assert
    bateu = (
        detalhes.ncm == '11111111'
        and icms.base_calculo == Decimal('50.0') and icms.valor == Decimal('9.05')
        and icms.aliquota == Decimal('18.1') and icms.cst == 0
        and icms_st.cst is None
        and icms_ret.cst is None and icms_ret.aliquota is None and icms_ret.reducao is None
        and ipi.reducao is None
    )
    registrar_resultado(
        tabela_resultados, 'detalhes_calcula_por_unidade_e_usa_ncm_xml',
        'quantidade_nota=2.0, ICMS base_calculo=100/valor=18.1, ncm_xml=11111111/ncm_cadastro=22222222',
        'ICMS base_calculo=50.0/valor=9.05 (por unidade), ncm exibido=ncm_xml, cst/aliquota/reducao ausentes onde não existem no domínio',
        'Exibição sempre divide base_calculo/valor pela quantidade (aliquota/reducao nunca dividem) e usa NCM do XML, nunca do Cadastro',
        f'ncm={detalhes.ncm}, icms=({icms.base_calculo},{icms.valor},{icms.aliquota},{icms.cst}), '
        f'icms_st.cst={icms_st.cst}, icms_ret=({icms_ret.cst},{icms_ret.aliquota},{icms_ret.reducao}), ipi.reducao={ipi.reducao}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_obter_detalhes_para_exibicao_devolve_none_quando_quantidade_ausente(tabela_resultados):
    # Setup: sincroniza normalmente, depois simula produto sincronizado
    # antes de quantidade_nota existir (campo fica None no banco).
    produto = _criar_produto('7900000000012')
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, _dados_xml_nf_padrao())
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    guarda_chuva.quantidade_nota = None
    guarda_chuva.save()
    guarda_chuva.refresh_from_db()

    # Exercise
    detalhes = guarda_chuva.obter_detalhes_para_exibicao()

    # Assert
    todos_none = all(linha.base_calculo is None and linha.valor is None for linha in detalhes.linhas)
    registrar_resultado(
        tabela_resultados, 'detalhes_quantidade_ausente_devolve_none',
        'quantidade_nota=None (produto sincronizado antes desse campo existir)',
        'base_calculo e valor None nas 6 linhas',
        '_por_unidade nunca pode estourar ZeroDivisionError/TypeError sem quantidade',
        f'{[(l.nome, l.base_calculo, l.valor) for l in detalhes.linhas]}', todos_none,
    )
    assert todos_none

    # TearDown: nada a desmontar.


@pytest.mark.parametrize(
    'model_imposto, prefixo',
    [
        (IcmsEntradaProduto, 'ICMS'),
        (IcmsStEntradaProduto, 'ICMS ST'),
        (IcmsRetEntradaProduto, 'ICMS Ret'),
        (IpiEntradaProduto, 'IPI'),
        (PisEntradaProduto, 'PIS'),
        (CofinsEntradaProduto, 'COFINS'),
    ],
    ids=['icms', 'icms_st', 'icms_ret', 'ipi', 'pis', 'cofins'],
)
def test_str_de_cada_imposto_usa_prefixo_e_guarda_chuva(model_imposto, prefixo, tabela_resultados):
    # Setup
    produto = _criar_produto('7900000000013')
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, _dados_xml_nf_padrao())
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    instancia_imposto = model_imposto.objects.get(impostos_e_custos=guarda_chuva)

    # Exercise
    resultado = str(instancia_imposto)

    # Assert
    esperado = f'{prefixo} — {guarda_chuva}'
    registrar_resultado(
        tabela_resultados, f'str_{prefixo.lower().replace(" ", "_")}',
        f'{model_imposto.__name__}', esperado,
        '__str__ de cada imposto precisa mostrar o próprio nome e o guarda-chuva a que pertence',
        resultado, resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup
    produto = _criar_produto('7900000000008')
    dados = _dados_xml_nf_padrao()

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert: compara contra um NR NF errado de propósito.
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    nr_nf_errado_de_proposito = '9999-nao-existe'
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{guarda_chuva.nr_nf}', f'{nr_nf_errado_de_proposito}',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{guarda_chuva.nr_nf}', guarda_chuva.nr_nf == nr_nf_errado_de_proposito,
    )
    assert guarda_chuva.nr_nf == nr_nf_errado_de_proposito

    # TearDown: nada a desmontar.