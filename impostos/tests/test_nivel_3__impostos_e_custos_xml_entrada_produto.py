# impostos/tests/test_nivel_3__impostos_e_custos_xml_entrada_produto.py

# Função Objetivo: Nível 3 (banco real) de ImpostosECustosXMLEntradaProduto
# — cobre o único ponto de escrita, sincronizar_a_partir_de(): sempre
# sobrescreve (nunca duplica), sempre grava as 6 tabelas juntas (nunca
# deixa 1 de fora, mesmo zerada), e desfaz tudo se qualquer passo falhar.
# Usa DadosXmlNF real (DOC já rápido/determinístico — nunca dublê aqui, ver
# "Disciplina de Testes Automatizados" no vault).

from datetime import date
from decimal import Decimal

import pytest

from produtos.models import Produto
from impostos.models import (
    ImpostosECustosXMLEntradaProduto, IcmsEntradaProduto, IcmsStEntradaProduto,
    IcmsRetEntradaProduto, IpiEntradaProduto, PisEntradaProduto, CofinsEntradaProduto,
)
from scripts_exploracao_ERP.dados_xml_nf import (
    DadosXmlNF, IdentificacaoProduto, IdentificacaoNF, DadosNF, IdentificadorRegra,
    IcmsSt, Icms, IcmsRet, Ipi, Pis, Cofins, Custos,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 3 — ImpostosECustosXMLEntradaProduto'

pytestmark = pytest.mark.django_db


def _criar_produto(ean: str) -> Produto:
    return Produto.objects.create(ean=ean, titulo=f'Produto Teste {ean}')


def _dados_xml_nf_padrao(**overrides) -> DadosXmlNF:
    # * [EXPLICAÇÃO] → Constrói o DOC direto pelas dataclasses (não pelo
    #                  a_partir_do_registro) — testar o parsing do registro
    #                  cru não é responsabilidade deste arquivo (já
    #                  coberto, ou a cobrir, na camada de baixo).
    valores = {
        'identificacao_produto': IdentificacaoProduto(
            id_produto=1, produto='Produto Teste', codigo_barras='0000000000000',
            codigo_auxiliar='', codigo_fabricante='', qtde=1.0,
        ),
        'identificacao_nf': IdentificacaoNF(nr_nf='1001', data_entrada_nota='2026-08-01', emissao='2026-07-30'),
        'dados_nf': DadosNF(fornecedor='Fornecedor Padrao Ltda', cfop='1102', natureza_da_operacao='Compra', chave='chave-teste'),
        'identificador_regra': IdentificadorRegra(tes_saida=1, ncm='00000000', origem='0', origem_descricao='Nacional'),
        'icms_st': IcmsSt(base_calculo=0.0, aliquota=0.0, reducao=0.0, valor=0.0),
        'icms': Icms(cst=0, base_calculo=100.0, aliquota=18.1, reducao=0.0, valor=18.1),
        'icms_ret': IcmsRet(base=0.0, valor=0.0),
        'ipi': Ipi(cst=0, base_calculo=100.0, aliquota=5.0, valor=5.0),
        'pis': Pis(cst=0, base_calculo=90.0, aliquota=1.65, reducao=10.0, valor=1.5),
        'cofins': Cofins(cst=0, base_calculo=90.0, aliquota=7.6, reducao=10.0, valor=6.9),
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
        identificacao_nf=IdentificacaoNF(nr_nf='2002', data_entrada_nota='2026-08-05', emissao='2026-08-04'),
    )
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados_nova_nota)

    # Assert
    total_guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.filter(produto=produto).count()
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    bateu = total_guarda_chuva == 1 and guarda_chuva.nr_nf == '2002'
    registrar_resultado(
        tabela_resultados, 'segunda_sincronizacao_sobrescreve',
        '2ª chamada com nr_nf=2002 (1ª tinha nr_nf=1001)',
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
        identificacao_nf=IdentificacaoNF(nr_nf='1001', data_entrada_nota='2026-08-01', emissao='2026-07-30'),
    )

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    bateu = guarda_chuva.data_entrada_nota == date(2026, 8, 1)
    registrar_resultado(
        tabela_resultados, 'data_entrada_nota_string_vira_date',
        "data_entrada_nota='2026-08-01' (string)",
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
        identificacao_nf=IdentificacaoNF(nr_nf='1001', data_entrada_nota=None, emissao='2026-07-30'),
    )

    # Exercise
    ImpostosECustosXMLEntradaProduto.sincronizar_a_partir_de(produto, dados)

    # Assert
    guarda_chuva = ImpostosECustosXMLEntradaProduto.objects.get(produto=produto)
    bateu = guarda_chuva.data_entrada_nota is None
    registrar_resultado(
        tabela_resultados, 'data_entrada_nota_none_nao_quebra',
        'data_entrada_nota=None', 'None',
        'Nota sem essa data é caso real conhecido — nunca pode quebrar a sincronização',
        f'{guarda_chuva.data_entrada_nota!r}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_reducao_pis_cofins_chega_intacta(tabela_resultados):
    # Setup: reducao já vem calculada na dataclass — o pipeline só repassa.
    produto = _criar_produto('7900000000005')
    dados = _dados_xml_nf_padrao(
        pis=Pis(cst=0, base_calculo=90.0, aliquota=1.65, reducao=12.34, valor=1.5),
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
    dados = _dados_xml_nf_padrao(icms_ret=IcmsRet(base=0.0, valor=0.0))

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
    bateu = todas_existem and icms_ret.base == Decimal('0.0') and icms_ret.valor == Decimal('0.0')
    registrar_resultado(
        tabela_resultados, 'as_6_tabelas_sempre_criadas',
        'ICMS Ret zerado, resto padrão', 'as 6 existem, ICMS Ret com 0/0 (não ausente)',
        'Zero é dado real, não é "não sincronizado" — nenhuma das 6 pode ficar ausente',
        f'todas_existem={todas_existem}, icms_ret.base={icms_ret.base}',
        bateu,
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