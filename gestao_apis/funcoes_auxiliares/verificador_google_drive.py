# gestao_apis/funcoes_auxiliares/verificador_google_drive.py

# Função Objetivo: Lê e testa as 2 verificações (partes) da conexão "Google Drive".
#   - LEITURA (conta de serviço, escopo drive.readonly): Agenda de Vídeos lendo pastas.
#   - ENVIO (login OAuth da conta dona do Drive): postagem de arquivos e portal de vídeos.
#   A tela mostra UMA conexão "Google Drive" e junta o resultado destas duas (montagem_do_painel.py).
#
# * [EXPLICAÇÃO] → Cada verificação tem 2 funções:
#     ler_local_*()  → NÃO chama a internet. Só olha configuração/arquivos. Nunca devolve "Funcionando".
#     testar_*()     → Faz 1 a 2 chamadas leves ao Google (files.get na pasta raiz) usando os MESMOS
#                      pontos de entrada que o sistema usa (agenda_videos/funcoes_auxiliares/drive/cliente.py).
#                      Só devolve "Funcionando" se o Google respondeu.
#
# * [IMPORTANTE] → Nenhum conteúdo de credencial é lido/mostrado aqui. Os textos de "O que aconteceu /
#   Próximo passo" são escritos por nós; só o código curto do erro do Google (ex.: invalid_grant) entra neles.
#   A resposta REAL do Google (os dados da pasta, ou o erro que ele devolveu) aparece num bloco à parte em
#   "Ver detalhes", depois de passar por preparar_resposta_para_exibir() (decisão de 14/10/2026).

import json
import os
import re
import time

import httplib2
from django.conf import settings
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from agenda_videos.funcoes_auxiliares.drive.cliente import (
    obter_servico_drive,
    obter_servico_drive_escrita,
)

from .autorizacao_google_drive import (
    PEDIDO_DE_RENOVACAO, descrever_autorizacao_feita, descrever_lembrete, situacao_da_validade,
)
from .estados import (
    ATENCAO, COM_PROBLEMA, FUNCIONANDO, NAO_CONFIGURADA, NAO_VERIFICADA, Resultado,
)
from .protecao_de_segredos import limpar_texto_externo, preparar_resposta_para_exibir
from .tempo_legivel import descrever_duracao

_PADRAO_CODIGO_DE_ERRO = re.compile(r'^[a-z_]{3,40}$')


def _arquivo_existe(caminho):
    return bool(caminho) and os.path.isfile(caminho)


def _pastas_raiz_configuradas():
    pastas = []
    if settings.GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE:
        pastas.append(('Magazine', settings.GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE))
    if settings.GOOGLE_DRIVE_PASTA_RAIZ_SAMVALE:
        pastas.append(('Samvale', settings.GOOGLE_DRIVE_PASTA_RAIZ_SAMVALE))
    return pastas


def _ler_pasta(servico, pasta_id):
    # * [EXPLICAÇÃO] → Devolve a resposta inteira do Google (id e nome da pasta), não só o nome: ela é
    #                  mostrada em "Ver detalhes".
    return servico.files().get(
        fileId=pasta_id, fields='id,name', supportsAllDrives=True,
    ).execute()


def _estruturar_corpo(corpo):
    if isinstance(corpo, (bytes, bytearray)):
        corpo = bytes(corpo).decode('utf-8', errors='replace')
    if isinstance(corpo, str):
        try:
            return json.loads(corpo)
        except ValueError:
            return corpo
    return corpo


def _corpo_do_erro_do_google(erro):
    # * [EXPLICAÇÃO] → HttpError traz o corpo da resposta do Google; RefreshError traz (mensagem,
    #                  resposta_do_google) e daí sai só o dicionário da resposta. Outros erros não têm corpo.
    if isinstance(erro, HttpError):
        return _estruturar_corpo(getattr(erro, 'content', b''))
    if isinstance(erro, RefreshError) and len(erro.args) > 1 and isinstance(erro.args[1], dict):
        return erro.args[1]
    return ''


def _codigo_de_erro_do_google(erro):
    # * [EXPLICAÇÃO] → RefreshError traz (mensagem, resposta_do_google). Do dict só sai o
    #                  campo "error" (ex.: invalid_grant), e só se for um código curto.
    if len(erro.args) > 1 and isinstance(erro.args[1], dict):
        codigo = str(erro.args[1].get('error', ''))
        if _PADRAO_CODIGO_DE_ERRO.match(codigo):
            return codigo
    return ''


def _resultado_de_erro_do_google(erro, tipo, contexto=''):
    """Traduz erro do Google em Resultado. tipo = 'leitura' ou 'envio'. Devolve None se não souber."""
    if isinstance(erro, FileNotFoundError):
        return Resultado(
            NAO_CONFIGURADA,
            'O arquivo de credencial do Google não foi encontrado no caminho configurado.',
            como_resolver='Conferir as variáveis do Google Drive no .env.',
        )

    if isinstance(erro, RefreshError):
        codigo = _codigo_de_erro_do_google(erro)
        sufixo = f' ({codigo})' if codigo else ''
        if tipo == 'envio':
            return Resultado(
                COM_PROBLEMA,
                f'O Google recusou renovar o login do Drive{sufixo}. A autorização venceu ou foi revogada.',
                # * [EXPLICAÇÃO] → O botão Renovar autorização (neste cartão) refaz o login pela própria tela. O motivo
                #                  mais comum desta falha é o app OAuth em modo "Testando": o Google invalida a
                #                  autorização a cada 7 dias (publicar o app em produção acaba com isso).
                como_resolver=(
                    f'{PEDIDO_DE_RENOVACAO} neste cartão e entrar com a conta dona do Drive. Em modo "Testando" '
                    'o Google invalida a autorização a cada 7 dias (publicar o app em produção acaba com isso).'
                ),
            )
        return Resultado(
            COM_PROBLEMA,
            f'O Google recusou a credencial da conta de serviço{sufixo}.',
            como_resolver='Conferir se a chave JSON da conta de serviço ainda é válida e se a conta não foi desativada.',
        )

    if isinstance(erro, HttpError):
        status = int(getattr(erro.resp, 'status', 0) or 0)
        razao = str(getattr(erro, 'reason', '') or '').lower()
        if status in (429,) or status >= 500 or (status == 403 and any(p in razao for p in ('rate', 'limit', 'quota'))):
            return Resultado(
                ATENCAO,
                f'O Google está instável ou limitou o uso agora (status {status}).',
                como_resolver='Esperar alguns minutos e testar de novo.',
            )
        if status == 401:
            return Resultado(
                COM_PROBLEMA,
                'O Google respondeu 401: a credencial não foi aceita.',
                como_resolver=f'{PEDIDO_DE_RENOVACAO} neste cartão e entrar com a conta dona do Drive.' if tipo == 'envio'
                else 'Conferir a chave JSON da conta de serviço.',
            )
        if status == 403:
            return Resultado(
                COM_PROBLEMA,
                'O Google respondeu 403: sem permissão na pasta, ou a API do Google Drive está desativada no projeto.',
                como_resolver='Conferir se a pasta está compartilhada com esta credencial e se a API do Google Drive está ativada.',
            )
        if status == 404:
            onde = f' ({contexto})' if contexto else ''
            return Resultado(
                COM_PROBLEMA,
                f'A pasta raiz{onde} não foi encontrada ou não está acessível para esta credencial.',
                como_resolver='Conferir o ID da pasta raiz no .env e o compartilhamento da pasta.',
            )
        return Resultado(
            ATENCAO,
            f'O Google respondeu com status {status}.',
            como_resolver='Testar de novo; se repetir, ver o terminal do servidor.',
        )

    if isinstance(erro, (TransportError, httplib2.HttpLib2Error, OSError)):
        return Resultado(
            ATENCAO,
            'Não foi possível falar com o Google agora (internet do servidor ou instabilidade).',
            como_resolver='Conferir a internet do servidor e testar de novo.',
        )

    if isinstance(erro, ValueError):
        return Resultado(
            COM_PROBLEMA,
            'O arquivo de credencial do Google existe, mas o conteúdo não é válido '
            f'({limpar_texto_externo(erro, 80)}).',
            como_resolver=f'{PEDIDO_DE_RENOVACAO} neste cartão para gerar o arquivo do login de novo.' if tipo == 'envio'
            else 'Gerar a chave JSON da conta de serviço de novo.',
        )

    return None


# ================================================
# LEITURA (conta de serviço)
# ================================================

def ler_local_drive_leitura():
    if not _arquivo_existe(settings.GOOGLE_DRIVE_CREDENCIAIS_JSON):
        return Resultado(
            NAO_CONFIGURADA,
            'O arquivo da conta de serviço não foi encontrado (variável GOOGLE_DRIVE_CREDENCIAIS_JSON do .env).',
            como_resolver='Configurar o caminho da chave JSON da conta de serviço no .env.',
        )
    pastas = _pastas_raiz_configuradas()
    if not pastas:
        return Resultado(
            NAO_CONFIGURADA,
            'Nenhuma pasta raiz do Drive configurada (GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE / _SAMVALE).',
            como_resolver='Configurar o ID da pasta raiz de cada empresa no .env.',
        )
    nomes = ' e '.join(rotulo for rotulo, _ in pastas)
    return Resultado(
        NAO_VERIFICADA,
        'Configuração completa. Falta testar a conexão com o Google Drive.',
        evidencia=f'Pasta raiz configurada: {nomes}.',
    )


def testar_drive_leitura():
    local = ler_local_drive_leitura()
    if local.estado == NAO_CONFIGURADA:
        return local

    pastas = _pastas_raiz_configuradas()
    achados = []
    respostas = {}
    for rotulo, pasta_id in pastas:
        try:
            servico = obter_servico_drive()
            arquivo = _ler_pasta(servico, pasta_id)
        except (RefreshError, HttpError, TransportError, httplib2.HttpLib2Error, OSError, ValueError) as erro:
            resultado = _resultado_de_erro_do_google(erro, 'leitura', f'pasta raiz da {rotulo}')
            if resultado is None:
                raise
            if achados:
                resultado.evidencia = ' · '.join(achados)
            corpo_do_erro = _corpo_do_erro_do_google(erro)
            if corpo_do_erro:
                respostas[rotulo] = corpo_do_erro
            resultado.resposta = preparar_resposta_para_exibir(respostas) if respostas else ''
            return resultado
        respostas[rotulo] = arquivo
        achados.append(f'{rotulo}: pasta "{limpar_texto_externo(arquivo.get("name", ""), 60)}" acessível')

    return Resultado(
        FUNCIONANDO,
        'O Google Drive respondeu e a conta de serviço enxerga a pasta raiz.',
        evidencia=' · '.join(achados),
        resposta=preparar_resposta_para_exibir(respostas),
    )


# ================================================
# ENVIO (login OAuth da conta dona do Drive)
# ================================================

def ler_local_drive_envio():
    if not _arquivo_existe(settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON):
        return Resultado(
            NAO_CONFIGURADA,
            'O arquivo do login OAuth do Drive não foi encontrado (variável GOOGLE_DRIVE_OAUTH_TOKEN_JSON do .env).',
            como_resolver=f'{PEDIDO_DE_RENOVACAO} neste cartão para gerar o arquivo do login.',
        )
    if not _pastas_raiz_configuradas():
        return Resultado(
            NAO_CONFIGURADA,
            'Nenhuma pasta raiz do Drive configurada (GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE / _SAMVALE).',
            como_resolver='Configurar o ID da pasta raiz de cada empresa no .env.',
        )

    evidencia = ''
    try:
        # * [EXPLICAÇÃO] → O arquivo é regravado a cada renovação bem-sucedida do login (e quando
        #                  o script de autorização roda). Então a data dele mostra a última vez que
        #                  o login funcionou — sem abrir nem ler o conteúdo.
        idade = time.time() - os.path.getmtime(settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON)
        evidencia = f'Arquivo do login gravado há {descrever_duracao(idade)} (autorização ou última renovação).'
    except OSError:
        pass

    # * [EXPLICAÇÃO] → Quando a última autorização foi feita pelo botão desta tela, o cartão diz até quando ela vale
    #                  (modo "Testando" = 7 dias) e o "Próximo passo" lembra de renovar antes. Sem esse registro
    #                  (autorização feita pelo terminal, por exemplo) não há como saber a data, e nada é dito.
    validade = situacao_da_validade()
    como_resolver = ''
    if validade is not None:
        evidencia = f'{descrever_autorizacao_feita(validade)} {evidencia}'.strip()
        como_resolver = descrever_lembrete(validade)

    return Resultado(
        NAO_VERIFICADA,
        'Configuração completa. Falta testar a conexão com o Google Drive.',
        como_resolver=como_resolver,
        evidencia=evidencia,
    )


def testar_drive_envio():
    local = ler_local_drive_envio()
    if local.estado == NAO_CONFIGURADA:
        return local

    rotulo, pasta_id = _pastas_raiz_configuradas()[0]
    try:
        # * [EXPLICAÇÃO] → obter_servico_drive_escrita() renova o login se ele venceu — é nesse
        #                  ponto que o "invalid_grant" aparece. Se não venceu ainda, a chamada
        #                  files.get logo abaixo é que prova que o Google aceita o login.
        servico = obter_servico_drive_escrita()
        arquivo = _ler_pasta(servico, pasta_id)
    except (RefreshError, HttpError, TransportError, httplib2.HttpLib2Error, OSError, ValueError) as erro:
        resultado = _resultado_de_erro_do_google(erro, 'envio', f'pasta raiz da {rotulo}')
        if resultado is None:
            raise
        corpo_do_erro = _corpo_do_erro_do_google(erro)
        resultado.resposta = preparar_resposta_para_exibir({rotulo: corpo_do_erro}) if corpo_do_erro else ''
        return resultado

    return Resultado(
        FUNCIONANDO,
        'O Google aceitou o login da conta dona do Drive.',
        evidencia=f'Pasta raiz da {rotulo} ("{limpar_texto_externo(arquivo.get("name", ""), 60)}") acessível com esse login.',
        resposta=preparar_resposta_para_exibir({rotulo: arquivo}),
    )
