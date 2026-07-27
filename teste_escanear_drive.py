import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from agenda_videos.funcoes_auxiliares.escanear_drive_completo import sincronizar_snapshots_drive
from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.diagnostico_preparo_drive import calcular_diagnostico_preparo_drive

atualizados, sem_produto = sincronizar_snapshots_drive()
print(f'{atualizados} snapshot(s) atualizado(s).')
if sem_produto:
    print(f'\n{len(sem_produto)} EAN(s) encontrados no Drive sem Produto correspondente no banco:')
    for ean in sem_produto:
        print(f'  - {ean}')

# ==== CONFIGURA AQUI PRA VER O DIAGNÓSTICO DE 1 PRODUTO ESPECÍFICO ====
EAN_TESTE = '7891117102687'
# ========================================================================

produto = Produto.objects.filter(ean=EAN_TESTE).first()
if produto:
    diagnostico = calcular_diagnostico_preparo_drive(produto)
    print(f'\nDiagnóstico de {EAN_TESTE}: {diagnostico}')