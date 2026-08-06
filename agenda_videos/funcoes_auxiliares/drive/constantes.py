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