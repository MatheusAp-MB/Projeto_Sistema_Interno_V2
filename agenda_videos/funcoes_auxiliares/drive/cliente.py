# agenda_videos/funcoes_auxiliares/drive/cliente.py

# Função Objetivo: Autentica e devolve o cliente da API do Google Drive.
# LEITURA continua via Service Account (nunca gasta cota — sem mudança).
# ESCRITA passa a autenticar como o USUÁRIO REAL dono do Drive, via OAuth
# (18/08/2026) — achado real: Service Account tem SEMPRE 0 bytes de cota
# própria (regra da própria plataforma Google, não configurável), então
# todo upload de conteúdo novo falhava com storageQuotaExceeded, mesmo com
# permissão de editor na pasta (editor = pode fazer, não = tem cota pra
# isso — 2 coisas independentes). Conta do Drive é Google comum (sem
# Workspace), então Shared Drive de verdade e delegação de domínio (as 2
# soluções "padrão" pra Service Account) não são opção aqui.
#
# Autorização inicial (1x só, manual): rodar autorizar_drive_oauth.py na
# raiz do projeto — abre o navegador, pede login com a conta dona de
# verdade (financeiromagazinebrasileiro@gmail.com), grava o token de
# atualização em GOOGLE_DRIVE_OAUTH_TOKEN_JSON. Daí em diante, o token se
# renova sozinho (refresh(), abaixo) — nunca mais precisa logar de novo, a
# menos que o acesso seja revogado manualmente em
# myaccount.google.com/permissions.

from django.conf import settings
from google.auth.transport.requests import Request as RequisicaoAtualizacaoToken
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as CredenciaisOAuth
from googleapiclient.discovery import build

from core.empresa import obter_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

SCOPES_LEITURA = ['https://www.googleapis.com/auth/drive.readonly']
SCOPES_ESCRITA = ['https://www.googleapis.com/auth/drive']


def obter_servico_drive():
    # LEITURA: Service Account — nunca gasta cota, sem motivo pra mudar.
    credenciais = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_DRIVE_CREDENCIAIS_JSON, scopes=SCOPES_LEITURA,
    )
    return build('drive', 'v3', credentials=credenciais)


def obter_servico_drive_escrita():
    # ESCRITA: autentica como USUÁRIO REAL (OAuth) — só assim o upload usa
    # a cota de armazenamento de alguém de verdade, não de uma Service
    # Account (que nunca tem cota própria).
    credenciais = CredenciaisOAuth.from_authorized_user_file(
        settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON, scopes=SCOPES_ESCRITA,
    )
    if credenciais.expired and credenciais.refresh_token:
        credenciais.refresh(RequisicaoAtualizacaoToken())
        with open(settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON, 'w') as arquivo_token:
            arquivo_token.write(credenciais.to_json())
    return build('drive', 'v3', credentials=credenciais)


# * [EXPLICAÇÃO] → Achado real (18/08/2026): a Magazine e a Samvale usam a
#                  MESMA credencial/conta do Drive — o que muda é só a
#                  pasta raiz ("Magazine Estruturada" x "Samvale
#                  Estruturada"). Resolvida pela empresa ativa da sessão
#                  web ou do --empresa do comando atual — mesmo princípio
#                  já usado pro token/URL do Sysemp (ver
#                  api_sysemp/__init__.py). Nunca um valor fixo.
#
# * [DECISÃO, 31/08/2026] → Validação de Postagem/Verificação/Replicação
#               concluída — TODA leitura/escrita no Drive (Portal do Drive,
#               verificação automática, postagem) volta a apontar pra
#               pasta REAL de produção de cada empresa
#               (GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE/_SAMVALE), nunca mais
#               pra pasta de teste. Pasta de teste esteve ativa entre
#               20/08 e 31/08/2026.
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


def obter_credenciais_drive_escrita():
    # Extraído de obter_servico_drive_escrita() (19/08/2026) — o streaming
    # de vídeo do Portal do Drive também precisa do token bruto (pra
    # repassar Range direto pro Drive via requests), não só do serviço
    # já "empacotado" do googleapiclient.
    credenciais = CredenciaisOAuth.from_authorized_user_file(
        settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON, scopes=SCOPES_ESCRITA,
    )
    if credenciais.expired and credenciais.refresh_token:
        credenciais.refresh(RequisicaoAtualizacaoToken())
        with open(settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON, 'w') as arquivo_token:
            arquivo_token.write(credenciais.to_json())
    return credenciais


def obter_servico_drive_escrita():
    return build('drive', 'v3', credentials=obter_credenciais_drive_escrita())