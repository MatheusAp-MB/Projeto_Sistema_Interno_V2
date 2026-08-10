# integracao_sysemp/servicos/tests/test_nivel_0__filtro_cfop.py

# Função Objetivo: Nível 0 (função pura, sem dependência) de
# filtrar_por_cfop() — achata nota+itens_nf em linhas e mantém só CFOP
# relevante pra custo/imposto de entrada. Ver decisão de CFOP no vault:
# "Lista de CFOP Relevantes para Precificacao".

import pytest

from integracao_sysemp.servicos.filtro_cfop import filtrar_por_cfop
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — filtro_cfop'


def _nota(nr_nf, itens):
    return {'NR NF': nr_nf, 'Fornecedor': 'Fornecedor Teste', 'itens_nf': itens}


def test_achata_nota_com_varios_itens_em_linhas_separadas(tabela_resultados):
    # Setup: 1 nota com 2 itens.
    notas = [_nota('1001', [
        {'Código Barras': '111', 'CFOP': '1.102'},
        {'Código Barras': '222', 'CFOP': '1.102'},
    ])]

    # Exercise
    resultado = filtrar_por_cfop(notas)

    # Assert
    bateu = (
        len(resultado) == 2
        and all(linha['NR NF'] == '1001' for linha in resultado)
        and {linha['Código Barras'] for linha in resultado} == {'111', '222'}
    )
    registrar_resultado(
        tabela_resultados, 'achata_nota_varios_itens',
        '1 nota, 2 itens em itens_nf', '2 linhas, cada 1 com os campos da nota + do item',
        'Achatamento não pode perder item nem misturar campos entre notas',
        f'{len(resultado)} linha(s): {resultado}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_cfop_fora_da_lista_e_descartado(tabela_resultados):
    # Setup: 1 item com CFOP que não está em CFOPS_PARA_MANTER.
    notas = [_nota('1001', [{'Código Barras': '111', 'CFOP': '1.916'}])]

    # Exercise
    resultado = filtrar_por_cfop(notas)

    # Assert
    registrar_resultado(
        tabela_resultados, 'cfop_fora_da_lista_descartado',
        'CFOP 1.916 (retorno de conserto)', '0 linhas',
        'CFOP fora da lista validada não é compra nem bonificação — não representa custo real',
        f'{len(resultado)} linha(s)', len(resultado) == 0,
    )
    assert len(resultado) == 0

    # TearDown: nada a desmontar.


def test_cfop_da_lista_e_mantido(tabela_resultados):
    # Setup: 1 item com CFOP válido.
    notas = [_nota('1001', [{'Código Barras': '111', 'CFOP': '1.102'}])]

    # Exercise
    resultado = filtrar_por_cfop(notas)

    # Assert
    registrar_resultado(
        tabela_resultados, 'cfop_da_lista_mantido',
        'CFOP 1.102 (compra para revenda)', '1 linha',
        'CFOP validado precisa passar pelo filtro sem ser descartado por engano',
        f'{len(resultado)} linha(s)', len(resultado) == 1,
    )
    assert len(resultado) == 1

    # TearDown: nada a desmontar.


def test_lista_de_notas_vazia_devolve_lista_vazia(tabela_resultados):
    # Setup: nenhuma nota.
    notas = []

    # Exercise
    resultado = filtrar_por_cfop(notas)

    # Assert
    registrar_resultado(
        tabela_resultados, 'lista_vazia_devolve_vazia',
        '[]', '[]',
        'Período sem nenhuma nota não pode quebrar o pipeline',
        f'{resultado}', resultado == [],
    )
    assert resultado == []

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup: valor esperado ERRADO de propósito.
    notas = [_nota('1001', [{'Código Barras': '111', 'CFOP': '1.102'}])]

    # Exercise
    resultado = filtrar_por_cfop(notas)

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{len(resultado)} linha(s)', '99 linhas (errado de propósito)',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{len(resultado)} linha(s)', len(resultado) == 99,
    )
    assert len(resultado) == 99

    # TearDown: nada a desmontar.