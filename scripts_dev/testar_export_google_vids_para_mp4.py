# scripts_dev/testar_export_google_vids_para_mp4.py

# Função Objetivo: Verifica se a API do Drive oferece exportação real
# (pra algum formato de vídeo) pro arquivo nativo do Google Vids que
# travou a Postagem em 31/08/2026. Só lê metadado (exportLinks) — não
# baixa, não grava nada.

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

FILE_ID_TESTE = '1MTSP17yVfJMM9-vXMptAlSLRuufGjWMlBnNkJQuH_V4'
servico = obter_servico_drive()

metadado = servico.files().get(fileId=FILE_ID_TESTE, fields='exportLinks').execute()
print('Formatos de exportação que o Drive oferece de verdade pra este arquivo:')
for mime in metadado.get('exportLinks', {}):
    print(f'  {mime}')

if not metadado.get('exportLinks'):
    print('Nenhum exportLinks disponível — a API não oferece exportação pra este arquivo (precisa resolver na origem, não em código).')