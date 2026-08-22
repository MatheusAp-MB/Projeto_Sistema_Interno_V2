# agenda_videos/tests/test_nivel_4__view_portal_drive_sincronizar.py

# Função Objetivo: Testa view_portal_drive_sincronizar(),
# view_portal_drive_sincronizar_status() e
# _rodar_sincronizacao_portal_drive_em_thread() — Nível 4 (view HTTP real).
# Cobre o mecanismo de "rotina vira botão" (thread + polling, 21/08/2026):
# disparo/idempotência do POST, leitura pura do GET de status, os 3
# desfechos gravados no cache pela thread (sucesso com avanço, sucesso sem
# avanço, erro) e a regressão real já corrigida uma vez — thread em
# background não herdava a empresa ativa do EmpresaMiddleware
# (threading.local()). Também cobre o bloco de view_portal_drive() que
# consome esse estado do cache e vira mensagem pro usuário.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.urls import reverse

import agenda_videos.views as views_module
from core.empresa import definir_empresa_ativa, obter_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from produtos.models import Produto
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — view_portal_drive_sincronizar()/_status(): thread + polling'


@pytest.fixture(autouse=True)
def _empresa_ativa_magazine():
    definir_empresa_ativa(EMPRESA_MAGAZINE)


@pytest.fixture(autouse=True)
def _cache_limpo():
    # Setup/Teardown: o cache é global ao processo, não por teste — sem
    # isso, resíduo de um teste (ou de uma sincronização real rodada à
    # mão) vazaria pro próximo.
    cache.delete(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    yield
    cache.delete(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)


class _ThreadFalsaSincrona:
    # Função Objetivo: substitui threading.Thread por execução imediata,
    # no mesmo thread do teste — sem isso, o teste precisaria de
    # sleep/polling pra esperar uma thread de verdade terminar (lento e
    # instável). start() já roda a função-alvo inteira até o fim.
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class _ThreadingFalsoSincrono:
    Thread = _ThreadFalsaSincrona


class _ThreadFalsaNaoDeveriaSerCriada:
    # Função Objetivo: prova de forma forte que nenhuma thread nova foi
    # aberta — instanciar já derruba o teste, não só chamar start().
    def __init__(self, *args, **kwargs):
        raise AssertionError('threading.Thread não deveria ser instanciado quando a sincronização já está "rodando".')


class _ThreadingFalsoBloqueado:
    Thread = _ThreadFalsaNaoDeveriaSerCriada


def _url_sincronizar():
    return reverse('agenda_videos_portal_drive_sincronizar')


def _url_status():
    return reverse('agenda_videos_portal_drive_sincronizar_status')


def _url_lista():
    return reverse('agenda_videos_portal_drive')


def _definir_empresa_na_sessao(client, empresa):
    sessao = client.session
    sessao['empresa_ativa'] = empresa
    sessao.save()


def _criar_produto(sku, ean, marca='Marca Teste'):
    return Produto.objects.create(ean=ean, sku=sku, titulo='Produto Teste', marca=marca)


# ---------------------------------------------------------------------
# view_portal_drive_sincronizar (POST) — disparo e idempotência
# ---------------------------------------------------------------------

def test_post_quando_ocioso_dispara_sincronizacao_e_retorna_estado_capturado(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoSincrono)
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', lambda callback_progresso=None: ([], []))

    # Exercise:
    resposta = client.post(_url_sincronizar())

    # Assert:
    corpo = resposta.json()
    estado_final_no_cache = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    esperado_resposta = {'status': 'rodando', 'etapa': 'iniciando', 'processados': 0, 'total': None}
    passou = (
        resposta.status_code == 200
        and corpo == esperado_resposta
        and estado_final_no_cache is not None
        and estado_final_no_cache['status'] == 'concluido'
    )
    registrar_resultado(
        tabela_resultados, teste='POST ocioso → dispara a thread, responde com o estado capturado antes dela rodar',
        entrada='cache vazio; threading.Thread substituído por execução síncrona',
        esperado=f'resposta == {esperado_resposta}; cache, após a thread terminar, mostra status=concluido',
        motivo='A view devolve a "foto" do estado local no momento do disparo, nunca uma releitura do cache — mesmo a thread (síncrona no teste) já tendo terminado quando a resposta é montada',
        obtido=f'status_code={resposta.status_code}, corpo={corpo}, cache_final={estado_final_no_cache}',
        passou=passou,
    )
    assert passou


def test_post_quando_ja_rodando_nao_dispara_nova_thread_nem_chama_verificacao(client, tabela_resultados, monkeypatch):
    # Setup:
    estado_ja_rodando = {'status': 'rodando', 'etapa': 'atualizando_produtos', 'processados': 3, 'total': 10}
    cache.set(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, estado_ja_rodando, timeout=600)
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoBloqueado)

    def _nao_deveria_ser_chamada(callback_progresso=None):
        raise AssertionError('verificar_todos_no_drive não deveria ser chamado quando já está "rodando".')
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', _nao_deveria_ser_chamada)

    # Exercise:
    resposta = client.post(_url_sincronizar())

    # Assert:
    corpo = resposta.json()
    estado_no_cache_depois = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = resposta.status_code == 200 and corpo == estado_ja_rodando and estado_no_cache_depois == estado_ja_rodando
    registrar_resultado(
        tabela_resultados, teste='POST com sincronização já "rodando" → devolve o mesmo estado, sem iniciar 2ª thread',
        entrada=f'cache pré-existente: {estado_ja_rodando}',
        esperado=f'resposta == {estado_ja_rodando}; cache inalterado; threading.Thread nunca instanciado',
        motivo='Botão único — 2 cliques em sequência não podem rodar 2 sincronizações ao mesmo tempo',
        obtido=f'status_code={resposta.status_code}, corpo={corpo}, cache_depois={estado_no_cache_depois}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_portal_drive_sincronizar_status (GET) — leitura pura, sem side-effect
# ---------------------------------------------------------------------

def test_status_le_o_que_esta_no_cache_quando_esta_rodando(client, tabela_resultados):
    # Setup:
    estado = {'status': 'rodando', 'etapa': 'atualizando_produtos', 'processados': 5, 'total': 12}
    cache.set(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, estado, timeout=600)

    # Exercise:
    resposta = client.get(_url_status())

    # Assert:
    corpo = resposta.json()
    passou = resposta.status_code == 200 and corpo == estado
    registrar_resultado(
        tabela_resultados, teste='GET status com cache populado → devolve exatamente o que está no cache',
        entrada=f'cache = {estado}', esperado=f'resposta == {estado}',
        motivo='Endpoint de polling é leitura pura, sem side-effect — o navegador confia nisso a cada 1s',
        obtido=f'status_code={resposta.status_code}, corpo={corpo}',
        passou=passou,
    )
    assert passou


def test_status_retorna_ocioso_quando_cache_vazio(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url_status())

    # Assert:
    corpo = resposta.json()
    passou = resposta.status_code == 200 and corpo == {'status': 'ocioso'}
    registrar_resultado(
        tabela_resultados, teste='GET status sem nada no cache → "ocioso"',
        entrada='cache vazio', esperado="{'status': 'ocioso'}",
        motivo='Nenhuma sincronização foi disparada ainda nesta "vida" do cache',
        obtido=f'status_code={resposta.status_code}, corpo={corpo}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# _rodar_sincronizacao_portal_drive_em_thread — desfechos gravados no cache
# ---------------------------------------------------------------------

def test_thread_aplica_a_empresa_ativa_capturada_na_requisicao_antes_de_verificar(client, tabela_resultados, monkeypatch):
    # Setup: troca a empresa ativa da sessão pra SAMVALE (a rota real que o
    # EmpresaMiddleware usa) — o padrão é MAGAZINE, então isso só passa se
    # a empresa de verdade for propagada pra dentro da "thread".
    _definir_empresa_na_sessao(client, EMPRESA_SAMVALE)
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoSincrono)

    empresa_capturada = {}

    def _verificar_capturando_empresa(callback_progresso=None):
        empresa_capturada['valor'] = obter_empresa_ativa()
        return [], []
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', _verificar_capturando_empresa)

    # Exercise:
    client.post(_url_sincronizar())

    # Assert:
    passou = empresa_capturada.get('valor') == EMPRESA_SAMVALE
    registrar_resultado(
        tabela_resultados, teste='Empresa ativa da requisição (SAMVALE) chega até dentro da thread de sincronização',
        entrada='sessão com empresa_ativa=SAMVALE, requisição passando pelo EmpresaMiddleware',
        esperado='obter_empresa_ativa() dentro da thread == SAMVALE (não MAGAZINE/default, nem None)',
        motivo='Regressão do bug real de 21/08/2026: threading.local() não é herdado por uma thread nova — a view precisa capturar a empresa na thread da requisição e repassar explicitamente como argumento',
        obtido=f'empresa_capturada={empresa_capturada.get("valor")!r}',
        passou=passou,
    )
    assert passou


def test_thread_grava_estado_de_erro_no_cache_quando_verificacao_lanca_excecao(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoSincrono)

    def _verificar_com_falha(callback_progresso=None):
        raise ConnectionError('Falha simulada de rede com o Drive')
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', _verificar_com_falha)

    # Exercise:
    client.post(_url_sincronizar())

    # Assert:
    estado_final = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = estado_final == {'status': 'erro'}
    registrar_resultado(
        tabela_resultados, teste='Exceção dentro da thread → cache grava status=erro (nunca trava em "rodando" pra sempre)',
        entrada='verificar_todos_no_drive lançando ConnectionError',
        esperado="cache == {'status': 'erro'}",
        motivo='try/except cobre a função inteira de propósito — sem isso, uma falha de rede mataria a thread em silêncio e o botão ficaria "rodando" pra sempre aos olhos do usuário',
        obtido=f'estado_final={estado_final}',
        passou=passou,
    )
    assert passou


def test_thread_grava_mensagem_de_sucesso_com_contagem_quando_ha_avanco(client, tabela_resultados, monkeypatch):
    # Setup: 2 produtos avançaram, com 1 e 2 etapas marcadas respectivamente
    # (3 pontos no total) — números escolhidos de propósito pra não bater
    # por coincidência com "quantidade de produtos".
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoSincrono)
    resumo_por_produto = [(1, ['ponto_a']), (2, ['ponto_b', 'ponto_c'])]
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', lambda callback_progresso=None: (resumo_por_produto, []))

    # Exercise:
    client.post(_url_sincronizar())

    # Assert:
    estado_final = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = (
        estado_final is not None
        and estado_final['status'] == 'concluido'
        and estado_final['tipo_mensagem'] == 'success'
        and '2 produto(s)' in estado_final['mensagem']
        and '3 ponto(s)' in estado_final['mensagem']
        and estado_final['aviso_sem_produto'] is None
    )
    registrar_resultado(
        tabela_resultados, teste='2 produtos avançaram (3 pontos no total) → mensagem de sucesso com as contagens certas',
        entrada=f'resumo_por_produto={resumo_por_produto}, sem_produto_no_banco=[]',
        esperado="status=concluido, tipo_mensagem=success, mensagem cita '2 produto(s)' e '3 ponto(s)', aviso_sem_produto=None",
        motivo='total_pontos soma len(etapas_marcadas) de cada produto, não conta produtos',
        obtido=f'estado_final={estado_final}',
        passou=passou,
    )
    assert passou


def test_thread_grava_mensagem_de_info_quando_nao_ha_avanco_nenhum(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoSincrono)
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', lambda callback_progresso=None: ([], []))

    # Exercise:
    client.post(_url_sincronizar())

    # Assert:
    estado_final = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = (
        estado_final is not None
        and estado_final['status'] == 'concluido'
        and estado_final['tipo_mensagem'] == 'info'
        and 'nenhum produto' in estado_final['mensagem']
        and estado_final['aviso_sem_produto'] is None
    )
    registrar_resultado(
        tabela_resultados, teste='Nenhum produto avançou → mensagem tipo info (não success), sem aviso',
        entrada='resumo_por_produto=[], sem_produto_no_banco=[]',
        esperado="status=concluido, tipo_mensagem=info, mensagem cita 'nenhum produto', aviso_sem_produto=None",
        motivo='Sincronização rodou e terminou bem — só não achou nada novo pra avançar, não é erro',
        obtido=f'estado_final={estado_final}',
        passou=passou,
    )
    assert passou


def test_thread_grava_aviso_quando_ha_pasta_no_drive_sem_produto_correspondente(client, tabela_resultados, monkeypatch):
    # Setup:
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoSincrono)
    sem_produto_no_banco = ['7891234500000', '7891234500001']
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', lambda callback_progresso=None: ([], sem_produto_no_banco))

    # Exercise:
    client.post(_url_sincronizar())

    # Assert:
    estado_final = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = (
        estado_final is not None
        and estado_final['aviso_sem_produto'] is not None
        and '2 pasta(s)' in estado_final['aviso_sem_produto']
    )
    registrar_resultado(
        tabela_resultados, teste='2 EANs órfãos no Drive → aviso_sem_produto com a contagem certa',
        entrada=f'sem_produto_no_banco={sem_produto_no_banco}',
        esperado="aviso_sem_produto cita '2 pasta(s)'",
        motivo='Aviso separado da mensagem principal — não impede o "concluído com sucesso", só alerta',
        obtido=f'estado_final={estado_final}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# view_portal_drive (GET) — consumo do estado final do cache em messages
# ---------------------------------------------------------------------

def test_lista_consome_estado_concluido_com_sucesso_mostra_mensagens_e_limpa_cache(client, tabela_resultados):
    # Setup:
    cache.set(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, {
        'status': 'concluido',
        'mensagem': 'Sincronização concluída — 1 produto(s) avançaram, 1 ponto(s) marcado(s) no total.',
        'tipo_mensagem': 'success',
        'aviso_sem_produto': '1 pasta(s) no Drive não correspondem a nenhum produto do banco.',
    }, timeout=600)

    # Exercise:
    resposta = client.get(_url_lista())

    # Assert:
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    cache_depois = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = (
        resposta.status_code == 200
        and any('1 produto(s) avançaram' in m for m in mensagens)
        and any('1 pasta(s)' in m for m in mensagens)
        and cache_depois is None
    )
    registrar_resultado(
        tabela_resultados, teste='GET da lista com estado "concluido" (sucesso + aviso) no cache → 2 mensagens e cache limpo',
        entrada='cache com status=concluido, tipo_mensagem=success e aviso_sem_produto preenchido',
        esperado='mensagem principal + mensagem de aviso nas messages do Django; cache apagado depois de consumido',
        motivo='O resultado da sincronização só é mostrado 1 vez, no próximo GET — se o cache não fosse limpo, recarregar a página mostraria a mesma mensagem de novo',
        obtido=f'mensagens={mensagens}, cache_depois={cache_depois}',
        passou=passou,
    )
    assert passou


def test_lista_consome_estado_de_erro_mostra_mensagem_generica_e_limpa_cache(client, tabela_resultados):
    # Setup:
    cache.set(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, {'status': 'erro'}, timeout=600)

    # Exercise:
    resposta = client.get(_url_lista())

    # Assert:
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    cache_depois = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = (
        resposta.status_code == 200
        and any('Não foi possível conectar ao Google Drive' in m for m in mensagens)
        and cache_depois is None
    )
    registrar_resultado(
        tabela_resultados, teste='GET da lista com estado "erro" no cache → mensagem genérica de erro e cache limpo',
        entrada='cache com status=erro (sem mensagem/tipo_mensagem — o dict de erro não carrega esses campos)',
        esperado='mensagem genérica de erro nas messages do Django; cache apagado depois',
        motivo="Estado de erro não guarda 'mensagem'/'tipo_mensagem' (só status=erro) — a view precisa ter uma mensagem fixa própria pra esse caso, sem tentar ler chaves que não existem",
        obtido=f'mensagens={mensagens}, cache_depois={cache_depois}',
        passou=passou,
    )
    assert passou


def test_lista_nao_mostra_mensagem_quando_ainda_esta_rodando(client, tabela_resultados):
    # Setup:
    estado_rodando = {'status': 'rodando', 'etapa': 'atualizando_produtos', 'processados': 4, 'total': 9}
    cache.set(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, estado_rodando, timeout=600)

    # Exercise:
    resposta = client.get(_url_lista())

    # Assert:
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    cache_depois = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = resposta.status_code == 200 and mensagens == [] and cache_depois == estado_rodando
    registrar_resultado(
        tabela_resultados, teste='GET da lista com sincronização ainda "rodando" → nenhuma mensagem, cache intocado',
        entrada=f'cache = {estado_rodando}',
        esperado='nenhuma message; cache continua igual (a barra de progresso é quem mostra isso, via polling, não uma message)',
        motivo='Só "concluido" e "erro" são desfechos finais — "rodando" não deve ser consumido/apagado do cache nesse GET',
        obtido=f'mensagens={mensagens}, cache_depois={cache_depois}',
        passou=passou,
    )
    assert passou


# ---------------------------------------------------------------------
# Cobertura extra — progresso intermediário e paginação/por_pagina real
# ---------------------------------------------------------------------

def test_thread_publica_progresso_intermediario_no_cache_durante_a_execucao(client, tabela_resultados, monkeypatch):
    # Setup: o fake de verificar_todos_no_drive chama callback_progresso 2
    # vezes, lendo o cache logo depois de cada chamada — é isso que prova
    # que cada etapa intermediária é publicada em tempo real, não só o
    # estado inicial e o final.
    monkeypatch.setattr(views_module, 'threading', _ThreadingFalsoSincrono)
    estados_capturados = []

    def _verificar_com_progresso(callback_progresso=None):
        callback_progresso('lendo_drive', 0, None)
        estados_capturados.append(cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE))
        callback_progresso('atualizando_produtos', 7, 20)
        estados_capturados.append(cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE))
        return [], []
    monkeypatch.setattr(views_module, 'verificar_todos_no_drive', _verificar_com_progresso)

    # Exercise:
    client.post(_url_sincronizar())

    # Assert:
    esperado = [
        {'status': 'rodando', 'etapa': 'lendo_drive', 'processados': 0, 'total': None},
        {'status': 'rodando', 'etapa': 'atualizando_produtos', 'processados': 7, 'total': 20},
    ]
    passou = estados_capturados == esperado
    registrar_resultado(
        tabela_resultados, teste='callback_progresso publica cada etapa intermediária no cache, em tempo real',
        entrada="2 chamadas de callback_progresso: ('lendo_drive', 0, None) e ('atualizando_produtos', 7, 20)",
        esperado=f'{esperado}',
        motivo='É essa gravação intermediária que alimenta a barra de progresso real consultada por polling — sem ela, o navegador só veria o estado inicial e depois o final, nada no meio',
        obtido=f'{estados_capturados}',
        passou=passou,
    )
    assert passou


def test_lista_consome_estado_concluido_sem_aviso_mostra_so_a_mensagem_principal(client, tabela_resultados):
    # Setup:
    cache.set(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, {
        'status': 'concluido',
        'mensagem': 'Sincronização concluída — nenhum produto teve ponto novo pra avançar.',
        'tipo_mensagem': 'info',
        'aviso_sem_produto': None,
    }, timeout=600)

    # Exercise:
    resposta = client.get(_url_lista())

    # Assert:
    mensagens = [str(m) for m in get_messages(resposta.wsgi_request)]
    cache_depois = cache.get(views_module.CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    passou = (
        resposta.status_code == 200
        and mensagens == ['Sincronização concluída — nenhum produto teve ponto novo pra avançar.']
        and cache_depois is None
    )
    registrar_resultado(
        tabela_resultados, teste='GET da lista com "concluido" SEM aviso_sem_produto → só a mensagem principal, nenhuma de aviso',
        entrada='cache com status=concluido, tipo_mensagem=info, aviso_sem_produto=None',
        esperado='exatamente 1 mensagem (a principal); cache apagado depois',
        motivo="if estado_sincronizacao.get('aviso_sem_produto') precisa ser 'falsy' pra pular messages.warning() — sem esse cenário, esse desvio do branch nunca é exercitado",
        obtido=f'mensagens={mensagens}, cache_depois={cache_depois}',
        passou=passou,
    )
    assert passou


def test_lista_com_por_pagina_invalido_cai_no_padrao_de_25_sem_quebrar(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url_lista(), {'por_pagina': 'abc'})

    # Assert:
    por_pagina_usado = resposta.context['pagina'].paginator.per_page
    passou = resposta.status_code == 200 and por_pagina_usado == 25
    registrar_resultado(
        tabela_resultados, teste='por_pagina=abc (não numérico) → cai no padrão 25, sem quebrar a página',
        entrada='querystring ?por_pagina=abc', esperado='paginator.per_page == 25',
        motivo="int('abc') lança ValueError — o except precisa segurar isso e usar o padrão, não deixar a página inteira quebrar por causa de 1 parâmetro de URL malformado",
        obtido=f'status_code={resposta.status_code}, por_pagina_usado={por_pagina_usado}',
        passou=passou,
    )
    assert passou


def test_lista_calcula_arquivos_presentes_e_percentual_para_produtos_sem_avaliacao_previa(client, tabela_resultados):
    # Setup: produto sem nenhum snapshot do Drive — _contar_arquivos_presentes
    # devolve 0 nesse caso, sem quebrar. Sem filtro de progresso (fica no
    # branch "produtos_para_paginar = produtos", que NÃO pré-calcula
    # arquivos_presentes) — é só no loop de paginação que esse cálculo
    # precisa acontecer pela 1ª vez.
    _criar_produto(sku='SKU-SINC-001', ean='7891111100001')

    # Exercise:
    resposta = client.get(_url_lista())

    # Assert:
    produtos_da_pagina = list(resposta.context['pagina'].object_list)
    produto_testado = produtos_da_pagina[0] if produtos_da_pagina else None
    passou = (
        resposta.status_code == 200
        and produto_testado is not None
        and produto_testado.arquivos_presentes == 0
        and produto_testado.arquivos_total == views_module.TOTAL_ARQUIVOS_ESPERADOS
        and produto_testado.arquivos_percentual == 0
    )
    registrar_resultado(
        tabela_resultados, teste='Produto sem snapshot, listado sem filtro de progresso → arquivos_presentes/total/percentual calculados no loop de paginação',
        entrada='1 produto sem SnapshotArquivosDrive, GET sem parâmetro "progresso" (fica em "todos")',
        esperado=f'arquivos_presentes=0, arquivos_total={views_module.TOTAL_ARQUIVOS_ESPERADOS}, arquivos_percentual=0',
        motivo='Esse cálculo só é pulado quando já veio pronto do branch de progresso pendente/completo — aqui não veio, então o loop de paginação precisa fazer isso na primeira vez (hasattr check)',
        obtido=f'presentes={getattr(produto_testado, "arquivos_presentes", None)}, total={getattr(produto_testado, "arquivos_total", None)}, percentual={getattr(produto_testado, "arquivos_percentual", None)}',
        passou=passou,
    )
    assert passou