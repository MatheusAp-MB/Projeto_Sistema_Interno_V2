# agenda_videos/funcoes_auxiliares/drive/utilitarios_pasta.py

# Função Objetivo: Busca de subpasta por nome — compartilhada entre
# LocalizadorArquivosProduto (só lê) e ArquivadorDrive (lê e escreve).
# Corrigido (28/07, pente fino): antes, as 2 classes reimplementavam essa
# mesma query cada uma do seu jeito, sem nenhum código compartilhado.

from .constantes import MIME_PASTA


def buscar_subpasta(servico, pasta_pai_id, nome_subpasta):
    nome_escapado = nome_subpasta.replace("'", "\\'")
    query = (
        f"'{pasta_pai_id}' in parents and name = '{nome_escapado}' "
        f"and mimeType = '{MIME_PASTA}' and trashed = false"
    )
    resultado = servico.files().list(q=query, fields='files(id)').execute()
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
    ).execute()
    return pasta_nova['id']