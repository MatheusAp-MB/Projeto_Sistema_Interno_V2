# integracao_sysemp/servicos/tests/test_nivel_0__arquivos_retorno_api.py

# Função Objetivo: Nível 0 — salvar_json()/ler_json() do módulo
# arquivos_retorno_api. Toca disco de verdade, mas sempre redirecionado
# pro tmp_path do próprio pytest (via monkeypatch) — nunca escreve na
# pasta real de retorno da API durante o teste.

import pytest

from integracao_sysemp.servicos import arquivos_retorno_api
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — arquivos_retorno_api'


@pytest.fixture(autouse=True)
def _redirecionar_pasta_retorno_api(tmp_path, monkeypatch):
    # * [EXPLICAÇÃO] → autouse: todo teste deste arquivo usa a pasta
    #                  temporária, nunca a pasta real do projeto.
    monkeypatch.setattr(arquivos_retorno_api, 'PASTA_RETORNO_API', tmp_path)


def test_salvar_e_ler_json_devolve_o_mesmo_conteudo(tabela_resultados):
    # Setup: dado qualquer.
    dado = {'a': 1, 'b': [1, 2, 3]}

    # Exercise
    arquivos_retorno_api.salvar_json(dado, 'arquivo_teste.json')
    lido = arquivos_retorno_api.ler_json('arquivo_teste.json')

    # Assert
    registrar_resultado(
        tabela_resultados, 'salvar_e_ler_json',
        f'{dado}', f'{dado}',
        'O que foi salvo precisa voltar exatamente igual',
        f'{lido}', lido == dado,
    )
    assert lido == dado

    # TearDown: nada a desmontar — tmp_path é descartado pelo pytest.


def test_ler_json_de_arquivo_inexistente_devolve_padrao(tabela_resultados):
    # Setup: nenhum arquivo criado ainda.

    # Exercise
    lido = arquivos_retorno_api.ler_json('nao_existe.json', padrao={'vazio': True})

    # Assert
    registrar_resultado(
        tabela_resultados, 'ler_json_inexistente_devolve_padrao',
        'arquivo nunca criado, padrao={"vazio": True}', '{"vazio": True}',
        'Antes da 1ª execução não existe arquivo nenhum — não pode quebrar',
        f'{lido}', lido == {'vazio': True},
    )
    assert lido == {'vazio': True}

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup: salva um dado.
    arquivos_retorno_api.salvar_json({'x': 1}, 'arquivo_teste.json')

    # Exercise
    lido = arquivos_retorno_api.ler_json('arquivo_teste.json')

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{lido}', '{"x": 999} (errado de propósito)',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{lido}', lido == {'x': 999},
    )
    assert lido == {'x': 999}

    # TearDown: nada a desmontar.