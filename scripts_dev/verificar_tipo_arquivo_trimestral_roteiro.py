# scripts_dev/verificar_tipo_arquivo_trimestral_roteiro.py

# Função Objetivo: Confere o mimeType e o tamanho reais (do lado do Drive,
# não do nome do arquivo) de "Trimestral_01_Roteiro.mp4" — EAN 0789888395162,
# QUIMIVIDA — pra saber se o conteúdo é texto (roteiro) salvo com extensão
# errada, ou um vídeo de verdade. Só leitura.

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

ID_ARQUIVO_SUSPEITO = '1uW6oPXiQQoiRtCMUNV6HcQMXLe5dGdTF'  # "Trimestral_01_Roteiro.mp4"

servico = obter_servico_drive()
metadados = servico.files().get(fileId=ID_ARQUIVO_SUSPEITO, fields='id, name, mimeType, size').execute()

nome = metadados.get('name')
mime = metadados.get('mimeType')
tamanho_bytes = int(metadados.get('size', 0))
tamanho_kb = tamanho_bytes / 1024

print(f'Nome:      {nome}')
print(f'mimeType:  {mime}')
print(f'Tamanho:   {tamanho_bytes} bytes ({tamanho_kb:.1f} KB)')
print()
if mime and mime.startswith('video/'):
    print('=> Conteúdo real é VÍDEO. Renomear pra .txt estaria errado.')
elif mime and ('text' in mime or mime == 'application/octet-stream'):
    print('=> Conteúdo consistente com TEXTO. Nome com .mp4 provavelmente é só erro de extensão.')
else:
    print('=> mimeType não bateu com nenhum dos 2 casos esperados — olhar com atenção antes de decidir.')