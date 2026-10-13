# impostos/tests/entrada/test_nivel_1__pis_cofins_tributo_ja_pago.py

# Função Objetivo: Nível 1 (função pura, sem banco) de
# pis_cofins_tributo_ja_pago_pelo_fornecedor() — CST de PIS/COFINS 02, 04 ou 06
# no XML do fornecedor = tributo já pago antes (0% na entrada e na saída; regra
# de Matheus, 01/10/2026). Qualquer outro CST (ou ausência dele) não dispara.

import pytest

from impostos.funcoes_auxiliares.entrada.pis_cofins_tributo_ja_pago import pis_cofins_tributo_ja_pago_pelo_fornecedor
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 1 — PIS/COFINS Tributo Já Pago (CST 02/04/06)'


@pytest.mark.parametrize('cst_xml', ['02', '04', '06'])
def test_cst_da_regra_dispara(tabela_resultados, cst_xml):
    # Setup: nada a montar — função pura.

    # Exercise
    obtido = pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_xml)

    # Assert
    bateu = obtido is True
    registrar_resultado(
        tabela_resultados, f'cst_{cst_xml}_dispara',
        f'cst_xml={cst_xml!r}', 'True',
        'CST 02, 04 e 06 são os 3 que indicam tributo já pago pelo fornecedor',
        f'{obtido}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('cst_xml', ['00', '01', '03', '05', '49', '99'])
def test_cst_fora_da_regra_nao_dispara(tabela_resultados, cst_xml):
    # Setup: nada a montar — função pura.

    # Exercise
    obtido = pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_xml)

    # Assert
    bateu = obtido is False
    registrar_resultado(
        tabela_resultados, f'cst_{cst_xml}_nao_dispara',
        f'cst_xml={cst_xml!r}', 'False',
        'Só 02/04/06 entram na regra — qualquer outro CST segue o cálculo normal',
        f'{obtido}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('cst_xml', [None, '', '   '])
def test_cst_ausente_nao_dispara(tabela_resultados, cst_xml):
    # Setup: nada a montar — função pura.

    # Exercise
    obtido = pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_xml)

    # Assert
    bateu = obtido is False
    registrar_resultado(
        tabela_resultados, f'cst_ausente_{cst_xml!r}_nao_dispara',
        f'cst_xml={cst_xml!r}', 'False',
        'Sem CST não há como afirmar que o tributo foi pago antes — nunca dispara no escuro',
        f'{obtido}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.parametrize('cst_xml, esperado', [('4', True), (' 06 ', True), ('2', True), (6, True)])
def test_formatacao_do_cst_nao_derruba_a_regra(tabela_resultados, cst_xml, esperado):
    # Setup: o CST vem como texto do XML, mas zero à esquerda perdido ("4") ou espaço
    # sobrando não pode fazer a regra errar o produto.

    # Exercise
    obtido = pis_cofins_tributo_ja_pago_pelo_fornecedor(cst_xml)

    # Assert
    bateu = obtido is esperado
    registrar_resultado(
        tabela_resultados, f'cst_formatado_{cst_xml!r}',
        f'cst_xml={cst_xml!r}', f'{esperado}',
        'Normaliza (strip + zero à esquerda) antes de comparar com 02/04/06',
        f'{obtido}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.
