# scripts_dev/listar_estrutura_pasta_drive.py

# Função Objetivo: imprime a árvore completa (pastas e arquivos, recursivo)
# de dentro de uma pasta do Drive — só LEITURA (Service Account, nunca
# gasta cota). Serve pra confirmar visualmente, pelo terminal, que uma
# estrutura marca/ean/Videos foi criada certa, sem precisar abrir o site
# do Drive no navegador.
#
# Rodar com: poetry run python scripts_dev/listar_estrutura_pasta_drive.py

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__ + '/..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.conf import settings

from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive
from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA

# Troque aqui pra inspecionar outra pasta (ex: settings.GOOGLE_DRIVE_PASTA_TESTE_SAMVALE
# ou, com cuidado, settings.GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE).
PASTA_RAIZ_PARA_INSPECIONAR = settings.GOOGLE_DRIVE_PASTA_TESTE_MAGAZINE
ROTULO_RAIZ = 'Teste Magazine'


def _listar_filhos(servico, pasta_id):
    resultado = servico.files().list(
        q=f"'{pasta_id}' in parents and trashed = false",
        fields='files(id, name, mimeType, size, modifiedTime)',
        orderBy='folder,name',
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    return resultado.get('files', [])


def _imprimir_arvore(servico, pasta_id, profundidade=0):
    prefixo = '  ' * profundidade
    for item in _listar_filhos(servico, pasta_id):
        if item['mimeType'] == MIME_PASTA:
            print(f'{prefixo}📁 {item["name"]}/')
            _imprimir_arvore(servico, item['id'], profundidade + 1)
        else:
            tamanho_kb = int(item.get('size', 0)) / 1024 if item.get('size') else 0
            modificado = item.get('modifiedTime', '?')
            print(f'{prefixo}📄 {item["name"]}  ({tamanho_kb:.1f} KB, modificado {modificado}, ID: {item["id"]})')


def main():
    if not PASTA_RAIZ_PARA_INSPECIONAR:
        print('Pasta raiz não configurada — confira a variável PASTA_RAIZ_PARA_INSPECIONAR no topo do script.')
        sys.exit(1)

    servico = obter_servico_drive()
    print(f'{ROTULO_RAIZ}/')
    _imprimir_arvore(servico, PASTA_RAIZ_PARA_INSPECIONAR, profundidade=1)


if __name__ == '__main__':
    main()