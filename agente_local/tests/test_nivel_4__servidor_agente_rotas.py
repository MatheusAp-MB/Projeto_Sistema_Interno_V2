# agente_local/tests/test_nivel_4__servidor_agente_rotas.py

# Função Objetivo: Testa as 2 rotas Flask do agente local (/executar,
# /executar-replicacao) — Nível 4 (HTTP real, via test_client do próprio
# Flask). As funções de processamento real (_processar_execucao/
# _processar_execucao_replicacao) são sempre substituídas por um fake —
# elas de verdade abrem janela/mouse/rede, isso não é testável por pytest
# (ver [[Fluxo Manual Antes do Automatizado]] no vault). O que importa aqui
# é só o CONTRATO HTTP da rota: validação de `empresa`, trava de execução
# simultânea, e repasse correto dos argumentos pra thread.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import time

import pytest

from agente_local import servidor_agente
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 4 — agente_local.servidor_agente: rotas /executar e /executar-replicacao'


@pytest.fixture
def flask_client():
    return servidor_agente.app_flask.test_client()


@pytest.fixture(autouse=True)
def _resetar_estado_global_do_agente():
    # Função Objetivo: execucao_em_andamento/icone_referencia são dicts
    # compartilhados no MÓDULO inteiro (mesma razão de existir do problema
    # original) — sem resetar entre testes, o 2º teste sempre acharia
    # "já tem execução rodando" por causa do teste anterior.
    servidor_agente.execucao_em_andamento['ativo'] = False
    servidor_agente.icone_referencia['obj'] = None
    yield
    servidor_agente.execucao_em_andamento['ativo'] = False
    servidor_agente.icone_referencia['obj'] = None


def _aguardar_thread_capturar(estado, chave='chamado', timeout=1.0):
    # Função Objetivo: a rota devolve a resposta HTTP ANTES da thread nova
    # terminar de rodar (ela só espera o F8, que nunca vem no teste) — dá um
    # tempo curto pra thread pelo menos COMEÇAR e registrar os argumentos
    # recebidos, sem precisar de sleep fixo arbitrário.
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if estado.get(chave):
            return
        time.sleep(0.01)


# ===================================================================
# /executar (Postagem)
# ===================================================================

def test_executar_sem_empresa_devolve_400_e_nao_chama_processar(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    monkeypatch.setattr(servidor_agente, '_processar_execucao', lambda *a, **k: estado.update(chamado=True))

    # Exercise:
    resposta = flask_client.post('/executar/1')

    # Assert:
    passou = resposta.status_code == 400 and estado['chamado'] is False
    registrar_resultado(
        tabela_resultados, teste='/executar sem ?empresa= na URL',
        entrada='POST /executar/1 (sem query string)', esperado='400, _processar_execucao NUNCA chamada',
        motivo='Mesma trava do EmpresaMiddleware, só que do lado do agente — nunca cai num padrão silencioso',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_executar_com_empresa_invalida_devolve_400(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    monkeypatch.setattr(servidor_agente, '_processar_execucao', lambda *a, **k: estado.update(chamado=True))

    # Exercise:
    resposta = flask_client.post('/executar/1?empresa=OUTRACOISA')

    # Assert:
    passou = resposta.status_code == 400 and estado['chamado'] is False
    registrar_resultado(
        tabela_resultados, teste='/executar com ?empresa=OUTRACOISA',
        entrada='POST /executar/1?empresa=OUTRACOISA', esperado='400, _processar_execucao NUNCA chamada',
        motivo='EMPRESAS_VALIDAS_AGENTE é a lista LOCAL duplicada de propósito (agente não importa Django)',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_executar_com_empresa_valida_inicia_thread_com_a_empresa_certa(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False, 'args': None}

    def _fake(execucao_id, empresa):
        estado['args'] = (execucao_id, empresa)
        estado['chamado'] = True
    monkeypatch.setattr(servidor_agente, '_processar_execucao', _fake)

    # Exercise:
    resposta = flask_client.post('/executar/42?empresa=SAMVALE')
    _aguardar_thread_capturar(estado)

    # Assert:
    corpo = resposta.get_json()
    passou = (
        resposta.status_code == 200 and corpo['empresa'] == 'SAMVALE'
        and estado['chamado'] is True and estado['args'] == (42, 'SAMVALE')
    )
    registrar_resultado(
        tabela_resultados, teste='/executar com ?empresa=SAMVALE — thread recebe execucao_id e empresa certos',
        entrada='POST /executar/42?empresa=SAMVALE', esperado='200, thread chamada com (42, "SAMVALE")',
        motivo='É esse repasse que o "Achado central" corrigiu — antes não existia empresa nenhuma aqui',
        obtido=f'status={resposta.status_code}, corpo={corpo}, args_recebidos={estado["args"]}',
        passou=passou,
    )
    assert passou


def test_executar_com_execucao_ja_em_andamento_devolve_409(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(servidor_agente, '_processar_execucao', lambda *a, **k: None)
    servidor_agente.execucao_em_andamento['ativo'] = True

    # Exercise:
    resposta = flask_client.post('/executar/1?empresa=MAGAZINE')

    # Assert:
    passou = resposta.status_code == 409
    registrar_resultado(
        tabela_resultados, teste='/executar com execução já em andamento neste agente',
        entrada='execucao_em_andamento["ativo"]=True', esperado='409, mesmo com ?empresa= válido',
        motivo='2 execuções concorrentes no mesmo agente derrubam Tkinter/hotkey — trava vem antes de validar empresa',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


# ===================================================================
# /executar-replicacao (mesmo contrato, espelhando a suíte acima)
# ===================================================================

def test_executar_replicacao_sem_empresa_devolve_400_e_nao_chama_processar(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    monkeypatch.setattr(servidor_agente, '_processar_execucao_replicacao', lambda *a, **k: estado.update(chamado=True))

    # Exercise:
    resposta = flask_client.post('/executar-replicacao/1')

    # Assert:
    passou = resposta.status_code == 400 and estado['chamado'] is False
    registrar_resultado(
        tabela_resultados, teste='/executar-replicacao sem ?empresa= na URL',
        entrada='POST /executar-replicacao/1 (sem query string)', esperado='400, _processar_execucao_replicacao NUNCA chamada',
        motivo='Mesma trava da rota de Postagem, espelhada pra Replicação',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_executar_replicacao_com_empresa_invalida_devolve_400(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    monkeypatch.setattr(servidor_agente, '_processar_execucao_replicacao', lambda *a, **k: estado.update(chamado=True))

    # Exercise:
    resposta = flask_client.post('/executar-replicacao/1?empresa=OUTRACOISA')

    # Assert:
    passou = resposta.status_code == 400 and estado['chamado'] is False
    registrar_resultado(
        tabela_resultados, teste='/executar-replicacao com ?empresa=OUTRACOISA',
        entrada='POST /executar-replicacao/1?empresa=OUTRACOISA', esperado='400, _processar_execucao_replicacao NUNCA chamada',
        motivo='Mesma lista local, mesma trava',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_executar_replicacao_com_empresa_valida_inicia_thread_com_a_empresa_certa(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False, 'args': None}

    def _fake(execucao_id, empresa):
        estado['args'] = (execucao_id, empresa)
        estado['chamado'] = True
    monkeypatch.setattr(servidor_agente, '_processar_execucao_replicacao', _fake)

    # Exercise:
    resposta = flask_client.post('/executar-replicacao/7?empresa=MAGAZINE')
    _aguardar_thread_capturar(estado)

    # Assert:
    corpo = resposta.get_json()
    passou = (
        resposta.status_code == 200 and corpo['empresa'] == 'MAGAZINE'
        and estado['chamado'] is True and estado['args'] == (7, 'MAGAZINE')
    )
    registrar_resultado(
        tabela_resultados, teste='/executar-replicacao com ?empresa=MAGAZINE — thread recebe execucao_id e empresa certos',
        entrada='POST /executar-replicacao/7?empresa=MAGAZINE', esperado='200, thread chamada com (7, "MAGAZINE")',
        motivo='Mesmo repasse crítico da rota de Postagem, espelhado pra Replicação',
        obtido=f'status={resposta.status_code}, corpo={corpo}, args_recebidos={estado["args"]}',
        passou=passou,
    )
    assert passou


def test_executar_replicacao_com_execucao_ja_em_andamento_devolve_409(flask_client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(servidor_agente, '_processar_execucao_replicacao', lambda *a, **k: None)
    servidor_agente.execucao_em_andamento['ativo'] = True

    # Exercise:
    resposta = flask_client.post('/executar-replicacao/1?empresa=MAGAZINE')

    # Assert:
    passou = resposta.status_code == 409
    registrar_resultado(
        tabela_resultados, teste='/executar-replicacao com execução já em andamento (mesma trava compartilhada)',
        entrada='execucao_em_andamento["ativo"]=True', esperado='409, mesmo com ?empresa= válido',
        motivo='Postagem e Replicação compartilham a MESMA trava de propósito (mesma infra de Tkinter/hotkey)',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou