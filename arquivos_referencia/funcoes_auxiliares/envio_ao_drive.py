# arquivos_referencia/funcoes_auxiliares/envio_ao_drive.py

# Função Objetivo: Única porta da tela "Arquivos de referência" para o Google Drive. Faz 3 coisas:
#   1) consultar_no_drive: o que existe HOJE no Drive para um arquivo de referência (só leitura, não cria nada);
#   2) enviar_para_o_drive: coloca o arquivo já conferido na pasta certa, TROCANDO o que estava lá — sempre 1 cópia;
#   3) ler_do_drive: lê o arquivo que está no Drive para a MEMÓRIA do servidor (só leitura, nada é gravado em disco) — é o que o botão
#      "Atualizar o sistema com o Drive" usa (ver atualizacao_do_sistema.py).
# Não toca no sistema (banco): enviar ao Drive e atualizar o sistema são cliques separados (decisão de 14/10/2026).
#
# * [DECISÃO, 14/10/2026] → Fluxo em 2 etapas separadas. Esta é a etapa 1: o arquivo conferido substitui o do Drive, e o
#   Drive passa a ser a fonte única — "garantir só 1 cópia" (cada envio substitui o anterior).
# * [DECISÃO, 15/10/2026] → Onde fica: pasta raiz do sistema (GOOGLE_DRIVE_PASTA_RAIZ_SISTEMA no .env, "Sistema Interno MB SV")
#   > subpasta do grupo ("Tabelas de Frete" ou "Tabelas de Impostos de Saida", ver catalogo_arquivos.py) > nome fixo do
#   arquivo (`nome_no_drive`). Subpasta que não existe é criada.
# * [EXPLICAÇÃO] → Como "trocar" sem duplicar:
#   - já existe 1 arquivo com esse nome na pasta: troca o CONTEÚDO dele (files.update) — mesmo ID, mesmo link; o Drive guarda
#     a versão anterior por um tempo (Arquivo > Histórico de versões);
#   - não existe: cria;
#   - existe MAIS de 1 com o mesmo nome (alguém subiu à mão): atualiza o mais recente e manda os outros para a LIXEIRA do
#     Drive (recuperável) — a regra é "sempre 1 cópia";
#   - depois de gravar, lê de volta o tamanho e o checksum (MD5) que o próprio Drive calculou e compara com o arquivo
#     enviado: só diz "enviado" se bater.
# * [EXPLICAÇÃO] → Autenticação: a mesma do portal de vídeos para ESCREVER (login OAuth da conta dona do Drive, token em
#   GOOGLE_DRIVE_OAUTH_TOKEN_JSON, renovado pelo botão "Renovar autorização" da Gestão de APIs). A conta de serviço só lê e
#   nunca teve acesso a esta pasta, então não é usada aqui. Quando o Google recusa o login, o erro já diz onde renovar.
# * [DECISÃO, 16/10/2026] → MODO Expandir da planilha Busca Legal no ENVIO: em vez de trocar o arquivo do Drive por inteiro, o envio JUNTA a planilha nova ao
#   arquivo que já está lá (existentes atualizadas, novas no final — ver uniao_da_busca_legal.py). Quem decide o modo é a configuração da empresa (card no topo da
#   tela; ver configuracao_da_importacao.py): este módulo não conhece o modo, só recebe `juntar`, uma função que recebe os bytes do arquivo que está no Drive AGORA
#   e devolve os bytes que devem ficar lá. O Substituir (e as tabelas de frete) não passam `juntar`: o arquivo é trocado por inteiro, como sempre foi.
# * [IMPORTANTE] → A leitura do arquivo atual, a junção e a gravação acontecem DENTRO da mesma trava do arquivo: dois envios ao mesmo tempo não se atropelam
#   (o segundo junta ao resultado do primeiro). A leitura confere tamanho e MD5, como ler_do_drive.
# * [IMPORTANTE] → Erros previstos (login vencido, pasta não configurada, sem permissão, Google fora do ar) viram
#   `ErroDoEnvio`, com texto para a pessoa e o status HTTP. O detalhe técnico vai só para o log do servidor.

import hashlib
import io
import logging
import os
import re
import threading
from contextlib import contextmanager

from django.conf import settings
from django.utils.dateparse import parse_datetime
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from httplib2 import HttpLib2Error

from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA

from .leitura_planilha import TAMANHO_MAXIMO_DO_ARQUIVO

logger = logging.getLogger(__name__)

MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
CAMPOS_DO_ARQUIVO = 'id, name, mimeType, size, md5Checksum, modifiedTime'
PREFIXO_MIME_NATIVO_DO_GOOGLE = 'application/vnd.google-apps'  # Planilhas/Docs do Google (não são arquivos .xlsx de verdade)
SEPARADOR_DO_CAMINHO = ' › '

TEXTO_RENOVAR = 'Abra Configurações → Gestão de APIs e use “Renovar autorização” no cartão Google Drive.'

# Um envio por arquivo de cada vez (dentro deste processo): dois cliques seguidos não criam 2 cópias.
_TRAVA_GERAL = threading.Lock()
_TRAVAS_POR_ARQUIVO = {}

# Só 1 pedido de cada vez renova o login: a tela abre 6 consultas juntas e, se o token tivesse vencido, as 6 tentariam
# renovar e gravar o arquivo do token ao mesmo tempo (uma poderia estragar a gravação da outra).
_TRAVA_DO_LOGIN = threading.Lock()


class ErroDoEnvio(Exception):
    """Problema PREVISTO ao falar com o Drive. `mensagem` vai para a tela; `renovar_autorizacao` liga o atalho para a Gestão de APIs."""

    def __init__(self, mensagem, status=502, renovar_autorizacao=False):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.renovar_autorizacao = renovar_autorizacao

    # O texto curto, para a linha apertada do cartão: sem a instrução "Abra Configurações → Gestão de APIs…", porque ao lado
    # dele a tela já mostra o atalho para lá.
    @property
    def resumo(self):
        return self.mensagem.replace(f' {TEXTO_RENOVAR}', '') if self.renovar_autorizacao else self.mensagem


class ArquivoAusenteNoDrive(ErroDoEnvio):
    """O arquivo (ou a pasta dele) ainda não existe no Drive: não há o que ler. Não é falha do Drive — falta enviar o arquivo."""

    def __init__(self, mensagem):
        super().__init__(mensagem, status=404)


# ---------- Conexão ----------

# Função Objetivo: Cria o cliente do Drive com escrita (login OAuth). Separada só para os testes poderem trocar por um Drive de mentira.
def _criar_servico():
    from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive_escrita
    return obter_servico_drive_escrita()


def _servico_do_drive():
    caminho_do_token = getattr(settings, 'GOOGLE_DRIVE_OAUTH_TOKEN_JSON', None)
    if not caminho_do_token or not os.path.exists(caminho_do_token):
        raise ErroDoEnvio(
            f'Não achei o login do Drive neste computador (arquivo do token). {TEXTO_RENOVAR}', 503, renovar_autorizacao=True,
        )
    try:
        with _TRAVA_DO_LOGIN:
            return _criar_servico()
    except (GoogleAuthError, ValueError) as erro:
        # ValueError: o arquivo do token existe mas está incompleto/estragado.
        logger.warning('Drive: não foi possível usar/renovar o login', exc_info=True)
        raise ErroDoEnvio(
            f'A autorização do Drive venceu, foi revogada ou o arquivo dela está incompleto. {TEXTO_RENOVAR}', 503,
            renovar_autorizacao=True,
        ) from erro
    except (OSError, HttpLib2Error) as erro:
        logger.warning('Drive: sem conexão ao renovar o login', exc_info=True)
        raise ErroDoEnvio(_TEXTO_SEM_CONEXAO, 503) from erro


# Função Objetivo: ID da pasta raiz do sistema, vindo do .env. Aceita o ID puro ou o link inteiro da pasta.
def _id_da_pasta_raiz():
    bruto = (getattr(settings, 'GOOGLE_DRIVE_PASTA_RAIZ_SISTEMA', '') or '').strip()
    if not bruto:
        raise ErroDoEnvio(
            'A pasta raiz do sistema no Drive não está configurada. Coloque o ID dela em GOOGLE_DRIVE_PASTA_RAIZ_SISTEMA '
            'no arquivo .env e reinicie o servidor.',
            503,
        )
    achado = re.search(r'/folders/([A-Za-z0-9_-]+)', bruto)
    return achado.group(1) if achado else bruto


# Função Objetivo: Transforma um erro do Google em texto para a pessoa. O detalhe técnico vai para o log do servidor.
def _traduzir_erro_http(erro):
    logger.warning('Drive: o Google devolveu erro', exc_info=True)
    status = getattr(erro.resp, 'status', None)
    # O "motivo" do Google (ex.: storageQuotaExceeded) vem no corpo da resposta; o texto do erro nem sempre o traz.
    texto_tecnico = (erro.content or b'').decode('utf-8', errors='replace') + ' ' + str(erro)
    if status == 401:
        return ErroDoEnvio(f'O Google não aceitou o login do Drive. {TEXTO_RENOVAR}', 503, renovar_autorizacao=True)
    if status == 403 and 'storageQuotaExceeded' in texto_tecnico:
        return ErroDoEnvio('O Drive da conta autorizada está sem espaço de armazenamento.', 507)
    if status == 403 and 'ateLimitExceeded' in texto_tecnico:   # rateLimitExceeded / userRateLimitExceeded
        return ErroDoEnvio('O Google pediu para ir mais devagar. Tente de novo em instantes.', 503)
    if status == 403:
        return ErroDoEnvio(
            'A conta autorizada no Drive não tem permissão para gravar nessa pasta (ou o Google bloqueou o pedido). '
            'Confira se a pasta pertence a essa conta.',
            403,
        )
    if status == 404:
        return ErroDoEnvio(
            'O Drive não achou a pasta raiz do sistema. Confira o ID em GOOGLE_DRIVE_PASTA_RAIZ_SISTEMA no .env e se a '
            'conta autorizada no Drive tem acesso a ela.',
            404,
        )
    if status in (429, 500, 502, 503, 504):
        return ErroDoEnvio('O Google não respondeu agora. Tente de novo em instantes.', 503)
    return ErroDoEnvio(f'O Google recusou o pedido (erro {status}). Veja o terminal do servidor.', 502)


_TEXTO_SEM_CONEXAO = 'Não consegui falar com o Google agora. Confira a internet do servidor e tente de novo.'


# Função Objetivo: Tudo que pode dar errado ao falar com o Google vira ErroDoEnvio (com texto para a pessoa). O que NÃO é do
# Google (um bug nosso) passa direto, para aparecer no terminal do servidor como erro do sistema.
@contextmanager
def _traduzindo_falhas_do_google():
    try:
        yield
    except HttpError as erro:
        raise _traduzir_erro_http(erro) from erro
    except GoogleAuthError as erro:
        # O Google só recusa o login no 1º pedido de verdade (a renovação do token acontece ali, não ao criar o cliente).
        logger.warning('Drive: o Google recusou o login durante o pedido', exc_info=True)
        raise ErroDoEnvio(
            f'A autorização do Drive venceu ou foi revogada. {TEXTO_RENOVAR}', 503, renovar_autorizacao=True,
        ) from erro
    except (OSError, HttpLib2Error) as erro:
        logger.warning('Drive: falha de conexão com o Google', exc_info=True)
        raise ErroDoEnvio(_TEXTO_SEM_CONEXAO, 503) from erro


# ---------- Pastas e arquivos ----------

def _para_consulta(texto):
    return texto.replace('\\', '\\\\').replace("'", "\\'")


# Função Objetivo: A pasta raiz do sistema (confere que o ID é mesmo de uma pasta e que ela não está na lixeira).
def _conferir_pasta_raiz(servico):
    pasta = servico.files().get(
        fileId=_id_da_pasta_raiz(), fields='id, name, mimeType, trashed', supportsAllDrives=True,
    ).execute()
    if pasta.get('trashed') or pasta.get('mimeType') != MIME_PASTA:
        raise ErroDoEnvio(
            'O ID de GOOGLE_DRIVE_PASTA_RAIZ_SISTEMA no .env não é de uma pasta (ou a pasta está na lixeira do Drive).', 503,
        )
    return pasta


# Função Objetivo: ID da subpasta com esse nome dentro de `pai_id`, ou None. Se houver mais de uma, vale a mais antiga.
def _achar_pasta(servico, pai_id, nome):
    consulta = (
        f"'{pai_id}' in parents and name = '{_para_consulta(nome)}' "
        f"and mimeType = '{MIME_PASTA}' and trashed = false"
    )
    resultado = servico.files().list(
        q=consulta, fields='files(id, name)', orderBy='createdTime', pageSize=10,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    achadas = resultado.get('files', [])
    return achadas[0]['id'] if achadas else None


def _achar_ou_criar_pasta(servico, pai_id, nome):
    pasta_id = _achar_pasta(servico, pai_id, nome)
    if pasta_id is not None:
        return pasta_id
    nova = servico.files().create(
        body={'name': nome, 'mimeType': MIME_PASTA, 'parents': [pai_id]}, fields='id', supportsAllDrives=True,
    ).execute()
    return nova['id']


# Função Objetivo: Os arquivos (não pastas) com esse nome dentro da pasta, do mais recente para o mais antigo.
def _listar_copias(servico, pasta_id, nome_do_arquivo):
    consulta = (
        f"'{pasta_id}' in parents and name = '{_para_consulta(nome_do_arquivo)}' "
        f"and mimeType != '{MIME_PASTA}' and trashed = false"
    )
    resultado = servico.files().list(
        q=consulta, fields=f'files({CAMPOS_DO_ARQUIVO})', orderBy='modifiedTime desc', pageSize=50,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    return resultado.get('files', [])


def _tamanho(arquivo_do_drive):
    try:
        return int(arquivo_do_drive.get('size'))
    except (TypeError, ValueError):
        return None


def _quando(arquivo_do_drive):
    texto = arquivo_do_drive.get('modifiedTime')
    return parse_datetime(texto) if texto else None


def _caminho(pasta_raiz, arquivo_de_referencia):
    return f'{pasta_raiz["name"]}{SEPARADOR_DO_CAMINHO}{arquivo_de_referencia.pasta_no_drive}'


# ---------- O que existe hoje no Drive ----------

# Função Objetivo: Situação ATUAL de 1 arquivo de referência no Drive. Só leitura (não cria pasta nem arquivo).
# Devolve {'existe', 'copias', 'tamanho_em_bytes', 'modificado_em', 'caminho', 'md5'} — `md5` é a impressão digital que o PRÓPRIO Drive
# calcula do arquivo (None se não existir ou se o Drive não informar); a tela compara com a do último arquivo que o sistema leu.
def consultar_no_drive(arquivo_de_referencia):
    servico = _servico_do_drive()
    with _traduzindo_falhas_do_google():
        pasta_raiz = _conferir_pasta_raiz(servico)
        caminho = _caminho(pasta_raiz, arquivo_de_referencia)
        pasta_id = _achar_pasta(servico, pasta_raiz['id'], arquivo_de_referencia.pasta_no_drive)
        copias = _listar_copias(servico, pasta_id, arquivo_de_referencia.nome_no_drive) if pasta_id else []

    if not copias:
        return {'existe': False, 'copias': 0, 'tamanho_em_bytes': None, 'modificado_em': None, 'caminho': caminho, 'md5': None}
    atual = copias[0]
    return {
        'existe': True, 'copias': len(copias), 'tamanho_em_bytes': _tamanho(atual),
        'modificado_em': _quando(atual), 'caminho': caminho, 'md5': (atual.get('md5Checksum') or '').lower() or None,
    }


# ---------- Leitura ----------

# Função Objetivo: Lê o arquivo que está HOJE no Drive para a memória do servidor (só leitura: não cria nada, não grava em disco —
# o conteúdo vive só durante a importação e depois some; o servidor guarda apenas código e banco, decisão de 09/10/2026).
# Devolve {'conteudo' (bytes), 'nome', 'tamanho_em_bytes', 'modificado_em', 'copias', 'caminho', 'md5'}.
# * [EXPLICAÇÃO] → Se houver mais de 1 arquivo com o nome (alguém subiu à mão), vale o mais recente — a mesma regra do envio e da
#   consulta — e `copias` avisa quantos existem. Arquivo ausente vira ArquivoAusenteNoDrive (falta enviar, não é falha do Drive).
# * [IMPORTANTE] → Confere o que chegou com o que o Drive disse ter (MD5 e tamanho): só devolve bytes que bateram, nunca meio arquivo.
#   O tamanho máximo é o mesmo da conferência na tela (TAMANHO_MAXIMO_DO_ARQUIVO): maior que isso não é uma tabela de referência.
def ler_do_drive(arquivo_de_referencia):
    servico = _servico_do_drive()
    nome = arquivo_de_referencia.nome_no_drive

    with _trava_do_arquivo(arquivo_de_referencia.id), _traduzindo_falhas_do_google():
        pasta_raiz = _conferir_pasta_raiz(servico)
        caminho = _caminho(pasta_raiz, arquivo_de_referencia)
        pasta_id = _achar_pasta(servico, pasta_raiz['id'], arquivo_de_referencia.pasta_no_drive)
        copias = _listar_copias(servico, pasta_id, nome) if pasta_id else []
        if not copias:
            raise ArquivoAusenteNoDrive(
                f'O Drive ainda não tem “{nome}” em “{caminho}”. Envie o arquivo pelo cartão dele e atualize de novo.',
            )
        atual = copias[0]
        if (atual.get('mimeType') or '').startswith(PREFIXO_MIME_NATIVO_DO_GOOGLE):
            raise ErroDoEnvio(
                f'No Drive, “{nome}” é uma Planilha do Google (não um arquivo .xlsx). '
                'Renomeie ou apague essa planilha no Drive e envie o arquivo de novo pelo cartão.',
                409,
            )
        tamanho_no_drive = _tamanho(atual)
        if tamanho_no_drive is not None and tamanho_no_drive > TAMANHO_MAXIMO_DO_ARQUIVO:
            raise ErroDoEnvio(
                f'O arquivo “{nome}” no Drive é grande demais ({tamanho_no_drive // (1024 * 1024)} MB) para uma tabela de referência. '
                'Confira se é o arquivo certo.',
                413,
            )
        try:
            conteudo = servico.files().get_media(fileId=atual['id'], supportsAllDrives=True).execute()
        except HttpError as erro:
            if getattr(erro.resp, 'status', None) != 404:
                raise
            # Existia na listagem e sumiu no instante seguinte (alguém mexeu na pasta): não é problema da pasta raiz.
            logger.warning('Drive: o arquivo sumiu entre a listagem e a leitura', exc_info=True)
            raise ErroDoEnvio('O arquivo mudou de lugar no Drive durante a leitura. Tente de novo.', 409) from erro

    md5_do_drive = (atual.get('md5Checksum') or '').lower()
    md5_lido = hashlib.md5(conteudo, usedforsecurity=False).hexdigest()
    veio_inteiro = (
        md5_do_drive == md5_lido if md5_do_drive else (tamanho_no_drive is None or tamanho_no_drive == len(conteudo))
    )
    if not veio_inteiro or len(conteudo) > TAMANHO_MAXIMO_DO_ARQUIVO:
        logger.error('Drive: a leitura não bateu (Drive md5=%s, %s bytes; lido md5=%s, %s bytes)',
                     md5_do_drive, tamanho_no_drive, md5_lido, len(conteudo))
        raise ErroDoEnvio(
            'O arquivo que chegou do Drive não bateu com o que o Drive informou (a conferência de integridade falhou). '
            'Tente de novo; se repetir, avise o desenvolvedor.',
            502,
        )

    return {
        'conteudo': conteudo, 'nome': nome, 'tamanho_em_bytes': len(conteudo), 'modificado_em': _quando(atual),
        'copias': len(copias), 'caminho': caminho, 'md5': md5_lido,
    }


# ---------- Envio ----------

def _trava_do_arquivo(id_do_arquivo):
    with _TRAVA_GERAL:
        return _TRAVAS_POR_ARQUIVO.setdefault(id_do_arquivo, threading.Lock())


# Função Objetivo: Manda para a LIXEIRA do Drive (recuperável, nunca apaga em definitivo) as cópias repetidas. Devolve
# (quantas foram, quantas não foi possível). Falhar aqui não derruba o envio: o arquivo principal já está certo.
def _mandar_copias_repetidas_para_a_lixeira(servico, repetidas):
    removidas = 0
    for copia in repetidas:
        try:
            servico.files().update(
                fileId=copia['id'], body={'trashed': True}, fields='id', supportsAllDrives=True,
            ).execute()
            removidas += 1
        except HttpError:
            logger.warning('Drive: não consegui mandar uma cópia repetida para a lixeira', exc_info=True)
    return removidas, len(repetidas) - removidas


# Função Objetivo: Baixa para a memória o arquivo que está no Drive (um item de _listar_copias) e confere o que chegou com o que o Drive disse ter (MD5 e
# tamanho): só devolve bytes que bateram. Chamada DENTRO da trava do arquivo, por quem vai juntar a planilha nova ao que já está lá.
def _baixar_conferido(servico, arquivo_do_drive, nome):
    tamanho_no_drive = _tamanho(arquivo_do_drive)
    if tamanho_no_drive is not None and tamanho_no_drive > TAMANHO_MAXIMO_DO_ARQUIVO:
        raise ErroDoEnvio(
            f'O arquivo “{nome}” que está no Drive é grande demais ({tamanho_no_drive // (1024 * 1024)} MB) para juntar a planilha nova a ele. '
            'Confira se é o arquivo certo (ou use o modo Substituir).',
            413,
        )
    try:
        atual = servico.files().get_media(fileId=arquivo_do_drive['id'], supportsAllDrives=True).execute()
    except HttpError as erro:
        if getattr(erro.resp, 'status', None) != 404:
            raise
        logger.warning('Drive: o arquivo sumiu entre a listagem e a leitura', exc_info=True)
        raise ErroDoEnvio('O arquivo mudou de lugar no Drive durante a leitura. Nada foi enviado. Tente de novo.', 409) from erro
    md5_do_drive = (arquivo_do_drive.get('md5Checksum') or '').lower()
    md5_lido = hashlib.md5(atual, usedforsecurity=False).hexdigest()
    veio_inteiro = md5_do_drive == md5_lido if md5_do_drive else (tamanho_no_drive is None or tamanho_no_drive == len(atual))
    if not veio_inteiro or len(atual) > TAMANHO_MAXIMO_DO_ARQUIVO:
        logger.error('Drive: a leitura para juntar não bateu (Drive md5=%s, %s bytes; lido md5=%s, %s bytes)',
                     md5_do_drive, tamanho_no_drive, md5_lido, len(atual))
        raise ErroDoEnvio(
            'O arquivo que chegou do Drive não bateu com o que o Drive informou (a conferência de integridade falhou). Nada foi enviado. Tente de novo.',
            502,
        )
    return atual


# Função Objetivo: Envia `conteudo` (bytes do .xlsx JÁ conferido) para a pasta certa do Drive, trocando o que estiver lá.
# `juntar` (opcional) = modo Expandir: uma função que recebe os bytes do arquivo que está no Drive AGORA e devolve (bytes_que_ficam_no_Drive, resumo_da_junção);
# quem a escreve confere o resultado e levanta ErroDoEnvio para recusar (nada é enviado). Se ainda não há arquivo no Drive, `juntar` não é chamada e `conteudo`
# vai como está. Sem `juntar` o arquivo é trocado por inteiro (modo Substituir e tabelas de frete).
# Devolve {'nome', 'tamanho_em_bytes', 'modificado_em', 'substituiu', 'copias_removidas', 'copias_que_ficaram', 'caminho', 'md5', 'juncao'} — `juncao` é o resumo
# devolvido por `juntar` (None quando não houve junção).
def enviar_para_o_drive(arquivo_de_referencia, conteudo, juntar=None):
    servico = _servico_do_drive()
    nome = arquivo_de_referencia.nome_no_drive
    juncao = None

    with _trava_do_arquivo(arquivo_de_referencia.id), _traduzindo_falhas_do_google():
        pasta_raiz = _conferir_pasta_raiz(servico)
        pasta_id = _achar_ou_criar_pasta(servico, pasta_raiz['id'], arquivo_de_referencia.pasta_no_drive)
        copias = _listar_copias(servico, pasta_id, nome)
        if any((c.get('mimeType') or '').startswith(PREFIXO_MIME_NATIVO_DO_GOOGLE) for c in copias):
            raise ErroDoEnvio(
                f'Na pasta do Drive já existe “{nome}” como Planilha do Google (não é um arquivo .xlsx). '
                'Renomeie ou apague essa planilha no Drive e envie de novo.',
                409,
            )
        if juntar is not None and copias:
            conteudo, juncao = juntar(_baixar_conferido(servico, copias[0], nome))
        md5_do_envio = hashlib.md5(conteudo, usedforsecurity=False).hexdigest()
        conteudo_para_o_drive = MediaIoBaseUpload(io.BytesIO(conteudo), mimetype=MIME_XLSX, resumable=False)

        if copias:
            mantida = copias[0]
            gravado = servico.files().update(
                fileId=mantida['id'], media_body=conteudo_para_o_drive, fields=CAMPOS_DO_ARQUIVO, supportsAllDrives=True,
            ).execute()
            removidas, que_ficaram = _mandar_copias_repetidas_para_a_lixeira(servico, copias[1:])
        else:
            gravado = servico.files().create(
                body={'name': nome, 'parents': [pasta_id]}, media_body=conteudo_para_o_drive,
                fields=CAMPOS_DO_ARQUIVO, supportsAllDrives=True,
            ).execute()
            removidas, que_ficaram = 0, 0

    # Confere o que o Drive realmente guardou: o MD5 é calculado pelo próprio Drive (se não vier, vale o tamanho).
    md5_do_drive = gravado.get('md5Checksum')
    tamanho_no_drive = _tamanho(gravado)
    if (md5_do_drive and md5_do_drive.lower() != md5_do_envio) or (not md5_do_drive and tamanho_no_drive != len(conteudo)):
        logger.error('Drive: conferência de integridade falhou (enviado md5=%s, %s bytes; Drive md5=%s, %s bytes)',
                     md5_do_envio, len(conteudo), md5_do_drive, tamanho_no_drive)
        raise ErroDoEnvio(
            'O Drive guardou um arquivo diferente do que foi enviado (a conferência de integridade falhou). '
            'Envie de novo; se repetir, avise o desenvolvedor.',
            502,
        )

    return {
        'nome': nome, 'tamanho_em_bytes': tamanho_no_drive if tamanho_no_drive is not None else len(conteudo),
        'modificado_em': _quando(gravado), 'substituiu': bool(copias),
        'copias_removidas': removidas, 'copias_que_ficaram': que_ficaram,
        'caminho': _caminho(pasta_raiz, arquivo_de_referencia), 'md5': md5_do_envio, 'juncao': juncao,
    }
