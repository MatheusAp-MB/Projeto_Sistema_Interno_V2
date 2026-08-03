# agenda_videos/funcoes_auxiliares/a_fazer_hoje.py

# Função Objetivo: Calcula os indicadores de urgência (atrasado/risco) de 1
# ciclo específico — usado pra enriquecer a exibição de 1 produto (card,
# modal), nunca pra listar/filtrar em massa. A listagem por tela mora em
# filtros_agenda_videos.py (listar_produtos_agenda_filtrados), que já
# calcula a mesma coisa via annotation SQL pra N produtos de uma vez — aqui
# é só a versão Python de 1 produto por vez.
# listar_a_fazer_hoje() foi removida (Fase 2 do mapa de execução das 5
# telas) — virou listar_produtos_agenda_filtrados(tela=Tela.A_FAZER_HOJE).

from datetime import date

from produtos.models import Produto
from agenda_videos.models import CicloVideo
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje, adicionar_dias_uteis
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import DIAS_RISCO, ETAPAS_EM_PRODUCAO


def calcular_indicadores_ciclo(produto: Produto, ciclo: CicloVideo, data_referencia: date | None = None) -> str:
    data_referencia = data_referencia or date.today()
    hoje = ultimo_dia_util_ou_hoje(data_referencia)
    limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
    etapa = ciclo.etapa_atual()

    produto.a_fazer_hoje_atrasado = ciclo.esta_atrasado(data_referencia)
    produto.a_fazer_hoje_risco = (
        not produto.a_fazer_hoje_atrasado
        and etapa in ETAPAS_EM_PRODUCAO
        and ciclo.data_devida is not None
        and ciclo.data_devida <= limite_risco
    )
    produto.a_fazer_hoje_vencimento = ciclo.data_devida
    produto.a_fazer_hoje_fase = ciclo.fase
    return etapa