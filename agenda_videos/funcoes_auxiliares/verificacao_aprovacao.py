# agenda_videos/funcoes_auxiliares/verificacao_aprovacao.py

# Função Objetivo: Lista os ciclos atualmente "Aguardando Aprovação" com MLB
# postado conhecido — é a fila que o botão "Verificar Aprovação de Todos"
# manda pro agente local conferir na tela do Mercado Livre.
# Fase 1 (27/08): só LEITURA. Fase 2 (01/09): aplicar_estado_lido() abaixo
# faz a escrita, mas só quando o estado lido tem mapeamento certo (ver
# MAPEAMENTO_ESTADO_PARA_STATUS).

from agenda_videos.models import CicloVideo, StatusPostagem


def listar_ciclos_aguardando_aprovacao_com_mlb():
    return list(
        CicloVideo.objects
        .filter(status=StatusPostagem.AGUARDANDO_APROVACAO)
        .exclude(mlb_postado__isnull=True).exclude(mlb_postado='')
        .select_related('produto')
        .order_by('aguardando_aprovacao_em')
    )


# * [DECISÃO, 01/09] → Só 2 dos 4 estados reais têm mapeamento — os outros
#                  2 (EM REVISÃO, PAUSADO) e o caso de não achar nenhum
#                  estado na tela (None — inclui o caso de anúncio ficar
#                  inativo e nunca receber o vídeo de verdade, achado real
#                  de 31/08) ficam sem mudança de propósito: só mexe no
#                  status quando dá pra confirmar com certeza o que
#                  aconteceu. Ciclo continua na fila e tenta de novo na
#                  próxima verificação.
MAPEAMENTO_ESTADO_PARA_STATUS = {
    'PUBLICADO': StatusPostagem.APROVADO,
    'RECUSADO': StatusPostagem.RECUSADO,
}


# Função Objetivo: Único ponto de escrita da Verificação de Aprovação —
# aplica o estado lido na tela do ML ao ciclo correspondente (achado pelo
# mlb_postado, filtrando só quem ainda está Aguardando Aprovação — evita
# reagir a um ciclo que já mudou de status por outro caminho). Devolve uma
# palavra curta pro log/API entenderem o que aconteceu.
def aplicar_estado_lido(mlb, estado):
    novo_status = MAPEAMENTO_ESTADO_PARA_STATUS.get(estado)
    if novo_status is None:
        return 'sem_mudanca'

    ciclo = (
        CicloVideo.objects
        .filter(status=StatusPostagem.AGUARDANDO_APROVACAO, mlb_postado=mlb)
        .first()
    )
    if ciclo is None:
        return 'ciclo_nao_encontrado'

    ciclo.marcar_aprovado_ou_recusado(novo_status)
    return 'atualizado'