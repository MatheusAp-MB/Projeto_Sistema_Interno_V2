# agenda_videos/funcoes_auxiliares/drive/cliente.py

# Função Objetivo: Autentica e devolve o cliente da API do Google Drive, via
# conta de serviço. Credencial (caminho do JSON) vem de variável de ambiente
# (.env), nunca hardcoded, nunca commitada no Git.
#
# * [EXPLICAÇÃO] → 2 escopos, cada um usado só onde é necessário — leitura
#                  (localizador.py, escaneador.py, tudo que só consulta) e
#                  escrita (arquivador.py, o único lugar que move/cria
#                  arquivo). Menor permissão possível, no lugar certo.

from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES_LEITURA = ['https://www.googleapis.com/auth/drive.readonly']
SCOPES_ESCRITA = ['https://www.googleapis.com/auth/drive']


def obter_servico_drive():
    credenciais = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_DRIVE_CREDENCIAIS_JSON, scopes=SCOPES_LEITURA,
    )
    return build('drive', 'v3', credentials=credenciais)


def obter_servico_drive_escrita():
    credenciais = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_DRIVE_CREDENCIAIS_JSON, scopes=SCOPES_ESCRITA,
    )
    return build('drive', 'v3', credentials=credenciais)