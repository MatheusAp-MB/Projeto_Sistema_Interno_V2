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
from api_sysemp.core.excecoes import ErroRedeSysemp
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
# Paginação completa (listar_periodo_completo) — nunca tinha teste
# isolado antes (achado real, 14/08/2026, revisão calma do pipeline).
# Cobre acumulação normal e a resiliência: preserva o que já foi
# buscado se a API falhar no meio de uma paginação longa.
# ===================================================================

def test_listar_periodo_completo_acumula_paginas_ate_a_vazia(monkeypatch, tabela_resultados):
    # Setup: 2 páginas com registro (2 e 1), 3ª página vazia — fim
    # normal da paginação.
    respostas = [
        {'status': True, 'qtde': 2, 'retorno': [{'chave': 'nfe-1'}, {'chave': 'nfe-2'}]},
        {'status': True, 'qtde': 1, 'retorno': [{'chave': 'nfe-3'}]},
        {'status': True, 'qtde': 0, 'retorno': []},
    ]
    offsets_recebidos = []

    def _requests_post_falso(url, json, headers, timeout):
        offsets_recebidos.append(json['offset'])
        return _RespostaFalsa(200, corpo_json=respostas[len(offsets_recebidos) - 1])

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    contexto = _contexto_de_teste()
    progresso = []

    # Exercise
    resultado = contexto.listar_periodo_completo(
        '2026-07-01', '2026-08-06', data_referencia=date(2026, 8, 6),
        ao_avancar_pagina=lambda pagina, na_pagina, total: progresso.append((pagina, na_pagina, total)),
    )

    # Assert: acumulou as 3 (2+1) das 2 primeiras páginas, parou na 3ª
    # vazia, offset avançou certo a cada chamada.
    esperado = {'retorno': [{'chave': 'nfe-1'}, {'chave': 'nfe-2'}, {'chave': 'nfe-3'}]}
    bateu = (
        resultado == esperado
        and offsets_recebidos == ['0', '2', '3']
        and progresso == [(1, 2, 2), (2, 1, 3)]
    )
    registrar_resultado(
        tabela_resultados, 'listar_periodo_completo_acumula_paginas',
        '3 páginas simuladas (2, 1, 0 registros)', f'{esperado}',
        'listar_periodo_completo nunca teve teste isolado antes — confirma acumulação e parada na página vazia.',
        f'{resultado}, offsets={offsets_recebidos}, progresso={progresso}', bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_listar_periodo_completo_salva_parcial_e_ainda_relanca_quando_falha_no_meio(monkeypatch, tabela_resultados):
    # Setup: 1ª página com sucesso (2 registros), toda chamada seguinte
    # falha de rede de verdade — simula queda no meio de uma busca
    # longa. maximo_tentativas=4 (ver _contexto_de_teste): as 4
    # tentativas da 2ª página falham, ClienteApiSysemp esgota e levanta
    # ErroRedeSysemp.
    primeira_pagina = {'status': True, 'qtde': 2, 'retorno': [{'chave': 'nfe-1'}, {'chave': 'nfe-2'}]}
    chamadas = []

    def _requests_post_falso(url, json, headers, timeout):
        chamadas.append(json['offset'])
        if len(chamadas) == 1:
            return _RespostaFalsa(200, corpo_json=primeira_pagina)
        raise requests.exceptions.ConnectionError('rede caiu simulada')

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    contexto = _contexto_de_teste()
    parciais_salvos = []

    # Exercise
    excecao_capturada = None
    try:
        contexto.listar_periodo_completo(
            '2026-07-01', '2026-08-06', data_referencia=date(2026, 8, 6),
            ao_falhar_com_parcial=lambda registros: parciais_salvos.append(registros),
        )
    except ErroRedeSysemp as excecao:
        excecao_capturada = excecao

    # Assert: exceção original ainda propaga (nunca é engolida) e o
    # parcial preservado tem exatamente a 1ª página já obtida.
    bateu = (
        excecao_capturada is not None
        and parciais_salvos == [[{'chave': 'nfe-1'}, {'chave': 'nfe-2'}]]
    )
    registrar_resultado(
        tabela_resultados, 'listar_periodo_completo_salva_parcial_em_falha',
        '1ª página ok (2 registros), 2ª página falha de rede',
        '1 página preservada via callback, ErroRedeSysemp ainda propaga',
        'Achado real (14/08/2026): sem isso, uma falha no meio de uma paginação longa jogava fora tudo que já tinha sido buscado com sucesso.',
        f'excecao={type(excecao_capturada).__name__ if excecao_capturada else None}, parciais_salvos={parciais_salvos}',
        bateu,
    )
    assert bateu

    # TearDown: nada a desmontar.


def test_listar_periodo_completo_nao_chama_parcial_quando_nenhuma_pagina_teve_sucesso(monkeypatch, tabela_resultados):
    # Setup: já a 1ª chamada falha de rede — nenhuma página foi obtida
    # ainda, não há nada de real pra preservar.
    def _requests_post_falso(url, json, headers, timeout):
        raise requests.exceptions.ConnectionError('rede caiu simulada desde a 1ª chamada')

    monkeypatch.setattr(requests, 'post', _requests_post_falso)
    contexto = _contexto_de_teste()
    parciais_salvos = []

    # Exercise
    excecao_capturada = None
    try:
        contexto.listar_periodo_completo(
            '2026-07-01', '2026-08-06', data_referencia=date(2026, 8, 6),
            ao_falhar_com_parcial=lambda registros: parciais_salvos.append(registros),
        )
    except ErroRedeSysemp as excecao:
        excecao_capturada = excecao

    # Assert: exceção propaga, mas o callback de parcial nunca é
    # chamado — não faz sentido salvar uma lista vazia.
    bateu = excecao_capturada is not None and parciais_salvos == []
    registrar_resultado(
        tabela_resultados, 'listar_periodo_completo_sem_parcial_quando_nada_obtido',
        'já a 1ª chamada falha, nenhuma página obtida', 'callback de parcial nunca chamado',
        'Não faz sentido acionar o callback de salvamento parcial sem nenhum dado real pra preservar.',
        f'excecao={type(excecao_capturada).__name__ if excecao_capturada else None}, parciais_salvos={parciais_salvos}',
        bateu,
    )
    assert bateu

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