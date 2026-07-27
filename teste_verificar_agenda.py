import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.verificar_arquivos_drive import verificar_produto_no_drive

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EAN_TESTE = '7891117102687'
# ========================================

produto = Produto.objects.filter(ean=EAN_TESTE).first()
if produto is None:
    print(f'Produto com EAN {EAN_TESTE} não encontrado no banco.')
else:
    pontos_marcados, motivo_nao_encontrado, diagnostico = verificar_produto_no_drive(produto.id)

    if motivo_nao_encontrado:
        print(f'Não encontrado no Drive: {motivo_nao_encontrado}')
        exit()

    if pontos_marcados:
        print(f'{len(pontos_marcados)} ponto(s) marcado(s) como pronto:')
        for ponto in pontos_marcados:
            print(f'  - {ponto}')
    else:
        print('Nenhum ponto novo pra marcar.')

    if diagnostico:
        print(f'\n[Situação atual] {diagnostico.mensagem}')