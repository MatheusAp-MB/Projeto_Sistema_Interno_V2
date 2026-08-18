# agenda_videos/funcoes_auxiliares/drive/arquivador.py

# Função Objetivo: Baixa 1 arquivo do Drive por ID pra um caminho local, e
# move arquivo já usado pra subpasta "usados/" dentro de Videos/ — as 2
# operações que fecham o ciclo (baixar → postar → arquivar). Usa o cliente
# de ESCRITA (diferente de localizador.py, que só lê).
#
# * [ATENÇÃO] → enviar_arquivo (18/08/2026) é o 1º chamador real —
#               baixar_arquivo/mover_para_usados seguem sem chamador em
#               produção (feature de postagem automática, já planejada),
#               não código morto esquecido. Mantido de propósito.

import os
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from .cliente import obter_servico_drive_escrita
from .constantes import NOME_PASTA_USADOS, NOME_PASTA_VIDEOS, MIME_PASTA, PREFIXO_ARQUIVO_POR_FASE
from .parser import EXTENSOES_VALIDAS_POR_TIPO
from .utilitarios_pasta import buscar_subpasta, buscar_ou_criar_subpasta, buscar_arquivo


# Função Objetivo: Garante a subpasta {pasta_temporaria_raiz}/{ean}/ e devolve
# o caminho completo onde o arquivo deve ser salvo — puro filesystem local,
# nenhuma chamada à API aqui. Organiza por EAN pra a automação de postagem
# encontrar o vídeo certo só sabendo o EAN, sem precisar adivinhar o nome do
# arquivo baixado naquela rodada.
def montar_caminho_local_organizado(pasta_temporaria_raiz, ean, nome_arquivo):
    pasta_produto = os.path.join(pasta_temporaria_raiz, ean)
    os.makedirs(pasta_produto, exist_ok=True)
    return os.path.join(pasta_produto, nome_arquivo)


# Função Objetivo: Monta o nome CANÔNICO do arquivo pra uma fase/ocorrência/
# tipo — sentido inverso do que parser.py reconhece (mesma convenção,
# PREFIXO_ARQUIVO_POR_FASE e EXTENSOES_VALIDAS_POR_TIPO, fonte única em
# constantes.py/parser.py, nunca redeclarada aqui). 'simples' nunca leva
# número (Simples_Base.mp4); Mensal/Trimestral sempre levam, 2 dígitos
# (Mensal_01_Roteiro.txt).
def montar_nome_arquivo(fase, numero_ocorrencia, tipo):
    prefixo = PREFIXO_ARQUIVO_POR_FASE[fase]
    extensao = EXTENSOES_VALIDAS_POR_TIPO[tipo]
    tipo_capitalizado = tipo.capitalize()
    if fase == 'simples':
        return f'{prefixo}_{tipo_capitalizado}.{extensao}'
    return f'{prefixo}_{numero_ocorrencia:02d}_{tipo_capitalizado}.{extensao}'


class ArquivadorDrive:

    def __init__(self):
        self.servico = obter_servico_drive_escrita()

    # Função Objetivo: Baixa o conteúdo de 1 arquivo (por ID) pro caminho
    # local informado — streaming em pedaços, nunca carrega tudo na memória.
    def baixar_arquivo(self, drive_file_id, caminho_destino_local):
        requisicao = self.servico.files().get_media(fileId=drive_file_id, supportsAllDrives=True)
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
        pasta_nova = self.servico.files().create(body=metadados, fields='id', supportsAllDrives=True).execute()
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
            supportsAllDrives=True,
        ).execute()

    # Função Objetivo: Sobe 1 arquivo local pro Drive, dentro de
    # {pasta_raiz_id}/{marca}/{ean}/Videos/ — acha-ou-cria a cadeia inteira
    # (buscar_ou_criar_subpasta, 3x). pasta_raiz_id vem de fora (não resolve
    # obter_pasta_raiz_id_ativa() aqui dentro) de propósito: mantém a função
    # testável com qualquer pasta-raiz (inclusive a sandbox de teste), sem
    # depender de sessão/empresa ativa — quem chama já resolveu isso antes.
    #
    # Se já existe um arquivo com o nome canônico em Videos/:
    #   - permitir_substituir=False (padrão): levanta FileExistsError, NADA
    #     muda no Drive — decisão de sobrescrever é do usuário (modal de
    #     confirmação na tela, fora daqui).
    #   - permitir_substituir=True: substitui o CONTEÚDO do arquivo
    #     existente (files().update com media_body), mantendo o MESMO ID —
    #     nunca cria um 2º arquivo duplicado.
    def enviar_arquivo(self, pasta_raiz_id, marca, ean, fase, numero_ocorrencia, tipo, caminho_local, permitir_substituir=False):
        pasta_marca_id = buscar_ou_criar_subpasta(self.servico, pasta_raiz_id, marca)
        pasta_ean_id = buscar_ou_criar_subpasta(self.servico, pasta_marca_id, ean)
        pasta_videos_id = buscar_ou_criar_subpasta(self.servico, pasta_ean_id, NOME_PASTA_VIDEOS)

        nome_arquivo = montar_nome_arquivo(fase, numero_ocorrencia, tipo)
        arquivo_existente_id = buscar_arquivo(self.servico, pasta_videos_id, nome_arquivo)
        media = MediaFileUpload(caminho_local, resumable=True)

        if arquivo_existente_id is None:
            arquivo_novo = self.servico.files().create(
                body={'name': nome_arquivo, 'parents': [pasta_videos_id]},
                media_body=media,
                fields='id',
                supportsAllDrives=True,
            ).execute()
            return arquivo_novo['id']

        if not permitir_substituir:
            raise FileExistsError(
                f"Já existe um arquivo '{nome_arquivo}' em Videos/ — "
                f"passe permitir_substituir=True pra confirmar a substituição."
            )

        self.servico.files().update(
            fileId=arquivo_existente_id,
            media_body=media,
            fields='id',
            supportsAllDrives=True,
        ).execute()
        return arquivo_existente_id