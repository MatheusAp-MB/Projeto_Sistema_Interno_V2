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

from agenda_videos.models import ExecucaoPostagemAutomatica, StatusExecucao

# * [RESUMO] → Cria uma execução VAZIA (sem nenhum item), só pra testar se o
# JavaScript da tela de progresso consegue avisar o agente local — não
# depende de produto elegível nenhum.

execucao = ExecucaoPostagemAutomatica.objects.create(status=StatusExecucao.AGUARDANDO_INICIO)
print(f'Execução de teste criada: #{execucao.id}')
print(f'Abra esta URL no navegador: http://127.0.0.1:8000/agenda-videos/postagem-automatica/{execucao.id}/progresso/')