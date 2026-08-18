# api/tests/test_nivel_4__postagem_automatica_views_sem_drive.py

# Função Objetivo: Testa as 4 rotas de api/postagem_automatica que NÃO tocam
# Drive — Nível 4 (HTTP real), puro banco. view_baixar_video e
# view_marcar_concluido (as 2 que usam Drive de verdade) ficam em arquivo
# separado. Mesmo padrão de autenticação por token da API de replicação.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import json

import pytest
from django.conf import settings
from django.urls import reverse

from produtos.models import Produto
from mercado_livre.models import AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre
from agenda_videos.models import (
    CicloVideo, Fase,
    ExecucaoPostagemAutomatica, StatusExecucao,
    ItemExecucaoPostagem, StatusItemExecucao,
)
from django.utils import timezone
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 — api/postagem_automatica (sem Drive): listar_itens, marcar_falhou, heartbeat, finalizar_execucao'

CABECALHO_TOKEN_VALIDO = {'Authorization': f'Bearer {settings.AGENTE_TOKEN}'}
CABECALHO_TOKEN_INVALIDO = {'Authorization': 'Bearer token-errado'}


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste', marca='Marca Teste')


def _criar_execucao_com_item(produto):
    execucao = ExecucaoPostagemAutomatica.objects.create()
    item = ItemExecucaoPostagem.objects.create(execucao=execucao, produto=produto, ordem=1)
    return execucao, item


def _url_listar_itens(execucao_id):
    return reverse('api_postagem_listar_itens', args=[execucao_id])


def _url_marcar_falhou(item_id):
    return reverse('api_postagem_marcar_falhou', args=[item_id])


def _url_heartbeat(execucao_id):
    return reverse('api_postagem_heartbeat', args=[execucao_id])


def _url_finalizar_execucao(execucao_id):
    return reverse('api_postagem_finalizar_execucao', args=[execucao_id])


# ===================================================================
# view_listar_itens
# ===================================================================

def test_listar_itens_sem_token_devolve_403(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-101')
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.get(_url_listar_itens(execucao.id), headers=CABECALHO_TOKEN_INVALIDO)

    # Assert:
    passou = resposta.status_code == 403
    registrar_resultado(
        tabela_resultados, teste='listar_itens sem token válido',
        entrada='Authorization: Bearer token-errado', esperado='403',
        motivo='Mesmo guard de token de toda a API do agente',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_listar_itens_produto_nao_postou_hoje(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-102')
    anuncio = AnuncioMercadoLivre.objects.create(mlb='MLB0102')
    VariacaoAnuncioMercadoLivre.objects.create(anuncio=anuncio, variacao_id='1', produto=produto)
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.get(_url_listar_itens(execucao.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    item_resultado = resposta.json()['itens'][0]
    passou = resposta.status_code == 200 and item_resultado['mlb'] == 'MLB0102' and item_resultado['ja_postado_hoje'] is False
    registrar_resultado(
        tabela_resultados, teste='listar_itens produto que ainda não postou hoje',
        entrada='sem nenhum CicloVideo aguardando_aprovacao hoje', esperado='mlb correto, ja_postado_hoje=False',
        motivo='Caminho normal — a maioria dos itens da fila não postou ainda',
        obtido=f'mlb={item_resultado["mlb"]}, ja_postado_hoje={item_resultado["ja_postado_hoje"]}',
        passou=passou,
    )
    assert passou


def test_listar_itens_produto_ja_postou_hoje(client, tabela_resultados):
    # Setup: confere "já postou hoje" em TEMPO REAL, não só na hora de criar
    # a lista — cobre alguém postando manualmente no meio do caminho.
    produto = _criar_produto('SKU-103')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        status='aguardando_aprovacao', aguardando_aprovacao_em=timezone.now(),
    )
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.get(_url_listar_itens(execucao.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    item_resultado = resposta.json()['itens'][0]
    passou = item_resultado['ja_postado_hoje'] is True
    registrar_resultado(
        tabela_resultados, teste='listar_itens produto que já postou hoje (checagem em tempo real)',
        entrada='CicloVideo com aguardando_aprovacao_em=agora', esperado='ja_postado_hoje=True',
        motivo='Protege contra postar manualmente 1 produto que também está na fila automática',
        obtido=f'ja_postado_hoje={item_resultado["ja_postado_hoje"]}',
        passou=passou,
    )
    assert passou


# ===================================================================
# view_marcar_falhou
# ===================================================================

def test_marcar_falhou_sem_token_devolve_403(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_marcar_falhou(999999), headers=CABECALHO_TOKEN_INVALIDO)

    # Assert:
    passou = resposta.status_code == 403
    registrar_resultado(
        tabela_resultados, teste='marcar_falhou sem token válido',
        entrada='Authorization: Bearer token-errado', esperado='403',
        motivo='Mesmo guard de token',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_falhou_item_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_marcar_falhou(999999), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='marcar_falhou item_id inexistente',
        entrada='item_id=999999', esperado='404',
        motivo='ItemExecucaoPostagem precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_falhou_sucesso_grava_mensagem(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-104')
    _, item = _criar_execucao_com_item(produto)
    corpo = {'mensagem': 'Checkpoint 1 falhou — página não carregou.'}

    # Exercise:
    resposta = client.post(
        _url_marcar_falhou(item.id), data=json.dumps(corpo), content_type='application/json',
        headers=CABECALHO_TOKEN_VALIDO,
    )

    # Assert:
    item.refresh_from_db()
    passou = (
        resposta.status_code == 200 and item.status == StatusItemExecucao.FALHOU
        and item.mensagem_erro == 'Checkpoint 1 falhou — página não carregou.'
    )
    registrar_resultado(
        tabela_resultados, teste='marcar_falhou sucesso — grava status e mensagem reais',
        entrada='corpo com mensagem de erro real', esperado='item.status=Falhou, mensagem gravada',
        motivo='Mensagem real precisa chegar até o banco',
        obtido=f'status_item={item.status}, mensagem={item.mensagem_erro}',
        passou=passou,
    )
    assert passou


def test_marcar_falhou_corpo_sem_json_valido_usa_mensagem_padrao(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-105')
    _, item = _criar_execucao_com_item(produto)

    # Exercise: sem corpo nenhum.
    resposta = client.post(_url_marcar_falhou(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    item.refresh_from_db()
    passou = resposta.status_code == 200 and item.mensagem_erro == 'Falha não especificada.'
    registrar_resultado(
        tabela_resultados, teste='marcar_falhou sem corpo JSON válido',
        entrada='sem corpo (JSONDecodeError)', esperado='mensagem_erro cai no padrão "Falha não especificada."',
        motivo='Corpo malformado não pode impedir o registro da falha',
        obtido=f'mensagem_erro={item.mensagem_erro!r}',
        passou=passou,
    )
    assert passou


# ===================================================================
# view_heartbeat
# ===================================================================

def test_heartbeat_sem_token_devolve_403(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_heartbeat(999999), headers=CABECALHO_TOKEN_INVALIDO)

    # Assert:
    passou = resposta.status_code == 403
    registrar_resultado(
        tabela_resultados, teste='heartbeat sem token válido',
        entrada='Authorization: Bearer token-errado', esperado='403',
        motivo='Mesmo guard de token',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_heartbeat_execucao_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_heartbeat(999999), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='heartbeat execucao_id inexistente',
        entrada='execucao_id=999999', esperado='404',
        motivo='ExecucaoPostagemAutomatica precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_heartbeat_sucesso_atualiza_timestamp_e_status(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-106')
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.post(_url_heartbeat(execucao.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    execucao.refresh_from_db()
    passou = (
        resposta.status_code == 200 and execucao.ultimo_heartbeat_agente is not None
        and execucao.status == StatusExecucao.RODANDO
    )
    registrar_resultado(
        tabela_resultados, teste='heartbeat sucesso — atualiza timestamp e status RODANDO',
        entrada='execução recém-criada', esperado='status=RODANDO, heartbeat preenchido',
        motivo='Único jeito do Django saber que o agente ainda está vivo',
        obtido=f'status={execucao.status}, heartbeat={execucao.ultimo_heartbeat_agente}',
        passou=passou,
    )
    assert passou


# ===================================================================
# view_finalizar_execucao
# ===================================================================

def test_finalizar_execucao_sem_token_devolve_403(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_finalizar_execucao(999999), headers=CABECALHO_TOKEN_INVALIDO)

    # Assert:
    passou = resposta.status_code == 403
    registrar_resultado(
        tabela_resultados, teste='finalizar_execucao sem token válido',
        entrada='Authorization: Bearer token-errado', esperado='403',
        motivo='Mesmo guard de token',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_finalizar_execucao_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_finalizar_execucao(999999), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='finalizar_execucao execucao_id inexistente',
        entrada='execucao_id=999999', esperado='404',
        motivo='ExecucaoPostagemAutomatica precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_finalizar_execucao_sucesso_sem_cancelada_marca_concluido(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-107')
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.post(_url_finalizar_execucao(execucao.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    execucao.refresh_from_db()
    passou = resposta.status_code == 200 and execucao.status == StatusExecucao.CONCLUIDO and execucao.finalizado_em is not None
    registrar_resultado(
        tabela_resultados, teste='finalizar_execucao sem "cancelada" no corpo',
        entrada='corpo vazio', esperado='status=Concluído',
        motivo='Padrão de "cancelada" precisa ser False, nunca None/erro',
        obtido=f'status={execucao.status}',
        passou=passou,
    )
    assert passou


def test_finalizar_execucao_sucesso_com_cancelada_marca_cancelado(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-108')
    execucao, _ = _criar_execucao_com_item(produto)
    corpo = {'cancelada': True}

    # Exercise:
    resposta = client.post(
        _url_finalizar_execucao(execucao.id), data=json.dumps(corpo), content_type='application/json',
        headers=CABECALHO_TOKEN_VALIDO,
    )

    # Assert:
    execucao.refresh_from_db()
    passou = resposta.status_code == 200 and execucao.status == StatusExecucao.CANCELADO
    registrar_resultado(
        tabela_resultados, teste='finalizar_execucao com "cancelada": true',
        entrada='corpo {"cancelada": true}', esperado='status=Cancelado',
        motivo='Distingue fim normal de cancelamento',
        obtido=f'status={execucao.status}',
        passou=passou,
    )
    assert passou