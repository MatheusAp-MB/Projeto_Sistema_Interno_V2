# api_sysemp/tests/test_nivel_0__api_sysemp.py

# Função Objetivo: Nível 0 (zero dependência de banco/Django) do ponto
# único de entrada da API Sysemp — cobre a resolução de token (explícito
# vs. .env vs. ausente) e a propriedade impostos_entrada (cria 1 vez só,
# reaproveita depois). Nunca lê o .env real da máquina — MB_SYSEMP_API_TOKEN
# controlado só via monkeypatch, pra não depender do que existir de
# verdade no ambiente de quem roda o teste (settings.py já carrega o .env
# real na inicialização do Django, antes de qualquer teste rodar).

import pytest

from api_sysemp import ApiSysemp
from api_sysemp.impostos_entrada_xml import ImpostosEntradaXML
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — api_sysemp (ApiSysemp)'


@pytest.fixture(autouse=True)
def _sem_dotenv_real(monkeypatch):
    # Setup: nunca deixa o teste ler o .env real da máquina — controla
    # SYSEMP_API_TOKEN só via monkeypatch.setenv/delenv, determinístico
    # independente do que existir de verdade no .env do repo.
    monkeypatch.setattr('api_sysemp.load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.delenv('MB_SYSEMP_API_TOKEN', raising=False)
    yield
    # TearDown: monkeypatch desfaz sozinho.


def test_init_com_token_explicito_nao_consulta_variavel_de_ambiente(tabela_resultados):
    # Setup: variável de ambiente nem existe (fixture autouse já garante).

    # Exercise
    api = ApiSysemp(token='token-explicito-de-teste')

    # Assert
    resultado = api._cliente._token
    esperado = 'token-explicito-de-teste'
    registrar_resultado(
        tabela_resultados, 'init_com_token_explicito',
        "token='token-explicito-de-teste', sem SYSEMP_API_TOKEN no ambiente", f'{esperado}',
        'Token passado explicitamente nunca precisa consultar o .env — usa exatamente o que foi injetado.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_init_sem_token_explicito_carrega_da_variavel_de_ambiente(monkeypatch, tabela_resultados):
    # Setup: simula o .env já carregado — SYSEMP_API_TOKEN presente no ambiente.
    monkeypatch.setenv('MB_SYSEMP_API_TOKEN', 'token-do-env-de-teste')

    # Exercise
    api = ApiSysemp()

    # Assert
    resultado = api._cliente._token
    esperado = 'token-do-env-de-teste'
    registrar_resultado(
        tabela_resultados, 'init_sem_token_carrega_do_env',
        'token=None, SYSEMP_API_TOKEN=token-do-env-de-teste no ambiente', f'{esperado}',
        'Sem token explícito, cai pro .env da raiz do repo — mesmo token que estiver lá.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_init_sem_token_e_sem_variavel_de_ambiente_levanta_erro_claro(tabela_resultados):
    # Setup: nada a montar — fixture autouse já garante SYSEMP_API_TOKEN ausente.

    # Exercise
    excecao_capturada = None
    try:
        ApiSysemp()
    except RuntimeError as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = type(excecao_capturada)
    esperado = RuntimeError
    registrar_resultado(
        tabela_resultados, 'init_sem_token_e_sem_env',
        'token=None, SYSEMP_API_TOKEN ausente do ambiente', f'{esperado}',
        'Sem token nenhum disponível (nem explícito, nem .env) — recusa na hora, com mensagem clara de como corrigir.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_impostos_entrada_retorna_instancia_de_impostos_entrada_xml(tabela_resultados):
    # Setup: API com token explícito, sem precisar de rede pra este teste.
    api = ApiSysemp(token='token-de-teste')

    # Exercise
    resultado_tipo = type(api.impostos_entrada)

    # Assert
    esperado = ImpostosEntradaXML
    registrar_resultado(
        tabela_resultados, 'impostos_entrada_retorna_tipo_correto',
        "ApiSysemp(token='token-de-teste').impostos_entrada", f'{esperado}',
        'A propriedade precisa devolver o contexto certo — é o único jeito de acessar impostos de entrada a partir da API.',
        f'{resultado_tipo}', resultado_tipo == esperado,
    )
    assert resultado_tipo == esperado

    # TearDown: nada a desmontar.


def test_impostos_entrada_acessado_2x_devolve_a_mesma_instancia(tabela_resultados):
    # Setup: nada a montar além da API em si.
    api = ApiSysemp(token='token-de-teste')

    # Exercise
    primeiro_acesso = api.impostos_entrada
    segundo_acesso = api.impostos_entrada

    # Assert
    resultado = primeiro_acesso is segundo_acesso
    esperado = True
    registrar_resultado(
        tabela_resultados, 'impostos_entrada_e_cacheado',
        '2 acessos seguidos a api.impostos_entrada', f'{esperado}',
        'Cria 1 instância só e reaproveita — não faz sentido recriar o contexto a cada acesso.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


@pytest.mark.xfail(reason='Falha de propósito — prova visual de como fica a linha FALHOU na tabela')
def test_impostos_entrada_caso_de_falha_proposital(tabela_resultados):
    # Setup: valor errado de propósito — instância criada solta por fora
    # nunca é a mesma (cacheada) que a da propriedade.
    api = ApiSysemp(token='token-de-teste')

    # Exercise
    resultado = api.impostos_entrada is ImpostosEntradaXML(api._cliente)

    # Assert
    esperado_errado = True
    registrar_resultado(
        tabela_resultados, 'impostos_entrada_caso_de_falha_proposital',
        'api.impostos_entrada comparado com uma instância nova e solta', f'{esperado_errado}',
        'Propositalmente errado — existe só pra provar que a tabela mostra FALHOU corretamente.',
        f'{resultado}', resultado == esperado_errado,
    )
    assert resultado == esperado_errado

    # TearDown: nada a desmontar.