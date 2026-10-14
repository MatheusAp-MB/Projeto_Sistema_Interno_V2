# autorizar_drive_oauth.py — alternativa de linha de comando para o botão
# "Renovar autorização" do cartão Google Drive (tela Gestão de APIs, que é o
# caminho preferido). Rode na sua máquina só se a tela estiver indisponível.
#
# Abre o navegador, pede login com a conta REAL dona do Drive
# (financeiromagazinebrasileiro@gmail.com), pede consentimento de escrita,
# e grava o token de atualização em GOOGLE_DRIVE_OAUTH_TOKEN_JSON —
# cliente.py reusa esse token sozinho daí em diante. Rodar de novo quando o
# acesso for revogado (myaccount.google.com/permissions) ou, enquanto o app
# OAuth do Google estiver em modo "Testando", a cada 7 dias: nesse modo o
# Google invalida a autorização sozinho depois de 7 dias (erro invalid_grant).
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
    # * [IMPORTANTE] → prompt='consent' obriga o Google a mostrar a tela de consentimento de novo e a entregar um
    #   token de atualização NOVO. Sem isso, se o Google ainda considerar o acesso concedido, ele devolve só o
    #   token de acesso (vale 1 hora), sem token de atualização, e o Drive pararia de funcionar em silêncio.
    credenciais = fluxo.run_local_server(port=0, prompt='consent')
    if not credenciais.refresh_token:
        print('O Google não entregou o token de atualização. Nada foi gravado (o token antigo continua no lugar).')
        print('Abra https://myaccount.google.com/permissions, remova o acesso deste app e rode este script de novo.')
        sys.exit(1)
    with open(settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON, 'w') as arquivo_token:
        arquivo_token.write(credenciais.to_json())
    print(f'Token salvo em {settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON}.')
    print('Faça login como financeiromagazinebrasileiro@gmail.com quando o navegador abrir.')


if __name__ == '__main__':
    main()