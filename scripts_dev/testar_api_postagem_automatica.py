import os
import sys


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

import requests
from django.conf import settings
from produtos.models import Produto
from agenda_videos.models import ExecucaoPostagemAutomatica, ItemExecucaoPostagem, StatusExecucao

# ==== CONFIGURA AQUI ANTES DE RODAR ====
URL_BASE = 'http://127.0.0.1:8000'
EAN_PRODUTO_TESTE = '7891117102687'  # Tramontina — troque se precisar
# ========================================

TOKEN = settings.AGENTE_TOKEN
if not TOKEN:
    raise RuntimeError('AGENTE_TOKEN não está definido no .env do Django — confere se você salvou lá.')

HEADERS = {'Authorization': f'Bearer {TOKEN}'}

# --- Passo 1: cria uma execução + 1 item de teste, direto no banco ---
produto = Produto.objects.filter(ean=EAN_PRODUTO_TESTE).first()
if produto is None:
    raise RuntimeError(f'Produto {EAN_PRODUTO_TESTE} não encontrado no banco.')

execucao = ExecucaoPostagemAutomatica.objects.create(status=StatusExecucao.RODANDO)
item = ItemExecucaoPostagem.objects.create(execucao=execucao, produto=produto, ordem=1)
print(f'Execução #{execucao.id} criada, item #{item.id} (produto {produto.ean}).\n')

# --- Passo 2: listar itens (seguro, só leitura) ---
print('=== Testando: listar itens ===')
resposta = requests.get(f'{URL_BASE}/api/postagem-automatica/execucao/{execucao.id}/itens/', headers=HEADERS)
print(f'Status: {resposta.status_code}')
print(f'Resposta: {resposta.json()}\n')

# --- Passo 3: baixar vídeo (seguro, só leitura do Drive) ---
print('=== Testando: baixar vídeo ===')
resposta = requests.get(f'{URL_BASE}/api/postagem-automatica/item/{item.id}/video/', headers=HEADERS)
print(f'Status: {resposta.status_code}')

drive_file_id = None
pasta_videos_id = None
if resposta.status_code == 200:
    drive_file_id = resposta.headers.get('X-Drive-File-Id')
    pasta_videos_id = resposta.headers.get('X-Drive-Pasta-Videos-Id')
    caminho_local = 'video_teste_baixado.mp4'
    with open(caminho_local, 'wb') as arquivo:
        arquivo.write(resposta.content)
    print(f'Vídeo baixado: {caminho_local} ({len(resposta.content)} bytes)')
    print(f'X-Drive-File-Id: {drive_file_id}')
    print(f'X-Drive-Pasta-Videos-Id: {pasta_videos_id}\n')
else:
    print(f'Erro: {resposta.json()}\n')

# --- Passo 4: marcar concluído — AÇÃO REAL, com confirmação ---
if drive_file_id:
    confirmacao = input(
        'PRÓXIMO TESTE TEM EFEITO REAL: cria 1 Postagem de verdade e MOVE '
        'o arquivo pra usados/ no Drive. Confirma? (digite SIM): '
    )
    if confirmacao.strip().upper() == 'SIM':
        print('\n=== Testando: marcar concluído (AÇÃO REAL) ===')
        resposta = requests.post(
            f'{URL_BASE}/api/postagem-automatica/item/{item.id}/concluido/',
            headers=HEADERS,
            json={'drive_file_id': drive_file_id, 'pasta_videos_id': pasta_videos_id},
        )
        print(f'Status: {resposta.status_code}')
        print(f'Resposta: {resposta.json()}')
    else:
        print('Pulado — nenhuma ação real feita.')

print('\nTestes concluídos.')