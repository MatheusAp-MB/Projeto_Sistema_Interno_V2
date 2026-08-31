# scripts_dev/diagnosticar_arquivos_nao_baixaveis.py

# Função Objetivo: Descobre o mimeType real dos 3 arquivos que falharam ao
# baixar na 1ª execução real de Postagem contra as pastas REAIS do Drive
# (31/08/2026). Só LÊ metadado — nunca baixa nada.

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

# IDs vindos direto do log de erro (agente_log_20260831_110305.txt)
IDS_PRA_DIAGNOSTICAR = [
    '1MTSP17yVfJMM9-vXMptAlSLRuufGjWMlBnNkJQuH_V4',
    '1f673S7IlT96lq-Mgb9NCbxZTWNyou3jLkos0WNVzwGo',
    '1NEKg4C70ydN8fifuPkLtO34lHwGNS7FuPLF8hVzzFN0',
]

servico = obter_servico_drive()

for file_id in IDS_PRA_DIAGNOSTICAR:
    metadado = servico.files().get(
        fileId=file_id, fields='id, name, mimeType, parents, trashed, size',
        supportsAllDrives=True,
    ).execute()
    print(f'ID={file_id}')
    print(f'  name={metadado.get("name")!r}')
    print(f'  mimeType={metadado.get("mimeType")!r}')
    print(f'  size={metadado.get("size", "(sem tamanho — provável arquivo Google nativo)")}')
    print(f'  trashed={metadado.get("trashed")}')
    print()