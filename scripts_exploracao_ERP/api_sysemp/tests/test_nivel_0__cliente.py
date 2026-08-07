# scripts_exploracao_ERP/api_sysemp/tests/test_nivel_0__cliente.py

# Função Objetivo: Nível 0 (zero dependência de banco/Django) do cliente
# HTTP do Sysemp — cobre como cada categoria de resposta é tratada
# (sucesso, autenticação, negócio, limite de requisições, servidor, falha
# de rede, status não mapeado) e a contagem de tentativas, através do
# único método público `chamar()`. Este cliente não sabe nada sobre
# endpoint específico — por isso os testes usam método e corpo genéricos,
# nunca os reais do manifesto de nota de entrada (isso mora em
# test_nivel_0__impostos_entrada_xml.py). `requests.post` é a única borda
# substituída. Nunca bate na API real. Ver "Padrao de Robustez para
# Clientes de API Externa" no vault.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import requests

from api_sysemp.core.cliente import ClienteApiSysemp
from api_sysemp.core.excecoes import (
    ErroAPISysemp,
    ErroAutenticacaoSysemp,
    ErroLimiteRequisicoesSysemp,
    ErroNegocioSysemp,
    ErroRedeSysemp,
    ErroServidorSysemp,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — api_sysemp.core.cliente'

METODO_DE_TESTE = 'metodoQualquer'
CORPO_DE_TESTE = {'chave': 'valor'}


class _RespostaFalsa:
    # Função Objetivo: Substituto mínimo de requests.Response — a borda de
    # rede em si, o único ponto que a Disciplina de Testes autoriza
    # substituir numa integração externa.
    def __init__(self, status_code, corpo_json=None, headers=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._corpo_json = corpo_json if corpo_json is not None else {}
        self.text = str(self._corpo_json)
        self.headers = headers or {}

    def json(self):
        return self._corpo_json


@pytest.fixture(autouse=True)
def _sem_espera_real(monkeypatch):
    # Setup: silencia o sleep — o valor exato já foi coberto em
    # test_nivel_0__protecao.py.
    monkeypatch.setattr('api_sysemp.core.protecao.time.sleep', lambda segundos: None)
    monkeypatch.setattr('api_sysemp.core.cliente.time.sleep', lambda segundos: None)
    yield
    # TearDown: monkeypatch desfaz sozinho ao fim do teste.


def _cliente_de_teste():
    return ClienteApiSysemp(token='token-de-teste', maximo_tentativas=4)


# ===================================================================
# Categorias com ação imediata (sem retentativa): autenticação e negócio.
# ===================================================================

@pytest.mark.parametrize(
    'status_code, excecao_esperada, motivo',
    [
        (401, ErroAutenticacaoSysemp, 'Token inválido não se resolve tentando de novo — falha na hora, sem retentativa.'),
        (403, ErroAutenticacaoSysemp, 'Mesmo caso de 401, só que proibido em vez de não-autenticado — mesma ação: falha na hora.'),
        (400, ErroNegocioSysemp, 'Parâmetro inválido não se resolve tentando de novo — falha na hora, sem retentativa.'),
    ],
    ids=[
        'status_401_levanta_erro_autenticacao_sem_retry',
        'status_403_levanta_erro_autenticacao_sem_retry',
        'status_400_levanta_erro_negocio_sem_retry',
    ],
)
def test_chamar_erro_nao_passageiro_falha_na_primeira_tentativa(status_code, excecao_esperada, motivo, monkeypatch, tabela_resultados):
    # Setup: requests.post sempre devolve o mesmo erro não-passageiro.
    chamadas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(1)
        return _RespostaFalsa(status_code)

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)
    except ErroAPISysemp as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = (type(excecao_capturada), len(chamadas))
    esperado = (excecao_esperada, 1)
    registrar_resultado(
        tabela_resultados, f'chamar_erro_nao_passageiro_{status_code}',
        f'status_code={status_code}', f'{esperado}', motivo,
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Categorias passageiras (com retentativa): limite de requisição, servidor
# e falha de rede — esgotam max_tentativas quando o erro nunca some.
# ===================================================================

@pytest.mark.parametrize(
    'status_code, excecao_esperada, motivo',
    [
        (429, ErroLimiteRequisicoesSysemp, 'Limite de requisições é passageiro — tenta até o máximo, mas se nunca melhorar, desiste no final.'),
        (500, ErroServidorSysemp, 'Erro de servidor é passageiro — mesma lógica de retentativa até o máximo.'),
    ],
    ids=[
        'status_429_esgota_tentativas_levanta_erro_limite',
        'status_500_esgota_tentativas_levanta_erro_servidor',
    ],
)
def test_chamar_erro_passageiro_esgota_tentativas(status_code, excecao_esperada, motivo, monkeypatch, tabela_resultados):
    # Setup: requests.post sempre devolve o mesmo erro passageiro, nunca
    # melhora — força esgotar as 4 tentativas configuradas.
    chamadas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(1)
        return _RespostaFalsa(status_code)

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)
    except ErroAPISysemp as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = (type(excecao_capturada), len(chamadas))
    esperado = (excecao_esperada, 4)
    registrar_resultado(
        tabela_resultados, f'chamar_erro_passageiro_esgota_{status_code}',
        f'status_code={status_code} em todas as tentativas', f'{esperado}', motivo,
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_chamar_falha_de_rede_esgota_tentativas_levanta_erro_rede(monkeypatch, tabela_resultados):
    # Setup: requests.post sempre levanta exceção crua de rede — nunca deve
    # escapar sem reembrulhar em ErroRedeSysemp.
    chamadas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(1)
        raise requests.exceptions.ConnectionError('Falha de rede simulada')

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)
    except ErroAPISysemp as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = (type(excecao_capturada), len(chamadas))
    esperado = (ErroRedeSysemp, 4)
    registrar_resultado(
        tabela_resultados, 'chamar_falha_de_rede_esgota_tentativas',
        'requests.post sempre levanta ConnectionError', f'{esperado}',
        'Exceção crua do requests nunca escapa sem reembrulhar — é passageira, tenta até o máximo, depois vira ErroRedeSysemp.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Recuperação: erro passageiro nas primeiras tentativas, sucesso antes de
# esgotar.
# ===================================================================

def test_chamar_recupera_apos_erro_passageiro_com_sucesso_antes_de_esgotar(monkeypatch, tabela_resultados):
    # Setup: 429 nas 2 primeiras chamadas, sucesso na 3ª.
    respostas = iter([
        _RespostaFalsa(429),
        _RespostaFalsa(429),
        _RespostaFalsa(200, corpo_json={'ok': True}),
    ])
    chamadas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(1)
        return next(respostas)

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    resultado_chamada = cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)

    # Assert
    resultado = (resultado_chamada, len(chamadas))
    esperado = ({'ok': True}, 3)
    registrar_resultado(
        tabela_resultados, 'chamar_recupera_apos_erro_passageiro',
        '429, 429, 200 (nessa ordem)', f'{esperado}',
        'Erro passageiro que para de acontecer antes do limite de tentativas resulta em sucesso — o retry de fato recupera, não só desiste.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_chamar_sucesso_na_primeira_tentativa_nao_faz_retry(monkeypatch, tabela_resultados):
    # Setup: 200 de primeira — caminho feliz.
    chamadas = []
    corpo_esperado = {'ok': True, 'itens': [1, 2]}

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(1)
        return _RespostaFalsa(200, corpo_json=corpo_esperado)

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    resultado_chamada = cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)

    # Assert
    resultado = (resultado_chamada, len(chamadas))
    esperado = (corpo_esperado, 1)
    registrar_resultado(
        tabela_resultados, 'chamar_sucesso_primeira_tentativa',
        'status_code=200 de primeira', f'{esperado}',
        'Caminho feliz — sucesso de primeira nunca aciona retentativa nem espera de backoff.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Status não mapeado — sobe o erro genérico, sem retentativa.
# ===================================================================

def test_chamar_status_inesperado_levanta_erro_generico_sem_retry(monkeypatch, tabela_resultados):
    # Setup: 404 não é nenhuma categoria tratada.
    chamadas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(1)
        return _RespostaFalsa(404)

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)
    except ErroAPISysemp as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = (type(excecao_capturada), len(chamadas))
    esperado = (ErroAPISysemp, 1)
    registrar_resultado(
        tabela_resultados, 'chamar_status_inesperado_404',
        'status_code=404 (não mapeado)', f'{esperado}',
        '404 não é nenhuma categoria conhecida — sobe o erro genérico da hierarquia, sem retentativa.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Retry-After.
# ===================================================================

def test_chamar_recupera_e_le_retry_after_quando_429_informa(monkeypatch, tabela_resultados):
    # Setup: 429 com header Retry-After na 1ª chamada, sucesso na 2ª.
    respostas = iter([
        _RespostaFalsa(429, headers={'Retry-After': '2'}),
        _RespostaFalsa(200, corpo_json={'ok': True}),
    ])
    chamadas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(1)
        return next(respostas)

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    resultado_chamada = cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)

    # Assert
    resultado = (resultado_chamada, len(chamadas))
    esperado = ({'ok': True}, 2)
    registrar_resultado(
        tabela_resultados, 'chamar_le_retry_after_e_recupera',
        "429 com header Retry-After='2', depois 200", f'{esperado}',
        'Quando a própria API informa Retry-After, o cliente lê e segue — o valor exato de segundos é coberto em test_nivel_0__protecao.py.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# _extrair_tempo_espera_sugerido — leitura defensiva do header.
# ===================================================================

@pytest.mark.parametrize(
    'headers, esperado, motivo',
    [
        ({'Retry-After': '2'}, 2.0, 'Header presente e numérico — usa o valor exato informado pela API.'),
        ({}, None, 'Sem header nenhum — não há tempo sugerido, cliente cai pro cálculo exponencial.'),
        ({'Retry-After': 'nao-eh-numero'}, None, 'Header presente mas não numérico — trata como se não tivesse vindo nada, nunca quebra.'),
    ],
    ids=[
        'header_presente_numerico_usa_valor_exato',
        'header_ausente_retorna_none',
        'header_presente_mas_invalido_retorna_none',
    ],
)
def test_extrair_tempo_espera_sugerido(headers, esperado, motivo, tabela_resultados):
    # Setup: resposta falsa só com headers variando.
    cliente = _cliente_de_teste()
    resposta = _RespostaFalsa(429, headers=headers)

    # Exercise
    resultado = cliente._extrair_tempo_espera_sugerido(resposta)

    # Assert
    registrar_resultado(
        tabela_resultados, 'extrair_tempo_espera_sugerido',
        f'headers={headers}', f'{esperado}', motivo,
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# __init__ — token vazio/None nunca constrói o cliente.
# ===================================================================

@pytest.mark.parametrize(
    'token_invalido',
    ['', None],
    ids=['token_vazio', 'token_none'],
)
def test_init_recusa_token_vazio_ou_none(token_invalido, tabela_resultados):
    # Setup: nada a montar — token_invalido já vem do parametrize.

    # Exercise
    excecao_capturada = None
    try:
        ClienteApiSysemp(token=token_invalido)
    except ValueError as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = type(excecao_capturada)
    esperado = ValueError
    registrar_resultado(
        tabela_resultados, 'init_recusa_token_invalido',
        f'token={token_invalido!r}', f'{esperado}',
        'Sem token não tem como autenticar — a guarda de entrada recusa na hora, antes de qualquer chamada.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Caso de falha proposital — nunca remover.
# ===================================================================

@pytest.mark.xfail(reason='Falha de propósito — prova visual de como fica a linha FALHOU na tabela')
def test_chamar_caso_de_falha_proposital(monkeypatch, tabela_resultados):
    # Setup: sucesso de primeira, mas afirmamos um número de chamadas
    # errado de propósito (2, quando só houve 1).
    def _requests_post_falso(url, json, headers, timeout):
        return _RespostaFalsa(200, corpo_json={'ok': True})

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    cliente = _cliente_de_teste()

    # Exercise
    cliente.chamar(METODO_DE_TESTE, CORPO_DE_TESTE)

    # Assert
    resultado = 1
    esperado_errado = 2
    registrar_resultado(
        tabela_resultados, 'chamar_caso_de_falha_proposital',
        'sucesso de primeira (1 chamada de verdade)', f'{esperado_errado}',
        'Propositalmente errado — só houve 1 chamada, nunca 2. Existe só pra provar que a tabela mostra FALHOU corretamente.',
        f'{resultado}', resultado == esperado_errado,
    )
    assert resultado == esperado_errado

    # TearDown: nada a desmontar.