# api_sysemp/tests/test_nivel_0__impostos_entrada_xml.py

# Função Objetivo: Nível 0 (zero dependência de banco/Django) do contexto
# "Obter impostos de entrada vindos do XML" — cobre a validação de período
# e de offset (pertence a este contexto, não ao cliente de transporte) e
# confirma, com 1-2 casos representativos, que a chamada ao
# ClienteApiSysemp (DOC já exaustivamente testado em
# test_nivel_0__cliente.py) usa os nomes de campo corretos — não repete
# aqui a exaustão de retry/backoff/exceção. Usa o ClienteApiSysemp real,
# monkeypatch só em requests.post. Nunca bate na API real. Ver "Padrao de
# Robustez para Clientes de API Externa" no vault.

from datetime import date

import pytest
import requests

from api_sysemp.core.cliente import ClienteApiSysemp
from api_sysemp.impostos_entrada_xml import ImpostosEntradaXML
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — api_sysemp.impostos_entrada_xml'


class _RespostaFalsa:
    def __init__(self, status_code, corpo_json=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._corpo_json = corpo_json if corpo_json is not None else {}
        self.text = str(self._corpo_json)
        self.headers = {}

    def json(self):
        return self._corpo_json


@pytest.fixture(autouse=True)
def _sem_espera_real(monkeypatch):
    # Setup: silencia o sleep — valor exato já coberto em outro arquivo.
    monkeypatch.setattr('api_sysemp.core.protecao.time.sleep', lambda segundos: None)
    monkeypatch.setattr('api_sysemp.core.cliente.time.sleep', lambda segundos: None)
    yield
    # TearDown: monkeypatch desfaz sozinho.


def _contexto_de_teste():
    cliente = ClienteApiSysemp(token='token-de-teste', maximo_tentativas=4)
    return ImpostosEntradaXML(cliente)


# ===================================================================
# Validação de período — nunca chega a chamar requests.post quando o
# período já está errado.
# ===================================================================

@pytest.mark.parametrize(
    'data_inicial, data_final, motivo',
    [
        ('não-é-data', '2026-08-01', 'data_inicial em formato inválido — recusado antes de qualquer rede.'),
        ('2026-08-01', 'não-é-data', 'data_final em formato inválido — recusado antes de qualquer rede.'),
        ('2026-08-05', '2026-08-01', 'data_inicial depois de data_final — período invertido.'),
        ('2026-08-01', '2026-08-01', 'data_inicial igual a data_final — precisa ser estritamente anterior.'),
    ],
    ids=[
        'data_inicial_formato_invalido',
        'data_final_formato_invalido',
        'periodo_invertido',
        'periodo_com_mesma_data',
    ],
)
def test_listar_por_periodo_recusa_periodo_invalido_sem_chamar_rede(data_inicial, data_final, motivo, monkeypatch, tabela_resultados):
    # Setup: requests.post nunca deveria ser chamado.
    chamadas = []
    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs: chamadas.append(1))
    contexto = _contexto_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        contexto.listar_por_periodo(data_inicial, data_final, '0', data_referencia=date(2026, 8, 6))
    except ValueError as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = (type(excecao_capturada), len(chamadas))
    esperado = (ValueError, 0)
    registrar_resultado(
        tabela_resultados, f'listar_por_periodo_recusa_{data_inicial}_{data_final}',
        f'data_inicial={data_inicial!r}, data_final={data_final!r}', f'{esperado}', motivo,
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_listar_por_periodo_recusa_data_alem_do_limite_futuro(monkeypatch, tabela_resultados):
    # Setup: referência fixa 2026-08-06 — limite permitido é 2026-08-07
    # (1 dia de margem por causa dos bugs de data conhecidos do ERP).
    chamadas = []
    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs: chamadas.append(1))
    contexto = _contexto_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        contexto.listar_por_periodo('2026-08-01', '2026-08-08', '0', data_referencia=date(2026, 8, 6))
    except ValueError as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = (type(excecao_capturada), len(chamadas))
    esperado = (ValueError, 0)
    registrar_resultado(
        tabela_resultados, 'listar_por_periodo_recusa_data_futura',
        "data_final='2026-08-08', data_referencia=2026-08-06", f'{esperado}',
        'Mais de 1 dia no futuro em relação à referência — passa do limite com margem.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_listar_por_periodo_aceita_data_final_no_limite_exato(monkeypatch, tabela_resultados):
    # Setup: data_final exatamente no limite (referência + 1 dia) — deve
    # passar, é a margem que o ERP precisa.
    def _requests_post_falso(url, json, headers, timeout):
        return _RespostaFalsa(200, corpo_json={'status': True, 'qtde': 0, 'retorno': []})

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    contexto = _contexto_de_teste()

    # Exercise
    resultado = contexto.listar_por_periodo('2026-08-01', '2026-08-07', '0', data_referencia=date(2026, 8, 6))

    # Assert
    esperado = {'status': True, 'qtde': 0, 'retorno': []}
    registrar_resultado(
        tabela_resultados, 'listar_por_periodo_aceita_limite_exato',
        "data_final='2026-08-07', data_referencia=2026-08-06 (limite exato)", f'{esperado}',
        'A margem de 1 dia é inclusiva — no limite exato ainda é aceito, só além dele é recusado.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.

def test_listar_por_periodo_usa_hoje_quando_data_referencia_nao_informada(monkeypatch, tabela_resultados):
    # Setup: data_referencia não é passada (uso real) — trava "hoje" numa
    # subclasse de date só pra este teste, sem precisar de lib nova, e sem
    # deixar o teste flutuar com o dia real da máquina.
    class _DataFixa(date):
        @classmethod
        def today(cls):
            return date(2026, 8, 6)

    monkeypatch.setattr('api_sysemp.impostos_entrada_xml.date', _DataFixa)

    def _requests_post_falso(url, json, headers, timeout):
        return _RespostaFalsa(200, corpo_json={'status': True, 'qtde': 0, 'retorno': []})

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    contexto = _contexto_de_teste()

    # Exercise: sem passar data_referencia — precisa cair no date.today().
    resultado = contexto.listar_por_periodo('2026-08-01', '2026-08-07', '0')

    # Assert
    esperado = {'status': True, 'qtde': 0, 'retorno': []}
    registrar_resultado(
        tabela_resultados, 'listar_por_periodo_usa_hoje_quando_nao_informada',
        "data_referencia não informada, 'hoje' travado em 2026-08-06", f'{esperado}',
        'Em uso real (fora de teste) data_referencia nunca é passada — precisa cair certo no date.today().',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.

# ===================================================================
# Validação de offset — mesma lógica, nunca chega a chamar rede.
# ===================================================================

@pytest.mark.parametrize(
    'offset, motivo',
    [
        ('', 'Offset vazio já quebrou a API antes (achado real) — recusado antes de qualquer rede.'),
        ('abc', 'Offset não numérico não representa uma página válida — recusado antes de qualquer rede.'),
        ('-1', 'Offset negativo não faz sentido como página — recusado antes de qualquer rede.'),
    ],
    ids=[
        'offset_vazio',
        'offset_nao_numerico',
        'offset_negativo',
    ],
)
def test_listar_por_periodo_recusa_offset_invalido_sem_chamar_rede(offset, motivo, monkeypatch, tabela_resultados):
    # Setup: requests.post nunca deveria ser chamado.
    chamadas = []
    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs: chamadas.append(1))
    contexto = _contexto_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        contexto.listar_por_periodo('2026-08-01', '2026-08-05', offset, data_referencia=date(2026, 8, 6))
    except ValueError as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = (type(excecao_capturada), len(chamadas))
    esperado = (ValueError, 0)
    registrar_resultado(
        tabela_resultados, f'listar_por_periodo_recusa_offset_{offset!r}',
        f'offset={offset!r}', f'{esperado}', motivo,
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Caminho feliz — confirma que o DOC é chamado com os nomes de campo
# corretos. Não repete retry/backoff/exceção aqui.
# ===================================================================

def test_listar_por_periodo_chama_cliente_com_corpo_correto(monkeypatch, tabela_resultados):
    # Setup: captura o que foi de fato enviado pro requests.post.
    chamadas_recebidas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas_recebidas.append(json)
        return _RespostaFalsa(200, corpo_json={'status': True, 'qtde': 1, 'retorno': [{'chave': 'nfe-1'}]})

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    contexto = _contexto_de_teste()

    # Exercise
    resultado_chamada = contexto.listar_por_periodo('2026-07-01', '2026-08-01', '5', data_referencia=date(2026, 8, 6))

    # Assert
    resultado = (resultado_chamada, chamadas_recebidas)
    esperado = (
        {'status': True, 'qtde': 1, 'retorno': [{'chave': 'nfe-1'}]},
        [{'datainicial': '2026-07-01', 'datafinal': '2026-08-01', 'offset': '5'}],
    )
    registrar_resultado(
        tabela_resultados, 'listar_por_periodo_chama_cliente_com_corpo_correto',
        "data_inicial='2026-07-01', data_final='2026-08-01', offset='5'", f'{esperado}',
        'Confirma que o corpo enviado usa os nomes de campo que a API espera (datainicial/datafinal/offset) — retry/exceção já cobertos na camada de baixo.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Caso de falha proposital — nunca remover.
# ===================================================================

@pytest.mark.xfail(reason='Falha de propósito — prova visual de como fica a linha FALHOU na tabela')
def test_listar_por_periodo_caso_de_falha_proposital(tabela_resultados):
    # Setup: período válido, mas afirmamos que ele levanta ValueError — errado de propósito.
    contexto = _contexto_de_teste()

    # Exercise
    excecao_capturada = None
    try:
        contexto._validar_periodo('2026-08-01', '2026-08-05', date(2026, 8, 6))
    except ValueError as excecao:
        excecao_capturada = excecao

    # Assert
    resultado = type(excecao_capturada)
    esperado_errado = ValueError
    registrar_resultado(
        tabela_resultados, 'listar_por_periodo_caso_de_falha_proposital',
        'período válido (2026-08-01 a 2026-08-05)', f'{esperado_errado}',
        'Propositalmente errado — período válido nunca levanta ValueError. Existe só pra provar que a tabela mostra FALHOU corretamente.',
        f'{resultado}', resultado == esperado_errado,
    )
    assert resultado == esperado_errado

    # TearDown: nada a desmontar.