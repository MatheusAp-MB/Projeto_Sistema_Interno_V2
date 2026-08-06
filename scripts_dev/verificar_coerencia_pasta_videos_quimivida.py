# scripts_dev/verificar_coerencia_pasta_videos_quimivida.py

# Função Objetivo: Confere, pra TODOS os arquivos da pasta "videos"
# (minúsculo) do EAN 0789888395162 — QUIMIVIDA — se o mimeType real (do
# lado do Drive) bate com o que o NOME do arquivo promete: arquivo com
# "Roteiro"/"Roteiros" no nome deveria ser texto; arquivo com "Base" ou
# "Completo" deveria ser vídeo. Só leitura — nenhuma escrita, nenhuma
# alteração. Mesma lógica que já confirmou o problema do
# Trimestral_01_Roteiro.mp4, agora aplicada à pasta inteira.

import os
import re
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

ID_PASTA_VIDEOS_LOWERCASE = '1dC91E55Ep17LHnMjYFVeCmDzIUd8McwJ'

PADRAO_ROTEIRO = re.compile(r'roteiro', re.IGNORECASE)
PADRAO_VIDEO_ESPERADO = re.compile(r'(base|completo)', re.IGNORECASE)


def _categoria_esperada(nome):
    if PADRAO_ROTEIRO.search(nome):
        return 'texto'
    if PADRAO_VIDEO_ESPERADO.search(nome):
        return 'video'
    return 'desconhecida'


servico = obter_servico_drive()
resultado = servico.files().list(
    q=f"'{ID_PASTA_VIDEOS_LOWERCASE}' in parents and trashed = false",
    fields='files(id, name, mimeType, size)',
).execute()
arquivos = resultado.get('files', [])

print(f'Total de arquivos verificados: {len(arquivos)}\n')

tem_mismatch = False
for item in sorted(arquivos, key=lambda a: a['name']):
    nome = item['name']
    mime = item.get('mimeType', '')
    tamanho_kb = int(item.get('size', 0)) / 1024
    esperado = _categoria_esperada(nome)
    eh_video_de_verdade = mime.startswith('video/')

    if esperado == 'texto':
        situacao = 'MISMATCH — nome diz texto, conteúdo é vídeo' if eh_video_de_verdade else 'OK'
    elif esperado == 'video':
        situacao = 'MISMATCH — nome diz vídeo, conteúdo NÃO é vídeo' if not eh_video_de_verdade else 'OK'
    else:
        situacao = 'categoria não reconhecida pelo padrão — olhar manualmente'

    if 'MISMATCH' in situacao or 'não reconhecida' in situacao:
        tem_mismatch = True

    print(f'{nome:35s}  mimeType={mime:25s}  {tamanho_kb:8.1f} KB  esperado={esperado:10s}  {situacao}')

print()
print('Achou pelo menos 1 inconsistência real.' if tem_mismatch else 'Tudo coerente — nenhuma inconsistência encontrada.')