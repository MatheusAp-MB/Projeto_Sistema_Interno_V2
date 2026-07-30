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

from django.utils import timezone
from agenda_videos.models import ExecucaoPostagemAutomatica

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EXECUCAO_ID = 7
# ========================================

execucao = ExecucaoPostagemAutomatica.objects.filter(id=EXECUCAO_ID).first()
if execucao is None:
    print(f'Execução #{EXECUCAO_ID} não encontrada.')
else:
    print(f'Status: {execucao.status}')
    print(f'Iniciado em: {execucao.iniciado_em}')
    print(f'Último heartbeat: {execucao.ultimo_heartbeat_agente}')
    print(f'Agora: {timezone.now()}')
    if execucao.ultimo_heartbeat_agente:
        diferenca = (timezone.now() - execucao.ultimo_heartbeat_agente).total_seconds()
        print(f'Segundos desde o último heartbeat: {diferenca}')
    print(f'Propriedade "travada" calculada: {execucao.travada}')