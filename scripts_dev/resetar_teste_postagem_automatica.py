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
from produtos.models import Produto
from agenda_videos.models import Postagem
from agenda_videos.funcoes_auxiliares.drive.localizador import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive_escrita
from agenda_videos.funcoes_auxiliares.drive.utilitarios_pasta import buscar_subpasta
from agenda_videos.funcoes_auxiliares.drive.constantes import NOME_PASTA_USADOS
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EANS_PARA_RESETAR = ['7891117102687', '7891988003199']
# ========================================

localizador = LocalizadorArquivosProduto()
servico_escrita = obter_servico_drive_escrita()
hoje = timezone.now().date()

for ean in EANS_PARA_RESETAR:
    print(f'=== {ean} ===')
    produto = Produto.objects.filter(ean=ean).first()
    if produto is None:
        print('  Não encontrado no banco.')
        continue

    # * [EXPLICAÇÃO] → Generalizado de novo (28/07) — reset de verdade
    #                  limpa TUDO desse produto, não só a última ocorrência
    #                  testada, e força sempre o mesmo ponto de partida
    #                  conhecido (ocorrência 1, vencendo hoje).
    qtd, _ = Postagem.objects.filter(produto=produto).delete()
    print(f'  {qtd} Postagem(ns) apagada(s) (todas, qualquer ocorrência).')

    encontrado, _, motivo, pasta_videos_id = localizador.localizar_arquivos(produto.marca, produto.ean)
    if not encontrado:
        print(f'  Pasta não encontrada no Drive ({motivo}) — não deu pra mover arquivo de volta.')
    else:
        arquivos_usados = localizador.listar_arquivos_usados(pasta_videos_id)
        if not arquivos_usados:
            print('  Nada em usados/ — nenhum arquivo pra mover de volta.')
        else:
            pasta_usados_id = buscar_subpasta(servico_escrita, pasta_videos_id, NOME_PASTA_USADOS)
            for arquivo in arquivos_usados:
                servico_escrita.files().update(
                    fileId=arquivo['id'], addParents=pasta_videos_id, removeParents=pasta_usados_id,
                    fields='id, parents',
                ).execute()
                print(f'  {arquivo["name"]} movido de volta pra Videos/.')

    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento is not None:
        andamento.ocorrencia_atual = 1
        andamento.inicio_fase = hoje
        andamento.fim_ocorrencia_atual = hoje
        andamento.save(update_fields=['ocorrencia_atual', 'inicio_fase', 'fim_ocorrencia_atual'])
        print(f'  Forçado pra ocorrência 1, vencendo hoje ({hoje}).')

    sincronizar_roadmap_agenda_produto(produto)
    print('  Roadmap ressincronizado.')