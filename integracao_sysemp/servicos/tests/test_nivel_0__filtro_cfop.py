# integracao_sysemp/servicos/tests/test_nivel_0__filtro_cfop.py

# Função Objetivo: Nível 0 (função pura, sem dependência) de
# filtrar_por_cfop() — achata nota+itens_nf em linhas e mantém só CFOP
# relevante pra custo/imposto de entrada. Ver decisão de CFOP no vault:
# "Lista de CFOP Relevantes para Precificacao". Devolve (linhas, erros) —
# testes novos (15/08/2026) cobrem a bonificação removida da lista e a
# nota com itens_nf malformado que não pode mais derrubar o lote inteiro.

import pytest

from integracao_sysemp.servicos.filtro_cfop import filtrar_por_cfop
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — filtro_cfop'


def _nota(nr_nf, itens):
    return {'NR NF': nr_nf, 'Fornecedor': 'Fornecedor Teste', 'itens_nf': itens}


def test_achata_nota_com_varios_itens_em_linhas_separadas(tabela_resultados):
    # Setup: 1 nota com 2 itens.
    notas = [_nota('1001', [
        {'Código Barras': '111', 'CFOP XML': '1.102'},
        {'Código Barras': '222', 'CFOP XML': '1.102'},
    ])]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    bateu = (
        len(resultado) == 2
        and all(linha['NR NF'] == '1001' for linha in resultado)
        and {linha['Código Barras'] for linha in resultado} == {'111', '222'}
        and erros == []
    )
    registrar_resultado(
        tabela_resultados, 'achata_nota_varios_itens',
        '1 nota, 2 itens em itens_nf', '2 linhas, cada 1 com os campos da nota + do item',
        'Achatamento não pode perder item nem misturar campos entre notas',
        f'{len(resultado)} linha(s), {len(erros)} erro(s): {resultado}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_cfop_fora_da_lista_e_descartado(tabela_resultados):
    # Setup: 1 item com CFOP que não está em CFOPS_PARA_MANTER.
    notas = [_nota('1001', [{'Código Barras': '111', 'CFOP XML': '1.916'}])]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    registrar_resultado(
        tabela_resultados, 'cfop_fora_da_lista_descartado',
        'CFOP 1.916 (retorno de conserto)', '0 linhas',
        'CFOP fora da lista validada não é compra real — não representa custo real de aquisição',
        f'{len(resultado)} linha(s)', len(resultado) == 0,
    )
    assert len(resultado) == 0

    # TearDown: nada a desmontar.


def test_bonificacao_foi_removida_da_lista(tabela_resultados):
    # Setup: 1 item com CFOP de bonificação (1.910/2.910) — removido da
    # lista em 15/08/2026, ver "Bonificacao Removida do Filtro de CFOP de
    # Impostos de Entrada" no vault.
    notas = [_nota('1001', [{'Código Barras': '111', 'CFOP XML': '1.910'}])]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    registrar_resultado(
        tabela_resultados, 'bonificacao_removida_da_lista',
        'CFOP 1.910 (bonificação)', '0 linhas',
        'Bonificação não tem custo real de aquisição — não pode mais entrar em Dados Filtrados',
        f'{len(resultado)} linha(s)', len(resultado) == 0,
    )
    assert len(resultado) == 0

    # TearDown: nada a desmontar.


def test_cfop_da_lista_e_mantido(tabela_resultados):
    # Setup: 1 item com CFOP válido.
    notas = [_nota('1001', [{'Código Barras': '111', 'CFOP XML': '1.102'}])]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

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
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    bateu = resultado == [] and erros == []
    registrar_resultado(
        tabela_resultados, 'lista_vazia_devolve_vazia',
        '[]', '[]',
        'Período sem nenhuma nota não pode quebrar o pipeline',
        f'{resultado}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nota_com_itens_nf_nulo_e_pulada_sem_derrubar_as_outras(tabela_resultados):
    # Setup: bug real corrigido em 15/08/2026 — itens_nf=None (em vez de
    # lista) derrubava filtrar_por_cfop inteiro com TypeError. 1 nota
    # malformada entre 2 notas válidas.
    notas = [
        _nota('1001', [{'Código Barras': '111', 'CFOP XML': '1.102'}]),
        {'NR NF': '1002', 'Fornecedor': 'Fornecedor Teste', 'itens_nf': None},
        _nota('1003', [{'Código Barras': '333', 'CFOP XML': '1.102'}]),
    ]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    bateu = (
        len(resultado) == 2
        and {linha['NR NF'] for linha in resultado} == {'1001', '1003'}
        and len(erros) == 1
        and erros[0]['identificador'] == '1002'
    )
    registrar_resultado(
        tabela_resultados, 'nota_itens_nf_nulo_pulada',
        'NF 1001 e 1003 válidas, NF 1002 com itens_nf=None', '2 linhas (1001, 1003) + 1 erro (NF 1002)',
        'Nota malformada não pode derrubar as outras notas do mesmo lote (bug real corrigido)',
        f'{len(resultado)} linha(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nota_que_nao_e_dicionario_e_pulada_e_registrada_como_erro(tabela_resultados):
    # Setup: 1 entrada na lista de notas brutas que não é um dicionário
    # (None) — precisa ser pulada sem derrubar as notas válidas ao redor.
    notas = [
        _nota('1001', [{'Código Barras': '111', 'CFOP XML': '1.102'}]),
        None,
        _nota('1003', [{'Código Barras': '333', 'CFOP XML': '1.102'}]),
    ]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    bateu = (
        len(resultado) == 2
        and {linha['NR NF'] for linha in resultado} == {'1001', '1003'}
        and len(erros) == 1
        and erros[0]['identificador'] == 'registro de nota malformado (não é um dicionário)'
    )
    registrar_resultado(
        tabela_resultados, 'nota_nao_e_dicionario_pulada',
        'NF 1001 e 1003 válidas, 1 entrada None no meio', '2 linhas (1001, 1003) + 1 erro identificado como registro malformado',
        'Entrada que nem é um dicionário não pode derrubar as notas válidas ao redor',
        f'{len(resultado)} linha(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nota_no_formato_plano_sem_itens_nf_vira_1_linha_direto(tabela_resultados):
    # Setup: formato antigo da API (anterior à remodelagem) — a própria
    # nota já é o item, sem a chave itens_nf.
    notas = [{'Código Barras': '111', 'CFOP XML': '1.102', 'NR NF': '1001'}]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    bateu = len(resultado) == 1 and resultado[0]['Código Barras'] == '111' and erros == []
    registrar_resultado(
        tabela_resultados, 'nota_formato_plano_vira_linha_direto',
        'nota sem itens_nf (formato plano, 1 item = 1 registro)', '1 linha, a própria nota',
        'Registro histórico anterior à remodelagem da API não pode deixar de ser lido',
        f'{len(resultado)} linha(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nota_que_nao_e_dicionario_e_pulada_e_registrada_como_erro(tabela_resultados):
    # Setup: 1 entrada na lista de notas brutas que não é um dicionário
    # (None) — precisa ser pulada sem derrubar as notas válidas ao redor.
    notas = [
        _nota('1001', [{'Código Barras': '111', 'CFOP XML': '1.102'}]),
        None,
        _nota('1003', [{'Código Barras': '333', 'CFOP XML': '1.102'}]),
    ]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    bateu = (
        len(resultado) == 2
        and {linha['NR NF'] for linha in resultado} == {'1001', '1003'}
        and len(erros) == 1
        and erros[0]['identificador'] == 'registro de nota malformado (não é um dicionário)'
    )
    registrar_resultado(
        tabela_resultados, 'nota_nao_e_dicionario_pulada',
        'NF 1001 e 1003 válidas, 1 entrada None no meio', '2 linhas (1001, 1003) + 1 erro identificado como registro malformado',
        'Entrada que nem é um dicionário não pode derrubar as notas válidas ao redor',
        f'{len(resultado)} linha(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nota_no_formato_plano_sem_itens_nf_vira_1_linha_direto(tabela_resultados):
    # Setup: formato antigo da API (anterior à remodelagem) — a própria
    # nota já é o item, sem a chave itens_nf.
    notas = [{'Código Barras': '111', 'CFOP XML': '1.102', 'NR NF': '1001'}]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert
    bateu = len(resultado) == 1 and resultado[0]['Código Barras'] == '111' and erros == []
    registrar_resultado(
        tabela_resultados, 'nota_formato_plano_vira_linha_direto',
        'nota sem itens_nf (formato plano, 1 item = 1 registro)', '1 linha, a própria nota',
        'Registro histórico anterior à remodelagem da API não pode deixar de ser lido',
        f'{len(resultado)} linha(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup: valor esperado ERRADO de propósito.
    notas = [_nota('1001', [{'Código Barras': '111', 'CFOP XML': '1.102'}])]

    # Exercise
    resultado, erros = filtrar_por_cfop(notas)

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{len(resultado)} linha(s)', '99 linhas (errado de propósito)',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{len(resultado)} linha(s)', len(resultado) == 99,
    )
    assert len(resultado) == 99

    # TearDown: nada a desmontar.