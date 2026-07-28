# agenda_videos/funcoes_auxiliares/drive/arquivador.py

# Função Objetivo: Baixa 1 arquivo do Drive por ID pra um caminho local, e
# move arquivo já usado pra subpasta "usados/" dentro de Videos/ — as 2
# operações que fecham o ciclo (baixar → postar → arquivar). Usa o cliente
# de ESCRITA (diferente de localizador.py, que só lê).
#
# * [ATENÇÃO] → Ainda sem nenhum chamador em produção (28/07) — infraestrutura
#               construída deliberadamente pra postagem automática (feature
#               futura já planejada), não código morto esquecido. Mantido de
#               propósito.

import os
from googleapiclient.http import MediaIoBaseDownload
from .cliente import obter_servico_drive_escrita
from .constantes import NOME_PASTA_USADOS, MIME_PASTA
from .utilitarios_pasta import buscar_subpasta


# Função Objetivo: Garante a subpasta {pasta_temporaria_raiz}/{ean}/ e devolve
# o caminho completo onde o arquivo deve ser salvo — puro filesystem local,
# nenhuma chamada à API aqui. Organiza por EAN pra a automação de postagem
# encontrar o vídeo certo só sabendo o EAN, sem precisar adivinhar o nome do
# arquivo baixado naquela rodada.
def montar_caminho_local_organizado(pasta_temporaria_raiz, ean, nome_arquivo):
    pasta_produto = os.path.join(pasta_temporaria_raiz, ean)
    os.makedirs(pasta_produto, exist_ok=True)
    return os.path.join(pasta_produto, nome_arquivo)


class ArquivadorDrive:

    def __init__(self):
        self.servico = obter_servico_drive_escrita()

    # Função Objetivo: Baixa o conteúdo de 1 arquivo (por ID) pro caminho
    # local informado — streaming em pedaços, nunca carrega tudo na memória.
    def baixar_arquivo(self, drive_file_id, caminho_destino_local):
        requisicao = self.servico.files().get_media(fileId=drive_file_id)
        with open(caminho_destino_local, 'wb') as arquivo_local:
            downloader = MediaIoBaseDownload(arquivo_local, requisicao)
            concluido = False
            while not concluido:
                _, concluido = downloader.next_chunk()

    # Função Objetivo: Acha a subpasta "usados" dentro de Videos/ — cria se
    # ainda não existir (1ª vez que qualquer arquivo é arquivado ali).
    def _obter_ou_criar_pasta_usados(self, pasta_videos_id):
        pasta_usados_id = buscar_subpasta(self.servico, pasta_videos_id, NOME_PASTA_USADOS)
        if pasta_usados_id:
            return pasta_usados_id

        metadados = {
            'name': NOME_PASTA_USADOS,
            'mimeType': MIME_PASTA,
            'parents': [pasta_videos_id],
        }
        pasta_nova = self.servico.files().create(body=metadados, fields='id').execute()
        return pasta_nova['id']

    # Função Objetivo: Move 1 arquivo (por ID) de dentro de Videos/ pra
    # Videos/usados/ — troca de "pai", não existe comando "mover" de verdade.
    def mover_para_usados(self, drive_file_id, pasta_videos_id):
        pasta_usados_id = self._obter_ou_criar_pasta_usados(pasta_videos_id)
        self.servico.files().update(
            fileId=drive_file_id,
            addParents=pasta_usados_id,
            removeParents=pasta_videos_id,
            fields='id, parents',
        ).execute()