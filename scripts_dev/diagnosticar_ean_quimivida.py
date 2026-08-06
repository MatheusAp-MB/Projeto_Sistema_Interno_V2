# scripts_dev/diagnosticar_ean_quimivida.py

# Função Objetivo: Resolve o mistério de qual é o EAN certo dentro de
# QUIMIVIDA — lista TODOS os filhos diretos da pasta QUIMIVIDA sem filtrar
# por estrutura (ao contrário de montar_arvore_por_ean, que descarta
# silenciosamente qualquer EAN sem subpasta "Videos" exata), mostra os
# filhos de cada pasta de EAN encontrada (pra checar se existe uma subpasta
# tipo "Videos" com nome diferente do esperado), e procura o trecho
# "395162" ou "395308" em QUALQUER lugar do Drive — não só dentro de
# QUIMIVIDA — pra cobrir o caso de a pasta ter sido criada na marca errada.
# Só leitura — nenhuma escrita, nenhuma alteração.

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
from agenda_videos.funcoes_auxiliares.drive.escaneador import _listar_tudo_paginado
from agenda_videos.funcoes_auxiliares.drive.constantes import MIME_PASTA

ID_PASTA_QUIMIVIDA = '1R425v5mXj47XBx7_xPUFFEU4bNE8sMCs'
TRECHOS_PROCURADOS = ['395162', '395308']

servico = obter_servico_drive()
todos_os_itens = _listar_tudo_paginado(servico)
print(f'Total de itens na varredura: {len(todos_os_itens)}\n')

filhos_de = {}
for item in todos_os_itens:
    for pai_id in item.get('parents', []):
        filhos_de.setdefault(pai_id, []).append(item)

print('=== TODOS os filhos diretos de QUIMIVIDA (sem filtrar por estrutura) ===')
filhos_quimivida = filhos_de.get(ID_PASTA_QUIMIVIDA, [])
print(f'Total: {len(filhos_quimivida)}\n')
for item in filhos_quimivida:
    tipo = 'PASTA' if item['mimeType'] == MIME_PASTA else 'arquivo'
    print(f'  [{tipo}] "{item["name"]}"  (id: {item["id"]})')

print()
print('=== Filhos de cada pasta de EAN dentro de QUIMIVIDA (pra checar a subpasta "Videos") ===')
for pasta_ean in filhos_quimivida:
    if pasta_ean['mimeType'] != MIME_PASTA:
        continue
    print(f'\nPasta EAN: "{pasta_ean["name"]}" (id: {pasta_ean["id"]})')
    filhos = filhos_de.get(pasta_ean['id'], [])
    if not filhos:
        print('  (vazia — nenhum filho encontrado)')
    for filho in filhos:
        tipo = 'PASTA' if filho['mimeType'] == MIME_PASTA else 'arquivo'
        print(f'    [{tipo}] "{filho["name"]}"  (id: {filho["id"]})')

print()
print('=== Busca por "395162" ou "395308" em QUALQUER lugar do Drive (não só QUIMIVIDA) ===')
encontrados = [item for item in todos_os_itens if any(trecho in item['name'] for trecho in TRECHOS_PROCURADOS)]
if not encontrados:
    print('  Nenhum item encontrado com esses trechos no nome.')
for item in encontrados:
    tipo = 'PASTA' if item['mimeType'] == MIME_PASTA else 'arquivo'
    pais = item.get('parents', [])
    print(f'  [{tipo}] "{item["name"]}"  (id: {item["id"]}, pais: {pais})')