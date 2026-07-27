# agenda_videos/funcoes_auxiliares/google_drive_cliente.py

# Função Objetivo: Autentica e devolve o cliente da API do Google Drive, via
# conta de serviço — usado pra verificar se vídeos/roteiros já foram salvos
# na pasta certa de cada produto. Credencial (caminho do JSON) vem de
# variável de ambiente (.env), nunca hardcoded, nunca commitada no Git.
#
# * [EXPLICAÇÃO] → Escopo "drive.readonly" de propósito — essa integração só
#                  PRECISA LER (conferir se arquivo existe), nunca escrever
#                  nada no Drive. Menor permissão possível pro que é
#                  necessário, mesmo que a conta de serviço tenha acesso de
#                  Editor na pasta (dado pelo usuário na hora de compartilhar).

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


# * [EXPLICAÇÃO] → Escopo de escrita separado, só pra quem realmente precisa
#                  mover/criar arquivo (baixar_arquivo.py) — nunca misturado
#                  com o cliente de leitura, usado por tudo que só lista/
#                  verifica (drive_arquivos_produto.py). Menor permissão
#                  possível, no lugar certo.
def obter_servico_drive_escrita():
    credenciais = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_DRIVE_CREDENCIAIS_JSON, scopes=SCOPES_ESCRITA,
    )
    return build('drive', 'v3', credentials=credenciais)