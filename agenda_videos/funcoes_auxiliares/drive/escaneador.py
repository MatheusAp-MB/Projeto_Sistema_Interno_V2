# agenda_videos/funcoes_auxiliares/drive/escaneador.py

# Função Objetivo: Varre TODA a árvore do Drive (raiz + tudo abaixo) numa
# passada só (paginada), reconstruindo marca→EAN→Videos→arquivos via relação
# de pai/filho — em vez de perguntar "o que tem dentro de X?" produto por
# produto. NÃO substitui LocalizadorArquivosProduto (aquele é o caminho
# certo pra 1 produto isolado) — esta varredura serve o "Verificar Todos" e
# qualquer rotina periódica futura. Resultado sempre PERSISTIDO
# (SnapshotArquivosDrive) — dado da API é caro, nunca descartado.

from collections import defaultdict
from agenda_videos.models import SnapshotArquivosDrive
from .cliente import obter_servico_drive, obter_pasta_raiz_id_ativa
from .constantes import MIME_PASTA, NOME_PASTA_VIDEOS, NOME_PASTA_USADOS


def _listar_tudo_paginado(servico):
    todos_os_itens = []
    page_token = None
    while True:
        # * [EXPLICAÇÃO] → Esta é a ÚNICA query do módulo sem filtro de pai —
        #                  varre tudo que a Service Account vê, corpora=
        #                  'allDrives' inclui o conteúdo do Drive
        #                  Compartilhado (sem isso, corpora default 'user'
        #                  nem chega a olhar pra dentro de Drives
        #                  Compartilhados). montar_arvore_por_ean() já filtra
        #                  só o que descende de raiz_id depois, em memória.
        resultado = servico.files().list(
            q='trashed = false',
            fields='nextPageToken, files(id, name, mimeType, parents)',
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora='allDrives',
        ).execute()
        todos_os_itens.extend(resultado.get('files', []))
        page_token = resultado.get('nextPageToken')
        if not page_token:
            break
    return todos_os_itens


# Função Objetivo: Reconstrói {ean: {'marca':..., 'arquivos_videos': [...],
# 'arquivos_usados': [...]}} a partir da lista bruta de itens — pura, sem
# chamada de rede, testável isolado com qualquer lista fabricada.
def montar_arvore_por_ean(todos_os_itens, raiz_id):
    filhos_de = defaultdict(list)
    for item in todos_os_itens:
        for pai_id in item.get('parents', []):
            filhos_de[pai_id].append(item)

    resultado_por_ean = {}

    for pasta_marca in filhos_de.get(raiz_id, []):
        if pasta_marca['mimeType'] != MIME_PASTA:
            continue

        for pasta_ean in filhos_de.get(pasta_marca['id'], []):
            if pasta_ean['mimeType'] != MIME_PASTA:
                continue
            ean = pasta_ean['name']

            pasta_videos = next(
                (f for f in filhos_de.get(pasta_ean['id'], [])
                 if f['name'].lower() == NOME_PASTA_VIDEOS.lower() and f['mimeType'] == MIME_PASTA),
                None,
            )
            if pasta_videos is None:
                continue

            conteudo_videos = filhos_de.get(pasta_videos['id'], [])
            pasta_usados = next(
                (f for f in conteudo_videos
                 if f['name'].lower() == NOME_PASTA_USADOS.lower() and f['mimeType'] == MIME_PASTA),
                None,
            )
            arquivos_videos = [
                {'id': f['id'], 'name': f['name']} for f in conteudo_videos if f['mimeType'] != MIME_PASTA
            ]
            arquivos_usados = []
            if pasta_usados:
                arquivos_usados = [
                    {'id': f['id'], 'name': f['name']} for f in filhos_de.get(pasta_usados['id'], [])
                    if f['mimeType'] != MIME_PASTA
                ]

            resultado_por_ean[ean] = {
                'marca': pasta_marca['name'],
                'arquivos_videos': arquivos_videos,
                'arquivos_usados': arquivos_usados,
            }

    return resultado_por_ean


# Função Objetivo: Varre o Drive inteiro e grava 1 SnapshotArquivosDrive por
# EAN encontrado que tenha Produto correspondente no banco. Devolve
# (quantidade_atualizada, lista_de_eans_sem_produto_no_banco,
# lista_de_ids_de_produto_atualizados) — o 3º valor permite que quem chama
# (verificador.verificar_todos_no_drive) rode o avanço de roadmap em cima do
# snapshot recém-salvo, sem precisar buscar o Drive de novo.
def sincronizar_snapshots_drive():
    from produtos.models import Produto

    servico = obter_servico_drive()
    pasta_raiz_id = obter_pasta_raiz_id_ativa()
    todos_os_itens = _listar_tudo_paginado(servico)
    arvore_por_ean = montar_arvore_por_ean(todos_os_itens, pasta_raiz_id)

    atualizados = 0
    sem_produto_no_banco = []
    produto_ids_atualizados = []

    for ean, dados in arvore_por_ean.items():
        produto = Produto.objects.filter(ean=ean).first()
        if produto is None:
            sem_produto_no_banco.append(ean)
            continue

        SnapshotArquivosDrive.objects.update_or_create(
            produto=produto,
            defaults={
                'pasta_encontrada': True,
                'motivo_nao_encontrado': None,
                'arquivos_videos': dados['arquivos_videos'],
                'arquivos_usados': dados['arquivos_usados'],
            },
        )
        atualizados += 1
        produto_ids_atualizados.append(produto.id)

    return atualizados, sem_produto_no_banco, produto_ids_atualizados