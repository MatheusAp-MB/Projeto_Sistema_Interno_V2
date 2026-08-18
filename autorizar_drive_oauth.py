# autorizar_drive_oauth.py — rodar 1x, manualmente, na sua máquina.
#
# Abre o navegador, pede login com a conta REAL dona do Drive
# (financeiromagazinebrasileiro@gmail.com), pede consentimento de escrita,
# e grava o token de atualização em GOOGLE_DRIVE_OAUTH_TOKEN_JSON —
# cliente.py reusa esse token sozinho daí em diante. Rodar de novo só se o
# acesso for revogado manualmente (myaccount.google.com/permissions).
#
# Pré-requisito: GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_JSON e
# GOOGLE_DRIVE_OAUTH_TOKEN_JSON configurados no .env (o 2º é só o CAMINHO
# onde este script vai gravar — o arquivo em si não precisa existir ainda).

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.conf import settings
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES_ESCRITA = ['https://www.googleapis.com/auth/drive']


def main():
    fluxo = InstalledAppFlow.from_client_secrets_file(
        settings.GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_JSON, SCOPES_ESCRITA,
    )
    credenciais = fluxo.run_local_server(port=0)
    with open(settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON, 'w') as arquivo_token:
        arquivo_token.write(credenciais.to_json())
    print(f'Token salvo em {settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON}.')
    print('Faça login como financeiromagazinebrasileiro@gmail.com quando o navegador abrir.')


if __name__ == '__main__':
    main()