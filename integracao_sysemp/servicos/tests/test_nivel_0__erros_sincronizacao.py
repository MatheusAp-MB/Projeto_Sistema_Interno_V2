# integracao_sysemp/servicos/tests/test_nivel_0__erros_sincronizacao.py

# Função Objetivo: Nível 0 — registrar_erro()/remover_erro() do módulo
# erros_sincronizacao. Toca disco via arquivos_retorno_api, redirecionado
# pro tmp_path do pytest (mesmo esquema do test de arquivos_retorno_api).

import pytest

from integracao_sysemp.servicos import arquivos_retorno_api, erros_sincronizacao
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — erros_sincronizacao'


@pytest.fixture(autouse=True)
def _redirecionar_pasta_retorno_api(tmp_path, monkeypatch):
    monkeypatch.setattr(arquivos_retorno_api, 'PASTA_RETORNO_API', tmp_path)


def test_registrar_erro_cria_a_pendencia(tabela_resultados):
    # Setup: nenhuma pendência ainda.

    # Exercise
    erros_sincronizacao.registrar_erro('111', etapa='parse', mensagem='campo ausente')

    # Assert
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS)
    bateu = '111' in erros and erros['111']['etapa'] == 'parse' and erros['111']['mensagem'] == 'campo ausente'
    registrar_resultado(
        tabela_resultados, 'registrar_erro_cria_pendencia',
        'Código Barras 111, etapa parse', 'pendência criada com etapa e mensagem',
        'Erro registrado precisa ficar rastreável — etapa e motivo, não só o código',
        f'{erros.get("111")}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_registrar_erro_duas_vezes_sobrescreve_nao_duplica(tabela_resultados):
    # Setup: 1ª pendência já registrada.
    erros_sincronizacao.registrar_erro('111', etapa='parse', mensagem='erro antigo')

    # Exercise: 2ª chamada, mesmo produto, mensagem diferente.
    erros_sincronizacao.registrar_erro('111', etapa='persistencia', mensagem='erro novo')

    # Assert
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS)
    bateu = len(erros) == 1 and erros['111']['mensagem'] == 'erro novo'
    registrar_resultado(
        tabela_resultados, 'registrar_erro_sobrescreve',
        '2ª chamada pro mesmo Código Barras', '1 só pendência, com a mensagem mais recente',
        'Pendência é sobre o estado atual do produto, não um log — não duplica',
        f'{len(erros)} pendência(s), mensagem={erros["111"]["mensagem"]!r}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_remover_erro_remove_a_pendencia_existente(tabela_resultados):
    # Setup: pendência registrada.
    erros_sincronizacao.registrar_erro('111', etapa='parse', mensagem='erro')

    # Exercise
    erros_sincronizacao.remover_erro('111')

    # Assert
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS)
    registrar_resultado(
        tabela_resultados, 'remover_erro_remove_pendencia',
        'pendência existente pro Código Barras 111', 'pendência removida',
        'Produto que voltou a sincronizar bem não pode continuar marcado como erro',
        f'{erros}', '111' not in erros,
    )
    assert '111' not in erros

    # TearDown: nada a desmontar.


def test_remover_erro_de_quem_nao_tem_pendencia_nao_quebra(tabela_resultados):
    # Setup: nenhuma pendência registrada.

    # Exercise
    erros_sincronizacao.remover_erro('999')

    # Assert: só precisa não levantar exceção — comportamento é a prova.
    registrar_resultado(
        tabela_resultados, 'remover_erro_sem_pendencia_nao_quebra',
        'Código Barras sem pendência nenhuma', 'nenhuma exceção levantada',
        'remover_erro precisa ser idempotente — chamada de sobra não pode quebrar',
        'nenhuma exceção levantada', True,
    )
    assert True

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual da linha FALHOU na tabela')
def test_caso_de_falha_proposital(tabela_resultados):
    # Setup: pendência registrada.
    erros_sincronizacao.registrar_erro('111', etapa='parse', mensagem='erro real')

    # Exercise
    erros = arquivos_retorno_api.ler_json(arquivos_retorno_api.NOME_ARQUIVO_ERROS)

    # Assert: compara contra o valor errado de propósito — tem que falhar.
    registrar_resultado(
        tabela_resultados, 'caso_de_falha_proposital',
        f'{erros["111"]["mensagem"]}', 'mensagem errada de propósito',
        'Propositalmente errado — prova que a tabela mostra FALHOU corretamente.',
        f'{erros["111"]["mensagem"]}', erros['111']['mensagem'] == 'mensagem errada de propósito',
    )
    assert erros['111']['mensagem'] == 'mensagem errada de propósito'

    # TearDown: nada a desmontar.