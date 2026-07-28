# agenda_videos/funcoes_auxiliares/drive/constantes.py

# Função Objetivo: Fonte ÚNICA de verdade pra tudo que é convenção fixa da
# estrutura de pastas do Drive — nomes de subpasta, tipo MIME de pasta, e o
# mapeamento fase↔prefixo de arquivo. Corrigido (28/07, pente fino): esses 3
# valores estavam redeclarados, cada um em 2-3 arquivos diferentes, sem
# nenhuma fonte compartilhada. Nunca redeclarar — sempre importar daqui.

MIME_PASTA = 'application/vnd.google-apps.folder'
NOME_PASTA_VIDEOS = 'Videos'
NOME_PASTA_USADOS = 'usados'

# * [EXPLICAÇÃO] → Direção canônica: fase (chave interna do sistema) → prefixo
#                  usado no nome do arquivo no Drive. O sentido inverso
#                  (prefixo minúsculo do Drive → fase), usado pelo parser na
#                  hora de RECONHECER nome de arquivo, é derivado daqui —
#                  nunca redeclarado à parte, como acontecia antes.
PREFIXO_ARQUIVO_POR_FASE = {'diaria': 'Diario', 'semanal': 'Semanal', 'mensal': 'Mensal'}

FASE_POR_PREFIXO_ARQUIVO_MINUSCULO = {
    prefixo.lower(): fase for fase, prefixo in PREFIXO_ARQUIVO_POR_FASE.items()
}