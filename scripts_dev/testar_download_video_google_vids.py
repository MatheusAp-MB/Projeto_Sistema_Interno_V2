# scripts_dev/testar_download_video_google_vids.py

# Função Objetivo: Testa o endpoint POST files/{fileId}/download (Long-
# Running Operation) — único jeito oficial de baixar um vídeo do Google
# Vids como MP4 real, confirmado contra a documentação oficial do Google
# em 31/08/2026. Só testa 1 arquivo, salva localmente pra conferência
# manual — não mexe no fluxo real de Postagem ainda.

import os
import sys
import time


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

from django.conf import settings
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

FILE_ID_TESTE = '1MTSP17yVfJMM9-vXMptAlSLRuufGjWMlBnNkJQuH_V4'

# * [EXPLICAÇÃO] → Chamada HTTP direta (não via googleapiclient) de
#                  propósito — esse endpoint é recente o suficiente que a
#                  versão instalada do google-api-python-client pode não
#                  ter o método dinâmico servico.files().download() ainda.
#                  Bater direto na REST API documentada é mais garantido.
credenciais = service_account.Credentials.from_service_account_file(
    settings.GOOGLE_DRIVE_CREDENCIAIS_JSON,
    scopes=['https://www.googleapis.com/auth/drive.readonly'],
)
sessao = AuthorizedSession(credenciais)

print('Passo 1: iniciando o download (POST .../download)...')
resposta = sessao.post(f'https://www.googleapis.com/drive/v3/files/{FILE_ID_TESTE}/download', json={})
resposta.raise_for_status()
operacao = resposta.json()
print(f'Operação iniciada: {operacao}')

nome_operacao = operacao['name']
print(f'\nPasso 2: fazendo polling de "{nome_operacao}" até done=true...')

espera_segundos = 10
while not operacao.get('done'):
    time.sleep(espera_segundos)
    resposta = sessao.get(f'https://www.googleapis.com/drive/v3/{nome_operacao}')
    resposta.raise_for_status()
    operacao = resposta.json()
    print(f'  done={operacao.get("done")}')
    espera_segundos = min(espera_segundos * 2, 60)

if 'error' in operacao:
    raise RuntimeError(f'Operação falhou: {operacao["error"]}')

download_uri = operacao['response']['downloadUri']
print(f'\nPasso 3: baixando de {download_uri[:80]}...')

resposta_video = sessao.get(download_uri)
resposta_video.raise_for_status()

with open('teste_download_vids.mp4', 'wb') as arquivo:
    arquivo.write(resposta_video.content)

print(f'\nOK — salvo em teste_download_vids.mp4 ({len(resposta_video.content)} bytes). Confere se abre como vídeo de verdade.')