# agente_local/postagem_ml.py

# Função Objetivo: Executa a postagem no Mercado Livre.
#
# * [ATENÇÃO] → PLACEHOLDER (29/07) — sempre sucede, não clica em nada de
#               verdade. Usado enquanto não há acesso ao ML pra testar a
#               automação real (a versão validada antes, com os 3
#               checkpoints, ainda vive em
#               agenda_videos/funcoes_auxiliares/postagem_automatica/
#               postagem_ml.py — será trazida pra cá quando o resto do
#               agente estiver validado de ponta a ponta).

import time


def postar_video_no_ml(mlb, caminho_video_local, janela_handle):
    print(f'[PLACEHOLDER] Simulando postagem de "{caminho_video_local}" no anúncio {mlb}...')
    time.sleep(2)
    return True, None