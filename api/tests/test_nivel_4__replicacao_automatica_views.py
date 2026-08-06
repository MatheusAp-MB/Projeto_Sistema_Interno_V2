# api/tests/test_nivel_4__replicacao_automatica_views.py

# Função Objetivo: Testa as 5 views de api/replicacao_automatica — Nível 4
# (HTTP real), primeira rodada de testes desta app. Puro banco: nenhuma
# chamada real a Drive ou Mercado Livre, só lê VariacaoAnuncioMercadoLivre
# (dado já sincronizado) e escreve em ItemExecucaoReplicacao/
# ExecucaoReplicacaoAutomatica/CicloVideo. Autenticação por TOKEN no
# cabeçalho (Authorization: Bearer ...), não por sessão — diferente de toda
# a suíte de agenda_videos.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import json

import pytest
from django.conf import settings
from django.urls import reverse

from produtos.models import Produto
from mercado_livre.models import AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre
from agenda_videos.models import (
    CicloVideo, Fase, StatusPostagem,
    ExecucaoReplicacaoAutomatica, StatusExecucao,
    ItemExecucaoReplicacao, StatusItemExecucaoReplicacao,
)
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db

TITULO_CAMADA = 'Nível 4 — api/replicacao_automatica: as 5 views via HTTP (token, puro banco)'

CABECALHO_TOKEN_VALIDO = {'Authorization': f'Bearer {settings.AGENTE_TOKEN}'}
CABECALHO_TOKEN_INVALIDO = {'Authorization': 'Bearer token-errado'}


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste', marca='Marca Teste')


def _criar_mlb(produto, mlb):
    anuncio = AnuncioMercadoLivre.objects.create(mlb=mlb)
    VariacaoAnuncioMercadoLivre.objects.create(anuncio=anuncio, variacao_id='1', produto=produto)


def _criar_execucao_com_item(produto):
    execucao = ExecucaoReplicacaoAutomatica.objects.create()
    item = ItemExecucaoReplicacao.objects.create(execucao=execucao, produto=produto, ordem=1)
    return execucao, item


def _url_listar_itens(execucao_id):
    return reverse('api_replicacao_listar_itens', args=[execucao_id])


def _url_marcar_concluido(item_id):
    return reverse('api_replicacao_marcar_concluido', args=[item_id])


def _url_marcar_falhou(item_id):
    return reverse('api_replicacao_marcar_falhou', args=[item_id])


def _url_heartbeat(execucao_id):
    return reverse('api_replicacao_heartbeat', args=[execucao_id])


def _url_finalizar_execucao(execucao_id):
    return reverse('api_replicacao_finalizar_execucao', args=[execucao_id])


# ===================================================================
# view_listar_itens
# ===================================================================

def test_listar_itens_sem_token_devolve_403(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-001')
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.get(_url_listar_itens(execucao.id), headers=CABECALHO_TOKEN_INVALIDO)

    # Assert:
    passou = resposta.status_code == 403
    registrar_resultado(
        tabela_resultados, teste='listar_itens sem token válido',
        entrada='Authorization: Bearer token-errado', esperado='403',
        motivo='API do agente é por token, nunca por sessão de navegador',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_listar_itens_devolve_mlb_e_outros_mlbs_corretos(client, tabela_resultados):
    # Setup: produto com 2 MLBs — o que já recebeu o clip (mlb_atual) e 1 outro.
    produto = _criar_produto('SKU-002')
    _criar_mlb(produto, 'MLB001')
    _criar_mlb(produto, 'MLB002')
    execucao, item = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.get(_url_listar_itens(execucao.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    corpo = resposta.json()
    item_resultado = corpo['itens'][0]
    passou = (
        resposta.status_code == 200 and item_resultado['mlb'] in ('MLB001', 'MLB002')
        and len(item_resultado['outros_mlbs']) == 1
    )
    registrar_resultado(
        tabela_resultados, teste='listar_itens devolve mlb + outros_mlbs (exclui o próprio)',
        entrada='produto com 2 VariacaoAnuncioMercadoLivre', esperado='mlb = 1 dos 2, outros_mlbs = o outro',
        motivo='_obter_outros_mlbs precisa excluir o MLB que já recebeu o clip',
        obtido=f'mlb={item_resultado["mlb"]}, outros_mlbs={item_resultado["outros_mlbs"]}',
        passou=passou,
    )
    assert passou


def test_listar_itens_produto_sem_variacao_mlb_none(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-003')
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.get(_url_listar_itens(execucao.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    item_resultado = resposta.json()['itens'][0]
    passou = item_resultado['mlb'] is None and item_resultado['outros_mlbs'] == []
    registrar_resultado(
        tabela_resultados, teste='listar_itens produto sem nenhuma VariacaoAnuncioMercadoLivre',
        entrada='produto sem MLB vinculado', esperado='mlb=None, outros_mlbs=[]',
        motivo='obter_mlb_do_produto() precisa devolver None sem quebrar, não estourar exceção',
        obtido=f'mlb={item_resultado["mlb"]}, outros_mlbs={item_resultado["outros_mlbs"]}',
        passou=passou,
    )
    assert passou


# ===================================================================
# view_marcar_concluido
# ===================================================================

def test_marcar_concluido_sem_token_devolve_403(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_marcar_concluido(999999), headers=CABECALHO_TOKEN_INVALIDO)

    # Assert:
    passou = resposta.status_code == 403
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido sem token válido',
        entrada='Authorization: Bearer token-errado', esperado='403',
        motivo='Guard de token precisa vir antes de qualquer outra checagem',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_item_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.post(_url_marcar_concluido(999999), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido item_id inexistente',
        entrada='item_id=999999', esperado='404',
        motivo='ItemExecucaoReplicacao precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_produto_sem_ciclo_devolve_400(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-004')
    _, item = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.post(_url_marcar_concluido(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido produto sem nenhum CicloVideo',
        entrada='produto sem ciclo', esperado='400 — estado inválido',
        motivo='Não existe "postagem aprovada" pra confirmar replicação sem ciclo',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_ciclo_nao_aprovado_devolve_400(client, tabela_resultados):
    # Setup: ciclo existe, mas ainda não está Aprovado (ex: Aguardando aprovação).
    produto = _criar_produto('SKU-005')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1,
        status=StatusPostagem.AGUARDANDO_APROVACAO,
    )
    _, item = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.post(_url_marcar_concluido(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido ciclo ainda Aguardando aprovação (não Aprovado)',
        entrada='ciclo.status=AGUARDANDO_APROVACAO', esperado='400 — estado inválido',
        motivo='Só pode confirmar replicação de uma postagem já Aprovada',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_sucesso_marca_item_e_replica_o_ciclo(client, tabela_resultados):
    # Setup: fase Simples de propósito — marcar_replicado() não dispara
    # criar_proximo() pra essa fase, evitando depender da régua de fases
    # (já testada à parte, não precisa duplicar aqui).
    produto = _criar_produto('SKU-006')
    ciclo = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, status=StatusPostagem.APROVADO,
    )
    _, item = _criar_execucao_com_item(produto)
    corpo = {'mlbs_replicados': ['MLB001', 'MLB002'], 'mlbs_nao_encontrados': ['MLB003']}

    # Exercise:
    resposta = client.post(
        _url_marcar_concluido(item.id), data=json.dumps(corpo), content_type='application/json',
        headers=CABECALHO_TOKEN_VALIDO,
    )

    # Assert:
    item.refresh_from_db()
    ciclo.refresh_from_db()
    passou = (
        resposta.status_code == 200 and item.status == StatusItemExecucaoReplicacao.CONCLUIDO
        and item.finalizado_em is not None and ciclo.status == StatusPostagem.REPLICADO
        and ciclo.mlbs_replicados == ['MLB001', 'MLB002'] and ciclo.mlbs_nao_encontrados == ['MLB003']
    )
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido sucesso — item concluído + CicloVideo replicado de verdade',
        entrada='ciclo Aprovado + corpo com mlbs_replicados/mlbs_nao_encontrados', esperado='item=Concluído, ciclo=Replicado, MLBs salvos no ciclo',
        motivo='marcar_replicado() é a única fonte da regra de negócio — a view nunca deve reimplementar isso',
        obtido=f'item.status={item.status}, ciclo.status={ciclo.status}, mlbs_replicados={ciclo.mlbs_replicados}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_corpo_sem_json_valido_usa_listas_vazias(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-007')
    ciclo = CicloVideo.objects.create(
        produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1, status=StatusPostagem.APROVADO,
    )
    _, item = _criar_execucao_com_item(produto)

    # Exercise: corpo vazio/inválido, mas o ciclo já está Aprovado — ainda deve suceder.
    resposta = client.post(_url_marcar_concluido(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    ciclo.refresh_from_db()
    passou = resposta.status_code == 200 and ciclo.mlbs_replicados == [] and ciclo.mlbs_nao_encontrados == []
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido sem corpo JSON válido',
        entrada='sem corpo (JSONDecodeError)', esperado='cai no padrão [] / [], ainda marca concluído',
        motivo='Corpo malformado não pode impedir a confirmação de uma postagem já Aprovada',
        obtido=f'status={resposta.status_code}, mlbs_replicados={ciclo.mlbs_replicados}',
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
        motivo='Mesmo guard de token de toda a API',
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
        motivo='ItemExecucaoReplicacao precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_falhou_sucesso_grava_mensagem(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-008')
    _, item = _criar_execucao_com_item(produto)
    corpo = {'mensagem': 'MLB não encontrado na busca do ML.'}

    # Exercise:
    resposta = client.post(
        _url_marcar_falhou(item.id), data=json.dumps(corpo), content_type='application/json',
        headers=CABECALHO_TOKEN_VALIDO,
    )

    # Assert:
    item.refresh_from_db()
    passou = (
        resposta.status_code == 200 and item.status == StatusItemExecucaoReplicacao.FALHOU
        and item.mensagem_erro == 'MLB não encontrado na busca do ML.' and item.finalizado_em is not None
    )
    registrar_resultado(
        tabela_resultados, teste='marcar_falhou sucesso — grava status e mensagem reais',
        entrada='corpo com mensagem de erro real', esperado='item.status=Falhou, mensagem gravada, finalizado_em preenchido',
        motivo='Mensagem real precisa chegar até o banco, não só o status',
        obtido=f'status_item={item.status}, mensagem={item.mensagem_erro}',
        passou=passou,
    )
    assert passou


def test_marcar_falhou_corpo_sem_json_valido_usa_mensagem_padrao(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-008B')
    _, item = _criar_execucao_com_item(produto)

    # Exercise: sem corpo nenhum → json.loads(b'') estoura JSONDecodeError.
    resposta = client.post(_url_marcar_falhou(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    item.refresh_from_db()
    passou = resposta.status_code == 200 and item.mensagem_erro == 'Falha não especificada.'
    registrar_resultado(
        tabela_resultados, teste='marcar_falhou sem corpo JSON válido',
        entrada='sem corpo (JSONDecodeError)', esperado='mensagem_erro cai no padrão "Falha não especificada."',
        motivo='Corpo malformado não pode impedir o registro da falha, só perde o detalhe da mensagem',
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
        motivo='Mesmo guard de token de toda a API',
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
        motivo='ExecucaoReplicacaoAutomatica precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_heartbeat_sucesso_atualiza_timestamp_e_status(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-009')
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
        entrada='execução recém-criada (status padrão AGUARDANDO_INICIO)', esperado='status=RODANDO, ultimo_heartbeat_agente preenchido',
        motivo='É o único jeito do Django saber que o agente ainda está vivo',
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
        motivo='Mesmo guard de token de toda a API',
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
        motivo='ExecucaoReplicacaoAutomatica precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_finalizar_execucao_sucesso_sem_cancelada_marca_concluido(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-010')
    execucao, _ = _criar_execucao_com_item(produto)

    # Exercise:
    resposta = client.post(_url_finalizar_execucao(execucao.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    execucao.refresh_from_db()
    passou = (
        resposta.status_code == 200 and execucao.status == StatusExecucao.CONCLUIDO
        and execucao.finalizado_em is not None
    )
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
    produto = _criar_produto('SKU-011')
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
        motivo='Distingue fim normal de cancelamento — usado no dashboard/relatório depois',
        obtido=f'status={execucao.status}',
        passou=passou,
    )
    assert passou