# agenda_videos/funcoes_auxiliares/drive/utilitarios_pasta.py

# Função Objetivo: Busca de subpasta/arquivo por nome — compartilhada entre
# LocalizadorArquivosProduto (só lê) e ArquivadorDrive (lê e escreve).
# Corrigido (28/07, pente fino): antes, as 2 classes reimplementavam essa
# mesma query cada uma do seu jeito, sem nenhum código compartilhado.
#
# * [EXPLICAÇÃO] → buscar_arquivo (18/08/2026) é irmã de buscar_subpasta —
#                  mesma busca por nome dentro de 1 pasta pai, mas SEM o
#                  filtro de mimeType = pasta, senão nunca acharia nenhum
#                  arquivo. Usada por ArquivadorDrive.enviar_arquivo pra
#                  checar se já existe um arquivo com esse nome antes de
#                  subir (nunca sobrescreve/duplica sem confirmação).

from .constantes import MIME_PASTA


def buscar_subpasta(servico, pasta_pai_id, nome_subpasta):
    nome_escapado = nome_subpasta.replace("'", "\\'")
    query = (
        f"'{pasta_pai_id}' in parents and name = '{nome_escapado}' "
        f"and mimeType = '{MIME_PASTA}' and trashed = false"
    )
    resultado = servico.files().list(
        q=query, fields='files(id)', supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    arquivos = resultado.get('files', [])
    return arquivos[0]['id'] if arquivos else None


def buscar_ou_criar_subpasta(servico, pasta_pai_id, nome_subpasta):
    # Contraparte de escrita de buscar_subpasta — usada pelo Portal do Drive
    # pra garantir marca/EAN/Videos sem duplicar quando a pasta já existe.
    pasta_id = buscar_subpasta(servico, pasta_pai_id, nome_subpasta)
    if pasta_id is not None:
        return pasta_id

    pasta_nova = servico.files().create(
        body={
            'name': nome_subpasta,
            'mimeType': MIME_PASTA,
            'parents': [pasta_pai_id],
        },
        fields='id',
        supportsAllDrives=True,
    ).execute()
    return pasta_nova['id']


def buscar_arquivo(servico, pasta_pai_id, nome_arquivo):
    # Igual a buscar_subpasta, mas SEM o filtro de mimeType — este busca
    # ARQUIVO (vídeo, roteiro), nunca pasta.
    nome_escapado = nome_arquivo.replace("'", "\\'")
    query = (
        f"'{pasta_pai_id}' in parents and name = '{nome_escapado}' "
        f"and trashed = false"
    )
    resultado = servico.files().list(
        q=query, fields='files(id)', supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    arquivos = resultado.get('files', [])
    return arquivos[0]['id'] if arquivos else None