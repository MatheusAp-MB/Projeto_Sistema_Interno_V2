# agente_local/cliente_api.py

# Função Objetivo: Único lugar do agente que conversa com a API do Django —
# nunca duplicar chamada HTTP em mais de 1 lugar. Cada função corresponde a
# 1 rota já validada em api/postagem_automatica/.

import os
import re
import requests


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


# * [EXPLICAÇÃO] → timeout adicionado em TODA chamada de rede deste arquivo
#                  (30/07) — sem isso, o Python espera indefinidamente se o
#                  servidor não responder. Nunca importou testando em
#                  localhost/rede local (resposta em milissegundos) — mas
#                  com o servidor numa máquina genuinamente separada
#                  (AWS), qualquer instabilidade de rede travaria o agente
#                  inteiro pra sempre, sem erro nenhum aparecer.
TIMEOUT_PADRAO = 30
TIMEOUT_DOWNLOAD_VIDEO = 120  # * vídeo pode demorar mais, especialmente em conexão mais lenta


def listar_itens(servidor, token, execucao_id):
    resposta = requests.get(
        f'{servidor}/api/postagem-automatica/execucao/{execucao_id}/itens/',
        headers=_headers(token), timeout=TIMEOUT_PADRAO,
    )
    resposta.raise_for_status()
    return resposta.json()['itens']


# Função Objetivo: Organiza o download por produto (subpasta por EAN) — cópia
# LOCAL, independente de Django, da mesma ideia já usada no lado do servidor
# (agenda_videos/.../drive/arquivador.py). O agente precisa ser 100%
# autossuficiente — não pode depender de Django estar instalado na máquina
# de quem só vai operar (a mesma razão de existir toda essa arquitetura).
def _montar_caminho_local_organizado(pasta_temporaria_raiz, ean, nome_arquivo):
    pasta_produto = os.path.join(pasta_temporaria_raiz, ean)
    os.makedirs(pasta_produto, exist_ok=True)
    return os.path.join(pasta_produto, nome_arquivo)


def baixar_video(servidor, token, item_id, ean_produto, pasta_destino):
    resposta = requests.get(
        f'{servidor}/api/postagem-automatica/item/{item_id}/video/',
        headers=_headers(token), timeout=TIMEOUT_DOWNLOAD_VIDEO,
    )
    if not resposta.ok:
        try:
            motivo = resposta.json().get('erro', resposta.text)
        except ValueError:
            motivo = resposta.text
        raise RuntimeError(f'{resposta.status_code}: {motivo}')

    drive_file_id = resposta.headers.get('X-Drive-File-Id')
    pasta_videos_id = resposta.headers.get('X-Drive-Pasta-Videos-Id')

    # * [EXPLICAÇÃO] → Corrigido (30/07) — o servidor já manda o nome REAL do
    #                  arquivo (ex: "Diario_01.mp4") no cabeçalho
    #                  Content-Disposition (via FileResponse(..., filename=...)
    #                  no lado do Django) — antes, esse dado era ignorado e
    #                  um nome genérico era inventado aqui ("video_item_47.mp4"),
    #                  que acabava sendo o nome exposto até dentro do Mercado
    #                  Livre. Usa o nome de verdade; só cai no genérico se o
    #                  cabeçalho não vier por algum motivo.
    nome_arquivo = f'video_item_{item_id}.mp4'
    match = re.search(r'filename="?([^";]+)"?', resposta.headers.get('Content-Disposition', ''))
    if match:
        nome_arquivo = match.group(1)

    # * [EXPLICAÇÃO] → Corrigido (30/07) — cada produto ganha sua própria
    #                  subpasta (por EAN), reaproveitando a mesma função já
    #                  usada pelo fluxo de download antigo. Antes, todos os
    #                  produtos da mesma execução caíam juntos na pasta raiz
    #                  — 2 produtos com o mesmo nome de arquivo (ex: os 2 na
    #                  ocorrência 1 de suas próprias fases) se sobrescreveriam.
    caminho_local = _montar_caminho_local_organizado(pasta_destino, ean_produto, nome_arquivo)
    with open(caminho_local, 'wb') as arquivo:
        arquivo.write(resposta.content)

    return caminho_local, drive_file_id, pasta_videos_id


def marcar_concluido(servidor, token, item_id, drive_file_id, pasta_videos_id):
    resposta = requests.post(
        f'{servidor}/api/postagem-automatica/item/{item_id}/concluido/',
        headers=_headers(token),
        json={'drive_file_id': drive_file_id, 'pasta_videos_id': pasta_videos_id},
        timeout=TIMEOUT_PADRAO,
    )
    resposta.raise_for_status()
    return resposta.json()


def marcar_falhou(servidor, token, item_id, mensagem):
    resposta = requests.post(
        f'{servidor}/api/postagem-automatica/item/{item_id}/falhou/',
        headers=_headers(token),
        json={'mensagem': mensagem},
        timeout=TIMEOUT_PADRAO,
    )
    resposta.raise_for_status()
    return resposta.json()

def enviar_heartbeat(servidor, token, execucao_id):
    requests.post(
        f'{servidor}/api/postagem-automatica/execucao/{execucao_id}/heartbeat/',
        headers=_headers(token), timeout=TIMEOUT_PADRAO,
    ).raise_for_status()

def finalizar_execucao(servidor, token, execucao_id, cancelada=False):
    requests.post(
        f'{servidor}/api/postagem-automatica/execucao/{execucao_id}/finalizar/',
        headers=_headers(token),
        json={'cancelada': cancelada},
        timeout=TIMEOUT_PADRAO,
    ).raise_for_status()