import os
import django
from rich import print

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from agenda_videos.funcoes_auxiliares.drive_arquivos_produto import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.parser_arquivos_drive import (
    parsear_arquivos_produto, montar_produto_nao_encontrado,
)

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MARCA_TESTE = 'TRAMONTINA'
EAN_TESTE = '7891117102687'
# ========================================

localizador = LocalizadorArquivosProduto()

# * [EXPLICAÇÃO] → Roda 2 vezes de propósito — 1ª vez "fria" (nada em cache),
#                  2ª vez "quente" (pasta da marca já em cache) — pra medir a
#                  diferença real de custo entre produto novo e produto que
#                  já é da mesma marca de outro já verificado na mesma rodada.
for rodada in ('fria', 'quente (mesma marca em cache)'):
    encontrado, nomes_arquivos, motivo, pasta_videos_id = localizador.localizar_arquivos(MARCA_TESTE, EAN_TESTE)
    if not encontrado:
        resultado = montar_produto_nao_encontrado(MARCA_TESTE, EAN_TESTE, motivo)
    else:
        resultado = parsear_arquivos_produto(MARCA_TESTE, EAN_TESTE, nomes_arquivos)
    print(f'--- Rodada {rodada} — chamadas acumuladas até aqui: {localizador.chamadas_realizadas} ---')

print()
print(resultado)