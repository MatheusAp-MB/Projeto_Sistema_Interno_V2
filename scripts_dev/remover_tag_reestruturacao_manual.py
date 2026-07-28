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

from produtos.models import Produto
from agenda_videos.models import RoadmapAgenda

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EANS_PARA_LIBERAR = ['7891117102687', '7891988003199']
# ========================================

for ean in EANS_PARA_LIBERAR:
    produto = Produto.objects.filter(ean=ean).first()
    if produto is None:
        print(f'EAN {ean} não encontrado no banco.')
        continue

    roadmap_agenda = getattr(produto, 'roadmap_agenda', None)
    if roadmap_agenda is None:
        print(f'EAN {ean}: sem RoadmapAgenda ainda — nada a remover.')
        continue

    if not roadmap_agenda.reestruturacao_manual:
        print(f'EAN {ean}: já estava sem a tag.')
        continue

    roadmap_agenda.reestruturacao_manual = False
    roadmap_agenda.save(update_fields=['reestruturacao_manual'])
    print(f'EAN {ean}: tag removida.')