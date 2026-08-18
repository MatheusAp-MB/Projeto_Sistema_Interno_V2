# api/tests/test_nivel_4__postagem_automatica_views_drive_simulado.py

# Função Objetivo: Testa view_baixar_video e view_marcar_concluido — as 2
# rotas de api/postagem_automatica que tocam Drive. Versão SIMULADA (Nível 4):
# LocalizadorArquivosProduto.localizar_arquivos e ArquivadorDrive.baixar_arquivo/
# mover_para_usados são mockados via monkeypatch (borda de rede) — resto da
# cadeia é real (parser real, resolver_arquivo_da_ocorrencia real, banco
# real). A versão REAL (Nível 5, contra o Drive de verdade) fica pra depois —
# view_marcar_concluido move arquivo de verdade no Drive, não é seguro
# testar isso direto em produto real sem uma pasta descartável dedicada.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

import json

import pytest
from django.conf import settings
from django.urls import reverse

from produtos.models import Produto
from agenda_videos.models import (
    CicloVideo, Fase, StatusPostagem, ItemExecucaoPostagem, StatusItemExecucao, ExecucaoPostagemAutomatica,
)
from agenda_videos.funcoes_auxiliares.drive.localizador import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.drive.arquivador import ArquivadorDrive
from testes_apoio.apoio_visual import registrar_resultado

pytestmark = pytest.mark.django_db(databases=['default', 'magazine', 'samvale'])

TITULO_CAMADA = 'Nível 4 (Simulado) — api/postagem_automatica: view_baixar_video / view_marcar_concluido'

CABECALHO_TOKEN_VALIDO = {'Authorization': f'Bearer {settings.AGENTE_TOKEN}'}
CABECALHO_TOKEN_INVALIDO = {'Authorization': 'Bearer token-errado'}


def _criar_produto(sku):
    return Produto.objects.create(ean=f'EAN-{sku}', sku=sku, titulo='Produto Teste', marca='Marca Teste')


def _criar_item(produto):
    execucao = ExecucaoPostagemAutomatica.objects.create()
    return ItemExecucaoPostagem.objects.create(execucao=execucao, produto=produto, ordem=1)


def _url_baixar_video(item_id):
    return reverse('api_postagem_baixar_video', args=[item_id])


def _url_marcar_concluido(item_id):
    return reverse('api_postagem_marcar_concluido', args=[item_id])


def _mockar_localizador(monkeypatch, arquivos_brutos, pasta_videos_id='pasta-videos-fake'):
    def _fake(self, marca, ean):
        return True, arquivos_brutos, None, pasta_videos_id
    monkeypatch.setattr(LocalizadorArquivosProduto, 'localizar_arquivos', _fake)


# ===================================================================
# view_baixar_video
# ===================================================================

def test_baixar_video_sem_token_devolve_403(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url_baixar_video(999999), headers=CABECALHO_TOKEN_INVALIDO)

    # Assert:
    passou = resposta.status_code == 403
    registrar_resultado(
        tabela_resultados, teste='baixar_video sem token válido',
        entrada='Authorization: Bearer token-errado', esperado='403',
        motivo='Mesmo guard de token de toda a API do agente',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_baixar_video_item_inexistente_devolve_404(client, tabela_resultados):
    # Exercise:
    resposta = client.get(_url_baixar_video(999999), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='baixar_video item_id inexistente',
        entrada='item_id=999999', esperado='404',
        motivo='ItemExecucaoPostagem precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_baixar_video_produto_sem_ciclo_pronto_devolve_400(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-201')
    item = _criar_item(produto)

    # Exercise:
    resposta = client.get(_url_baixar_video(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='baixar_video produto sem nenhum CicloVideo',
        entrada='produto sem ciclo', esperado='400',
        motivo='Não existe vídeo pra baixar sem ocorrência pronta pra postar',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_baixar_video_sucesso_baixa_o_arquivo_certo(client, tabela_resultados, monkeypatch):
    # Setup: ciclo Mensal #1 pronto pra postar; Drive simulado tem o
    # Completo certo dessa ocorrência.
    produto = _criar_produto('SKU-202')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em='2026-08-01T00:00:00Z', roteiro_concluido_em='2026-08-01T00:00:00Z',
        completo_concluido_em='2026-08-01T00:00:00Z',
    )
    item = _criar_item(produto)
    _mockar_localizador(monkeypatch, [{'id': 'drive-id-completo', 'name': 'Mensal_01_Completo.mp4'}])

    def _baixar_fake(self, drive_file_id, caminho_destino_local):
        with open(caminho_destino_local, 'wb') as arquivo:
            arquivo.write(b'conteudo de teste')
    monkeypatch.setattr(ArquivadorDrive, 'baixar_arquivo', _baixar_fake)

    # Exercise:
    resposta = client.get(_url_baixar_video(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = (
        resposta.status_code == 200 and resposta.content == b'conteudo de teste'
        and resposta['X-Drive-File-Id'] == 'drive-id-completo' and resposta['X-Drive-Pasta-Videos-Id'] == 'pasta-videos-fake'
    )
    registrar_resultado(
        tabela_resultados, teste='baixar_video sucesso — baixa o Completo certo da ocorrência',
        entrada='ciclo Mensal #1 pronto + Drive simulado com Mensal_01_Completo.mp4', esperado='200, conteúdo do arquivo, headers com os IDs do Drive',
        motivo='resolver_arquivo_da_ocorrencia() (recém-corrigida) precisa achar o arquivo certo, não qualquer um',
        obtido=f'status={resposta.status_code}, file_id={resposta.get("X-Drive-File-Id")}',
        passou=passou,
    )
    assert passou


def test_baixar_video_arquivo_nao_encontrado_no_drive_devolve_404(client, tabela_resultados, monkeypatch):
    # Setup: ciclo pronto, mas o Drive simulado só tem a ocorrência errada.
    produto = _criar_produto('SKU-203')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em='2026-08-01T00:00:00Z', roteiro_concluido_em='2026-08-01T00:00:00Z',
        completo_concluido_em='2026-08-01T00:00:00Z',
    )
    item = _criar_item(produto)
    _mockar_localizador(monkeypatch, [{'id': 'drive-id-outro', 'name': 'Mensal_02_Completo.mp4'}])

    # Exercise:
    resposta = client.get(_url_baixar_video(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 404
    registrar_resultado(
        tabela_resultados, teste='baixar_video Drive simulado sem o arquivo da ocorrência certa',
        entrada='ciclo pede ocorrência 1, Drive simulado só tem a 2', esperado='404',
        motivo='Nunca baixar o arquivo errado só porque "tem algum" na pasta',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_baixar_video_erro_ao_baixar_devolve_502(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-204')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em='2026-08-01T00:00:00Z', roteiro_concluido_em='2026-08-01T00:00:00Z',
        completo_concluido_em='2026-08-01T00:00:00Z',
    )
    item = _criar_item(produto)
    _mockar_localizador(monkeypatch, [{'id': 'drive-id-completo', 'name': 'Mensal_01_Completo.mp4'}])

    def _baixar_com_erro(self, drive_file_id, caminho_destino_local):
        raise RuntimeError('Falha simulada de rede')
    monkeypatch.setattr(ArquivadorDrive, 'baixar_arquivo', _baixar_com_erro)

    # Exercise:
    resposta = client.get(_url_baixar_video(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 502
    registrar_resultado(
        tabela_resultados, teste='baixar_video erro real ao baixar do Drive',
        entrada='ArquivadorDrive.baixar_arquivo levanta exceção', esperado='502',
        motivo='Erro de rede não pode virar 500 genérico nem 200 com lixo',
        obtido=f'status={resposta.status_code}',
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
        motivo='Mesmo guard de token',
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
        motivo='ItemExecucaoPostagem precisa existir de verdade',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_corpo_sem_ids_do_drive_devolve_400(client, tabela_resultados):
    # Setup:
    produto = _criar_produto('SKU-205')
    item = _criar_item(produto)

    # Exercise: corpo vazio, sem drive_file_id/pasta_videos_id.
    resposta = client.post(_url_marcar_concluido(item.id), headers=CABECALHO_TOKEN_VALIDO)

    # Assert:
    passou = resposta.status_code == 400
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido sem drive_file_id/pasta_videos_id no corpo',
        entrada='corpo vazio', esperado='400',
        motivo='Sem os IDs do Drive não tem como arquivar o arquivo certo depois',
        obtido=f'status={resposta.status_code}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_sucesso_marca_aguardando_e_arquiva(client, tabela_resultados, monkeypatch):
    # Setup:
    produto = _criar_produto('SKU-206')
    ciclo = CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em='2026-08-01T00:00:00Z', roteiro_concluido_em='2026-08-01T00:00:00Z',
        completo_concluido_em='2026-08-01T00:00:00Z',
    )
    item = _criar_item(produto)
    corpo = {'drive_file_id': 'drive-id-completo', 'pasta_videos_id': 'pasta-videos-fake'}
    chamadas = []
    monkeypatch.setattr(ArquivadorDrive, 'mover_para_usados', lambda self, fid, pid: chamadas.append((fid, pid)))

    # Exercise:
    resposta = client.post(
        _url_marcar_concluido(item.id), data=json.dumps(corpo), content_type='application/json',
        headers=CABECALHO_TOKEN_VALIDO,
    )

    # Assert:
    item.refresh_from_db()
    ciclo.refresh_from_db()
    passou = (
        resposta.status_code == 200 and item.status == StatusItemExecucao.CONCLUIDO
        and ciclo.status == StatusPostagem.AGUARDANDO_APROVACAO and chamadas == [('drive-id-completo', 'pasta-videos-fake')]
    )
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido sucesso — marca aguardando aprovação + arquiva',
        entrada='corpo com drive_file_id/pasta_videos_id, arquivamento simulado sem erro', esperado='item=Concluído, ciclo=Aguardando aprovação, mover_para_usados chamado com os IDs certos',
        motivo='Confirma a ordem real: primeiro atualiza a Agenda, só depois tenta arquivar',
        obtido=f'item.status={item.status}, ciclo.status={ciclo.status}, chamadas={chamadas}',
        passou=passou,
    )
    assert passou


def test_marcar_concluido_falha_ao_arquivar_ainda_marca_concluido_com_aviso(client, tabela_resultados, monkeypatch):
    # Função Objetivo: a postagem JÁ aconteceu — falha ao mover pra usados/
    # não pode desfazer isso, só avisar.
    # Setup:
    produto = _criar_produto('SKU-207')
    CicloVideo.objects.create(
        produto=produto, fase=Fase.VIDEO_MENSAL, numero_ocorrencia=1,
        base_concluido_em='2026-08-01T00:00:00Z', roteiro_concluido_em='2026-08-01T00:00:00Z',
        completo_concluido_em='2026-08-01T00:00:00Z',
    )
    item = _criar_item(produto)
    corpo = {'drive_file_id': 'drive-id-completo', 'pasta_videos_id': 'pasta-videos-fake'}

    def _mover_com_erro(self, drive_file_id, pasta_videos_id):
        raise RuntimeError('Falha simulada ao mover pra usados/')
    monkeypatch.setattr(ArquivadorDrive, 'mover_para_usados', _mover_com_erro)

    # Exercise:
    resposta = client.post(
        _url_marcar_concluido(item.id), data=json.dumps(corpo), content_type='application/json',
        headers=CABECALHO_TOKEN_VALIDO,
    )

    # Assert:
    item.refresh_from_db()
    corpo_resposta = resposta.json()
    passou = (
        resposta.status_code == 200 and corpo_resposta['status'] == 'concluido_com_aviso'
        and item.status == StatusItemExecucao.CONCLUIDO and item.mensagem_erro is not None
    )
    registrar_resultado(
        tabela_resultados, teste='marcar_concluido falha ao arquivar — ainda conclui, só avisa',
        entrada='mover_para_usados levanta exceção', esperado='status=concluido_com_aviso, item ainda Concluído',
        motivo='Fingir que não postou seria pior — a Agenda já foi atualizada antes do arquivamento',
        obtido=f'resposta={corpo_resposta}, item.status={item.status}',
        passou=passou,
    )
    assert passou