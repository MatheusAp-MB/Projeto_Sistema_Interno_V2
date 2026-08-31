# agenda_videos/funcoes_auxiliares/drive/constantes.py

# Função Objetivo: Fonte ÚNICA de verdade pra tudo que é convenção fixa da
# estrutura de pastas do Drive — nomes de subpasta, tipo MIME de pasta, e o
# mapeamento fase↔prefixo de arquivo. Nunca redeclarar — sempre importar
# daqui.
#
# * [EXPLICAÇÃO] → Atualizado (05/08) pro modelo novo de fases (Simples/
#                  Vídeo Mensal/Vídeo Trimestral) — substitui por completo o
#                  mapeamento antigo (diaria/semanal/mensal), obsoleto desde
#                  a reestruturação de 30/07 e nunca atualizado até agora.

MIME_PASTA = 'application/vnd.google-apps.folder'

# * [DESCOBERTA, 31/08/2026] → Vídeo gravado direto no Google Vids (editor
#                  de vídeo do Workspace) nunca é um binário normal — é um
#                  "documento" nativo do Google, como um Doc/Sheet. Baixar
#                  via files().get_media() (alt=media) falha com
#                  fileNotDownloadable, e files.export também não serve
#                  (fileNotExportable) — confirmado testando de verdade
#                  contra a API. Único jeito oficial: endpoint LRO
#                  POST files/{id}/download (ver arquivador.py,
#                  _baixar_arquivo_google_vids).
MIME_GOOGLE_VIDS = 'application/vnd.google-apps.vid'
NOME_PASTA_VIDEOS = 'Videos'
NOME_PASTA_USADOS = 'usados'

# * [EXPLICAÇÃO] → Direção canônica: fase (chave interna do sistema, valor
#                  do enum Fase) → prefixo usado no nome do arquivo no Drive.
#                  O sentido inverso (prefixo minúsculo do Drive → fase),
#                  usado pelo parser pra RECONHECER nome de arquivo, é
#                  derivado daqui — nunca redeclarado à parte.
PREFIXO_ARQUIVO_POR_FASE = {'simples': 'Simples', 'video_mensal': 'Mensal', 'video_trimestral': 'Trimestral'}

FASE_POR_PREFIXO_ARQUIVO_MINUSCULO = {
    prefixo.lower(): fase for fase, prefixo in PREFIXO_ARQUIVO_POR_FASE.items()
}