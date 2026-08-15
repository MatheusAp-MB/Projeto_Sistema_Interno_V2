# integracao_sysemp/servicos/tests/test_nivel_0__selecao_nota_recente.py

# Função Objetivo: Nível 0 (função pura, sem dependência) de
# selecionar_nota_mais_recente_por_produto() — 1 linha por Código Barras,
# a mais recente (Data Entrada da Nota desc, NR NF desc como desempate).
# Devolve (selecionados, erros) — testes novos (15/08/2026) cobrem o bug
# em que a 1ª nota de cada produto nunca era validada (curto-circuito do
# "or" na comparação) e os casos de data/NF/Código Barras malformados.

import pytest

from integracao_sysemp.servicos.selecao_nota_recente import selecionar_nota_mais_recente_por_produto
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — selecao_nota_recente'


def _linha(codigo_barras, nr_nf, data_entrada_nota):
    return {'Código Barras': codigo_barras, 'NR NF': nr_nf, 'Entrada NF': data_entrada_nota}


def test_mantem_so_a_nota_mais_recente_por_produto(tabela_resultados):
    # Setup: mesmo produto, 2 notas com datas diferentes.
    linhas = [
        _linha('111', '1001', '2026-01-01'),
        _linha('111', '1002', '2026-06-01'),
    ]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = len(resultado) == 1 and resultado[0]['NR NF'] == '1002' and erros == []
    registrar_resultado(
        tabela_resultados, 'mantem_nota_mais_recente',
        'NF 1001 (2026-01-01) e NF 1002 (2026-06-01), mesmo produto', 'só NF 1002',
        'Data mais recente vence — a antiga não pode sobrar no resultado',
        f'{[l["NR NF"] for l in resultado]}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_mesma_data_desempata_por_maior_nf(tabela_resultados):
    # Setup: mesmo produto, mesma data, NF diferente.
    linhas = [
        _linha('111', '1001', '2026-06-01'),
        _linha('111', '1005', '2026-06-01'),
    ]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = len(resultado) == 1 and resultado[0]['NR NF'] == '1005'
    registrar_resultado(
        tabela_resultados, 'mesma_data_desempata_maior_nf',
        'NF 1001 e NF 1005, mesma data 2026-06-01', 'só NF 1005',
        'Empate de data resolve pelo maior número de NF',
        f'{[l["NR NF"] for l in resultado]}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_produtos_diferentes_aparecem_separados(tabela_resultados):
    # Setup: 2 produtos diferentes, 1 nota cada.
    linhas = [
        _linha('111', '1001', '2026-01-01'),
        _linha('222', '2002', '2026-01-01'),
    ]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = {l['Código Barras'] for l in resultado} == {'111', '222'} and len(resultado) == 2
    registrar_resultado(
        tabela_resultados, 'produtos_diferentes_separados',
        '2 produtos distintos, 1 nota cada', '2 linhas no resultado, 1 por produto',
        'Produto diferente não pode se misturar nem sumir do resultado',
        f'{[l["Código Barras"] for l in resultado]}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_data_entrada_nota_ausente_perde_para_data_real(tabela_resultados):
    # Setup: mesmo produto, 1 linha sem Data Entrada da Nota (None), outra
    # com data real.
    linhas = [
        _linha('111', '1001', None),
        _linha('111', '1002', '2026-01-01'),
    ]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = len(resultado) == 1 and resultado[0]['NR NF'] == '1002'
    registrar_resultado(
        tabela_resultados, 'data_ausente_perde_para_data_real',
        'NF 1001 sem data, NF 1002 com 2026-01-01', 'só NF 1002',
        'Nota sem Data Entrada da Nota nunca pode vencer uma com data real',
        f'{[l["NR NF"] for l in resultado]}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nota_mais_antiga_depois_da_mais_recente_nao_substitui(tabela_resultados):
    # Setup: mesmo produto, mas a nota mais recente aparece PRIMEIRO na
    # lista, e a mais antiga vem depois — precisa continuar valendo a
    # mais recente (não é só "pegar a última processada").
    linhas = [
        _linha('111', '1002', '2026-06-01'),
        _linha('111', '1001', '2026-01-01'),
    ]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = len(resultado) == 1 and resultado[0]['NR NF'] == '1002'
    registrar_resultado(
        tabela_resultados, 'nota_mais_antiga_depois_nao_substitui',
        'NF 1002 (2026-06-01) processada antes de NF 1001 (2026-01-01), mesmo produto', 'só NF 1002',
        'Comparação real, não "pega a última vista" — nota mais antiga processada depois não pode substituir a mais recente',
        f'{[l["NR NF"] for l in resultado]}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_nf_nao_numerica_e_pulada_mesmo_sendo_a_unica_nota_do_produto(tabela_resultados):
    # Setup: bug real corrigido em 15/08/2026 — antes, a 1ª nota de cada
    # produto nunca era validada (curto-circuito do "or" na comparação),
    # então uma NF não numérica na ÚNICA nota de um produto passava batido
    # sem erro nenhum. Agora precisa ser pega e registrada como erro.
    linhas = [_linha('111', 'ABC-nao-numerico', '2026-01-01')]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = resultado == [] and len(erros) == 1 and erros[0]['identificador'] == '111'
    registrar_resultado(
        tabela_resultados, 'nf_nao_numerica_pulada_unica_nota',
        '1 produto, 1 nota só, NF="ABC-nao-numerico"', '0 selecionados + 1 erro',
        'Produto com 1 nota só não pode escapar da validação (bug do curto-circuito corrigido)',
        f'{len(resultado)} selecionado(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_data_malformada_e_pulada_sem_derrubar_as_outras_notas(tabela_resultados):
    # Setup: 1 nota com data num formato que não dá pra converter, entre
    # 2 notas válidas de produtos diferentes.
    linhas = [
        _linha('111', '1001', '2026-01-01'),
        _linha('222', '2002', 'data-invalida'),
        _linha('333', '3003', '2026-03-01'),
    ]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = (
        {l['Código Barras'] for l in resultado} == {'111', '333'}
        and len(erros) == 1
        and erros[0]['identificador'] == '222'
    )
    registrar_resultado(
        tabela_resultados, 'data_malformada_pulada',
        'produto 222 com Entrada NF="data-invalida", outros 2 produtos válidos', '2 selecionados (111, 333) + 1 erro (222)',
        'Nota com data malformada não pode derrubar a seleção dos outros produtos',
        f'{len(resultado)} selecionado(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_linha_sem_codigo_barras_e_pulada_e_registrada_como_erro(tabela_resultados):
    # Setup: 1 linha sem o campo Código Barras.
    linhas = [{'NR NF': '1001', 'Entrada NF': '2026-01-01'}]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert
    bateu = resultado == [] and len(erros) == 1
    registrar_resultado(
        tabela_resultados, 'linha_sem_codigo_barras_pulada',
        'linha sem Código Barras', '0 selecionados + 1 erro',
        'Linha sem Código Barras não tem como ser associada a um produto — precisa virar erro, não quebrar',
        f'{len(resultado)} selecionado(s), erros={erros}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup: valor esperado ERRADO de propósito.
    linhas = [_linha('111', '1001', '2026-01-01')]

    # Exercise
    resultado, erros = selecionar_nota_mais_recente_por_produto(linhas)

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{len(resultado)} produto(s)', '99 produtos (errado de propósito)',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{len(resultado)} produto(s)', len(resultado) == 99,
    )
    assert len(resultado) == 99

    # TearDown: nada a desmontar.