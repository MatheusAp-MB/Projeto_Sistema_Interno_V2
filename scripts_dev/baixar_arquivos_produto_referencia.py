# scripts_dev/baixar_arquivos_produto_referencia.py

# Função Objetivo: baixa, pra esta máquina, todos os arquivos BINÁRIOS reais
# da pasta Videos/ do produto de referência já validado no Drive (QUIMIVIDA,
# EAN 0789888395162, marca da Magazine) — só LEITURA (Service Account,
# nunca gasta cota), nenhuma escrita no Drive. Serve pra ter arquivo real
# (nome/extensão corretos) pra usar nos testes manuais do Portal do Drive,
# em vez de arquivo vazio/fake.
#
# Achado real (19/08/2026): alguns dos 18 arquivos dessa pasta são arquivo
# NATIVO do Google (Google Doc/Sheets/etc, mimeType
# 'application/vnd.google-apps.*') em vez de arquivo binário de verdade —
# a API recusa baixar esse tipo com get_media() (erro 403
# fileNotDownloadable), precisaria de export() em outro formato. Este
# script pula esses com um aviso claro, em vez de quebrar no meio do lote.
#
# Rodar com: poetry run python scripts_dev/baixar_arquivos_produto_referencia.py

import os
import sys

import django
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__ + '/..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.conf import settings

from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive
from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA, NOME_PASTA_VIDEOS
from agenda_videos.funcoes_auxiliares.drive.utilitarios_pasta import buscar_subpasta

MARCA_REFERENCIA = 'QUIMIVIDA'
EAN_REFERENCIA = '0789888395162'
PASTA_DESTINO_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'arquivos_baixados_quimivida')
PREFIXO_MIME_GOOGLE_NATIVO = 'application/vnd.google-apps.'


def _baixar_arquivo(servico, arquivo_id, nome_arquivo, pasta_destino):
    caminho_destino = os.path.join(pasta_destino, nome_arquivo)
    requisicao = servico.files().get_media(fileId=arquivo_id, supportsAllDrives=True)
    with open(caminho_destino, 'wb') as arquivo_local:
        downloader = MediaIoBaseDownload(arquivo_local, requisicao)
        concluido = False
        while not concluido:
            _, concluido = downloader.next_chunk()
    return caminho_destino


def main():
    servico = obter_servico_drive()

    pasta_marca_id = buscar_subpasta(servico, settings.GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE, MARCA_REFERENCIA)
    if not pasta_marca_id:
        print(f'Marca "{MARCA_REFERENCIA}" não encontrada na raiz da Magazine.')
        sys.exit(1)

    pasta_ean_id = buscar_subpasta(servico, pasta_marca_id, EAN_REFERENCIA)
    if not pasta_ean_id:
        print(f'EAN "{EAN_REFERENCIA}" não encontrado dentro de "{MARCA_REFERENCIA}".')
        sys.exit(1)

    pasta_videos_id = buscar_subpasta(servico, pasta_ean_id, NOME_PASTA_VIDEOS)
    if not pasta_videos_id:
        print(f'Subpasta "{NOME_PASTA_VIDEOS}" não encontrada dentro do EAN "{EAN_REFERENCIA}".')
        sys.exit(1)

    resultado = servico.files().list(
        q=f"'{pasta_videos_id}' in parents and trashed = false",
        fields='files(id, name, mimeType, size)',
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    itens = [item for item in resultado.get('files', []) if item['mimeType'] != MIME_PASTA]

    if not itens:
        print('Nenhum arquivo encontrado dentro de Videos/ — nada pra baixar.')
        sys.exit(0)

    os.makedirs(PASTA_DESTINO_LOCAL, exist_ok=True)
    print(f'Encontrados {len(itens)} item(ns) em {MARCA_REFERENCIA}/{EAN_REFERENCIA}/{NOME_PASTA_VIDEOS}/:\n')

    baixados, pulados = 0, []
    for item in itens:
        if item['mimeType'].startswith(PREFIXO_MIME_GOOGLE_NATIVO):
            print(f'  [PULADO] {item["name"]} — é um arquivo nativo do Google ({item["mimeType"]}), sem conteúdo binário pra baixar direto.')
            pulados.append(item['name'])
            continue
        try:
            caminho_baixado = _baixar_arquivo(servico, item['id'], item['name'], PASTA_DESTINO_LOCAL)
            tamanho_kb = int(item.get('size', 0)) / 1024
            print(f'  [OK] {item["name"]} ({tamanho_kb:.1f} KB) -> {caminho_baixado}')
            baixados += 1
        except HttpError as erro:
            print(f'  [ERRO] {item["name"]} -> {erro}')
            pulados.append(item['name'])

    print(f'\n{baixados} arquivo(s) baixado(s) em: {PASTA_DESTINO_LOCAL}')
    if pulados:
        print(f'{len(pulados)} item(ns) pulado(s): {", ".join(pulados)}')


if __name__ == '__main__':
    main()