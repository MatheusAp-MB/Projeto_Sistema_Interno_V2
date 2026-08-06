# scripts_dev/renomear_arquivos_roteiro_quimivida.py

# Função Objetivo: Corrige o nome de 3 arquivos da pasta de teste do EAN
# 0789888395162 (QUIMIVIDA). 1) "Simples_Roteiros.txt" (plural, deveria
# ser singular) — simples correção de digitação. 2) e 3) o par
# "Trimestral_01_Completo.mp4"/"Trimestral_01_Roteiro.mp4" está com os
# nomes INVERTIDOS em relação ao conteúdo real (confirmado via mimeType):
# quem tem conteúdo de vídeo estava nomeado "Roteiro", e quem tem conteúdo
# de Google Doc estava nomeado "Completo" — aqui cada um recebe o nome que
# bate com o que ele realmente é. Usa o cliente de ESCRITA — só renomeia,
# nunca move nem apaga nem troca conteúdo.

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

from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive_escrita

RENOMEACOES = [
    {'id': '1aXjov6cQrfjUITpj6tx2imFTXCXzYGugnhNJUjwMVHI', 'de': 'Simples_Roteiros.txt', 'para': 'Simples_Roteiro.txt'},
    {'id': '1uW6oPXiQQoiRtCMUNV6HcQMXLe5dGdTF', 'de': 'Trimestral_01_Roteiro.mp4 (conteúdo real: vídeo)', 'para': 'Trimestral_01_Completo.mp4'},
    {'id': '18xT_KBlmh3P1oQM-5OR28C15mN534iMDRM7GXKVg-B0', 'de': 'Trimestral_01_Completo.mp4 (conteúdo real: Google Doc)', 'para': 'Trimestral_01_Roteiro.txt'},
]

servico = obter_servico_drive_escrita()

for item in RENOMEACOES:
    resultado = servico.files().update(
        fileId=item['id'], body={'name': item['para']}, fields='id, name',
    ).execute()
    print(f'{item["de"]}  →  {resultado["name"]}  (id: {resultado["id"]})')