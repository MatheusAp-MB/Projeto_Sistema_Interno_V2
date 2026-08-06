# scripts_dev/listar_conteudo_pasta_videos_quimivida.py

# Função Objetivo: Lista o conteúdo real da pasta "videos" (minúsculo) do
# EAN 0789888395162 (QUIMIVIDA) — id já confirmado pelo diagnóstico
# anterior. Também verifica, dentro dela, qualquer subpasta que pareça ser
# "usados" (comparação sem diferenciar maiúscula/minúscula) e lista o
# conteúdo dela também. Só leitura — nenhuma escrita, nenhuma alteração.

import os
import sys


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive
from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA

ID_PASTA_VIDEOS_LOWERCASE = '1dC91E55Ep17LHnMjYFVeCmDzIUd8McwJ'


def _listar_filhos(servico, pasta_id):
    resultado = servico.files().list(
        q=f"'{pasta_id}' in parents and trashed = false",
        fields='files(id, name, mimeType)',
    ).execute()
    return resultado.get('files', [])


servico = obter_servico_drive()

print('=== Conteúdo de "videos" (minúsculo) — EAN 0789888395162 ===')
filhos = _listar_filhos(servico, ID_PASTA_VIDEOS_LOWERCASE)
print(f'Total: {len(filhos)}\n')
for item in filhos:
    tipo = 'PASTA' if item['mimeType'] == MIME_PASTA else 'arquivo'
    print(f'  [{tipo}] "{item["name"]}"  (id: {item["id"]})')

pasta_usados = next(
    (f for f in filhos if f['mimeType'] == MIME_PASTA and f['name'].lower() == 'usados'),
    None,
)
if pasta_usados:
    print(f'\n=== Conteúdo de "{pasta_usados["name"]}" (id: {pasta_usados["id"]}) ===')
    filhos_usados = _listar_filhos(servico, pasta_usados['id'])
    print(f'Total: {len(filhos_usados)}\n')
    for item in filhos_usados:
        tipo = 'PASTA' if item['mimeType'] == MIME_PASTA else 'arquivo'
        print(f'  [{tipo}] "{item["name"]}"  (id: {item["id"]})')
else:
    print('\n(Nenhuma subpasta "usados" encontrada dentro de "videos")')