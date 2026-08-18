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

from core.empresa import obter_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

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


# * [EXPLICAÇÃO] → Achado real (18/08/2026): a Magazine e a Samvale usam a
#                  MESMA credencial/conta do Drive — o que muda é só a
#                  pasta raiz ("Magazine Estruturada" x "Samvale
#                  Estruturada"). Resolvida pela empresa ativa da sessão
#                  web ou do --empresa do comando atual — mesmo princípio
#                  já usado pro token/URL do Sysemp (ver
#                  api_sysemp/__init__.py). Nunca um valor fixo.
def obter_pasta_raiz_id_ativa():
    empresa = obter_empresa_ativa()
    if empresa is None:
        raise RuntimeError(
            'obter_pasta_raiz_id_ativa() precisa saber a empresa (MAGAZINE/SAMVALE) — '
            'nenhuma empresa ativa encontrada. Rode dentro de uma sessão web com '
            'empresa escolhida, ou de um comando com --empresa=.'
        )

    pasta_raiz_id = {
        EMPRESA_MAGAZINE: settings.GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE,
        EMPRESA_SAMVALE: settings.GOOGLE_DRIVE_PASTA_RAIZ_SAMVALE,
    }[empresa]

    if not pasta_raiz_id:
        raise RuntimeError(
            f'Pasta raiz do Drive não configurada pra empresa {empresa} — adicione '
            f'a variável GOOGLE_DRIVE_PASTA_RAIZ_{empresa}=... no .env.'
        )
    return pasta_raiz_id