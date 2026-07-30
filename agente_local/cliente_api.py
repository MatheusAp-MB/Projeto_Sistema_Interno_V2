# agente_local/cliente_api.py

# Função Objetivo: Único lugar do agente que conversa com a API do Django —
# nunca duplicar chamada HTTP em mais de 1 lugar. Cada função corresponde a
# 1 rota já validada em api/postagem_automatica/.

import os
import requests


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


def listar_itens(servidor, token, execucao_id):
    resposta = requests.get(
        f'{servidor}/api/postagem-automatica/execucao/{execucao_id}/itens/', headers=_headers(token),
    )
    resposta.raise_for_status()
    return resposta.json()['itens']


def baixar_video(servidor, token, item_id, pasta_destino):
    resposta = requests.get(
        f'{servidor}/api/postagem-automatica/item/{item_id}/video/', headers=_headers(token),
    )
    resposta.raise_for_status()

    drive_file_id = resposta.headers.get('X-Drive-File-Id')
    pasta_videos_id = resposta.headers.get('X-Drive-Pasta-Videos-Id')

    os.makedirs(pasta_destino, exist_ok=True)
    caminho_local = os.path.join(pasta_destino, f'video_item_{item_id}.mp4')
    with open(caminho_local, 'wb') as arquivo:
        arquivo.write(resposta.content)

    return caminho_local, drive_file_id, pasta_videos_id


def marcar_concluido(servidor, token, item_id, drive_file_id, pasta_videos_id):
    resposta = requests.post(
        f'{servidor}/api/postagem-automatica/item/{item_id}/concluido/',
        headers=_headers(token),
        json={'drive_file_id': drive_file_id, 'pasta_videos_id': pasta_videos_id},
    )
    resposta.raise_for_status()
    return resposta.json()


def marcar_falhou(servidor, token, item_id, mensagem):
    resposta = requests.post(
        f'{servidor}/api/postagem-automatica/item/{item_id}/falhou/',
        headers=_headers(token),
        json={'mensagem': mensagem},
    )
    resposta.raise_for_status()
    return resposta.json()

def enviar_heartbeat(servidor, token, execucao_id):
    requests.post(
        f'{servidor}/api/postagem-automatica/execucao/{execucao_id}/heartbeat/', headers=_headers(token),
    ).raise_for_status()