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
from agenda_videos.models import Postagem, ExecucaoPostagemAutomatica, StatusExecucao, StatusItemExecucao
from agenda_videos.funcoes_auxiliares.drive.localizador import LocalizadorArquivosProduto
from agenda_videos.funcoes_auxiliares.drive.cliente import obter_servico_drive_escrita
from agenda_videos.funcoes_auxiliares.drive.utilitarios_pasta import buscar_subpasta
from agenda_videos.funcoes_auxiliares.drive.constantes import NOME_PASTA_USADOS
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EANS_PARA_RESETAR = ['7891117102687', '7891988003199']
# ========================================

hoje = timezone.now().date()


# * [EXPLICAÇÃO] → PARTE 1 (29/07, adicionada depois do incidente de 2
#                  execuções concorrentes derrubando o servidor) — encerra
#                  qualquer Execução presa (Aguardando Início/Rodando/
#                  Pausado), que travaria uma nova de começar. Não depende
#                  de EAN nenhum — é estado do SISTEMA, não do produto.
print('=== Encerrando execuções presas ===')
execucoes_presas = ExecucaoPostagemAutomatica.objects.filter(
    status__in=[StatusExecucao.AGUARDANDO_INICIO, StatusExecucao.RODANDO, StatusExecucao.PAUSADO],
)
if not execucoes_presas.exists():
    print('  Nenhuma execução presa encontrada.')
else:
    for execucao in execucoes_presas:
        qtd_itens = execucao.itens.exclude(
            status__in=[StatusItemExecucao.CONCLUIDO, StatusItemExecucao.FALHOU, StatusItemExecucao.CANCELADO],
        ).update(status=StatusItemExecucao.CANCELADO)
        execucao.status = StatusExecucao.CANCELADO
        execucao.finalizado_em = timezone.now()
        execucao.save(update_fields=['status', 'finalizado_em'])
        print(f'  Execução #{execucao.id} (estava presa) encerrada — {qtd_itens} item(ns) cancelado(s) junto.')

print()
print('=== Resetando produtos de teste ===')

localizador = LocalizadorArquivosProduto()
servico_escrita = obter_servico_drive_escrita()

for ean in EANS_PARA_RESETAR:
    print(f'--- {ean} ---')
    produto = Produto.objects.filter(ean=ean).first()
    if produto is None:
        print('  Não encontrado no banco.')
        continue

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

print()
print('Concluído.')