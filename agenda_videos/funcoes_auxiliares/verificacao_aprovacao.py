# agenda_videos/funcoes_auxiliares/verificacao_aprovacao.py

# Função Objetivo: Lista os ciclos atualmente "Aguardando Aprovação" com MLB
# postado conhecido — é a fila que o botão "Verificar Aprovação de Todos"
# manda pro agente local conferir na tela do Mercado Livre.
# Fase 1 (27/08): só LEITURA — nenhuma escrita no banco acontece a partir
# daqui. A escrita (marcar_aprovado/marcar_recusado) fica pra fase 2.

from agenda_videos.models import CicloVideo, StatusPostagem


def listar_ciclos_aguardando_aprovacao_com_mlb():
    return list(
        CicloVideo.objects
        .filter(status=StatusPostagem.AGUARDANDO_APROVACAO)
        .exclude(mlb_postado__isnull=True).exclude(mlb_postado='')
        .select_related('produto')
        .order_by('aguardando_aprovacao_em')
    )