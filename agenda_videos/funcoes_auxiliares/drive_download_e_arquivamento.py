# agenda_videos/funcoes_auxiliares/drive_download_e_arquivamento.py

# Função Objetivo: Baixa 1 arquivo do Drive por ID pra um caminho local, e
# move arquivo já usado pra subpasta "usados/" dentro de Videos/ — as 2
# operações que fecham o ciclo (baixar → postar → arquivar). Usa o cliente
# de ESCRITA (diferente de drive_arquivos_produto.py, que só lê) — escopo
# maior, usado só aqui, onde é realmente necessário.

import io
import os
from googleapiclient.http import MediaIoBaseDownload
from agenda_videos.funcoes_auxiliares.google_drive_cliente import obter_servico_drive_escrita


# Função Objetivo: Garante a subpasta {pasta_temporaria_raiz}/{ean}/ e devolve
# o caminho completo onde o arquivo deve ser salvo — puro filesystem local,
# nenhuma chamada à API aqui. Organiza por EAN pra a automação de postagem
# (ainda não construída) encontrar o vídeo certo só sabendo o EAN, sem
# precisar adivinhar qual nome de arquivo foi baixado naquela rodada.
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
        query = (
            f"'{pasta_videos_id}' in parents and name = 'usados' "
            f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        resultado = self.servico.files().list(q=query, fields='files(id)').execute()
        encontrados = resultado.get('files', [])
        if encontrados:
            return encontrados[0]['id']

        metadados = {
            'name': 'usados',
            'mimeType': 'application/vnd.google-apps.folder',
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