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

from agenda_videos.funcoes_auxiliares.google_drive_cliente import obter_servico_drive
from agenda_videos.funcoes_auxiliares.escanear_drive_completo import _listar_tudo_paginado, MIME_PASTA

# ==== CONFIGURA AQUI ANTES DE RODAR ====
ID_PASTA_GUARANY = '1azbTu-GSp1hIm5v43sQV1f4-ouCHc8J3'
# ========================================

servico = obter_servico_drive()
todos_os_itens = _listar_tudo_paginado(servico)

filhos_de = {}
for item in todos_os_itens:
    for pai_id in item.get('parents', []):
        filhos_de.setdefault(pai_id, []).append(item)


def mostrar_nivel(pasta_id, prefixo=''):
    for item in filhos_de.get(pasta_id, []):
        tipo = 'PASTA' if item['mimeType'] == MIME_PASTA else 'arquivo'
        # * [EXPLICAÇÃO] → repr() em vez de print direto — mostra aspas
        #                  ao redor do nome, revelando espaço extra no
        #                  início/fim que passaria despercebido visualmente.
        print(f'{prefixo}[{tipo}] {item["name"]!r}')
        if item['mimeType'] == MIME_PASTA:
            mostrar_nivel(item['id'], prefixo + '    ')


print('Estrutura crua dentro de "Guarany" (nomes entre aspas, pra revelar espaço extra):\n')
mostrar_nivel(ID_PASTA_GUARANY)