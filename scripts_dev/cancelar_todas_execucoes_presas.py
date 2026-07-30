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
from agenda_videos.models import ExecucaoPostagemAutomatica, StatusExecucao, StatusItemExecucao

execucoes_presas = ExecucaoPostagemAutomatica.objects.filter(
    status__in=[StatusExecucao.AGUARDANDO_INICIO, StatusExecucao.RODANDO, StatusExecucao.PAUSADO],
)

total = execucoes_presas.count()
if total == 0:
    print('Nenhuma execução presa encontrada.')
else:
    for execucao in execucoes_presas:
        qtd_itens = execucao.itens.exclude(
            status__in=[StatusItemExecucao.CONCLUIDO, StatusItemExecucao.FALHOU, StatusItemExecucao.CANCELADO],
        ).update(status=StatusItemExecucao.CANCELADO)
        execucao.status = StatusExecucao.CANCELADO
        execucao.finalizado_em = timezone.now()
        execucao.save(update_fields=['status', 'finalizado_em'])
        print(f'Execução #{execucao.id} cancelada — {qtd_itens} item(ns) junto.')

    print(f'\n{total} execução(ões) presa(s) cancelada(s) no total.')