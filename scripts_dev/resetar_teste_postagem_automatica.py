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
from agenda_videos.models import Postagem, Fase
from agenda_videos.funcoes_auxiliares.drive.localizador import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive_escrita
from agenda_videos.funcoes_auxiliares.drive.utilitarios_pasta import buscar_subpasta
from agenda_videos.funcoes_auxiliares.drive.constantes import NOME_PASTA_USADOS
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EANS_PARA_RESETAR = ['7891117102687', '7891988003199']
NOME_ARQUIVO_DIA_01 = 'Diario_01.mp4'
# ========================================

localizador = LocalizadorArquivosProduto()
servico_escrita = obter_servico_drive_escrita()

for ean in EANS_PARA_RESETAR:
    print(f'=== {ean} ===')
    produto = Produto.objects.filter(ean=ean).first()
    if produto is None:
        print('  Não encontrado no banco.')
        continue

    qtd, _ = Postagem.objects.filter(produto=produto, fase=Fase.DIARIA, numero_ocorrencia=1).delete()
    print(f'  {qtd} Postagem(ns) apagada(s) (Diária, ocorrência 1).')

    encontrado, _, motivo, pasta_videos_id = localizador.localizar_arquivos(produto.marca, produto.ean)
    if not encontrado:
        print(f'  Pasta não encontrada no Drive ({motivo}) — não deu pra mover o arquivo de volta.')
        continue

    arquivos_usados = localizador.listar_arquivos_usados(pasta_videos_id)
    arquivo_usado = next(
        (a for a in arquivos_usados if a['name'].lower() == NOME_ARQUIVO_DIA_01.lower()), None,
    )
    if arquivo_usado is None:
        print(f'  {NOME_ARQUIVO_DIA_01} não está em usados/ — talvez já esteja de volta em Videos/.')
    else:
        pasta_usados_id = buscar_subpasta(servico_escrita, pasta_videos_id, NOME_PASTA_USADOS)
        servico_escrita.files().update(
            fileId=arquivo_usado['id'], addParents=pasta_videos_id, removeParents=pasta_usados_id,
            fields='id, parents',
        ).execute()
        print(f'  {NOME_ARQUIVO_DIA_01} movido de volta pra Videos/.')

    sincronizar_roadmap_agenda_produto(produto)
    print('  Roadmap ressincronizado.')