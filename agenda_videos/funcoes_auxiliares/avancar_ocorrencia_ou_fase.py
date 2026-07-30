# agenda_videos/funcoes_auxiliares/avancar_ocorrencia_ou_fase.py

# Função Objetivo: Avança o AndamentoAgenda pra próxima ocorrência ou próxima
# fase — assume que a ocorrência atual já foi tratada (replicada, ou pulada
# via "seguir sem repor"), quem chama decide isso antes de chamar esta
# função. Extraída (30/07) de dentro de views.py — agora tem 4 chamadores:
# clique manual de "replicar", recálculo em massa ao salvar Configuração de
# Fases, "seguir sem repor", e a API de Replicação Automática. Não chama
# .save() sozinha — quem chama decide quando persistir.

from datetime import timedelta
from django.utils import timezone
from agenda_videos.models import Fase, ConfiguracaoFase
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia, calcular_janela_fase

PROXIMA_FASE = {Fase.DIARIA: Fase.SEMANAL, Fase.SEMANAL: Fase.MENSAL}


def avancar_ocorrencia_ou_fase(andamento, ocorrencias_completadas):
    if ocorrencias_completadas < andamento.fase_atual.periodo:
        andamento.ocorrencia_atual = ocorrencias_completadas + 1
    else:
        proxima_fase = PROXIMA_FASE.get(andamento.fase_atual.fase)
        if proxima_fase is None:
            andamento.concluido = True
            andamento.concluido_em = timezone.now().date()
            andamento.concluido_marcado_em = timezone.now()
        else:
            config_proxima = ConfiguracaoFase.objects.filter(fase=proxima_fase).first()
            if config_proxima is None:
                raise ValueError(f'Configuração da fase "{proxima_fase}" ainda não existe.')
            # * [EXPLICAÇÃO] → Referência é a data REAL do fim da última ocorrência
            #                  que de fato aconteceu (nunca andamento.fim_fase, que
            #                  fica desatualizado se o periodo mudar no meio da
            #                  fase).
            janela_ocorrencia_referencia = calcular_janela_ocorrencia(
                andamento.fase_atual.fase, andamento.inicio_fase, ocorrencias_completadas,
            )
            referencia = janela_ocorrencia_referencia.fim + timedelta(days=1)
            janela_proxima = calcular_janela_fase(proxima_fase, referencia, config_proxima.periodo)
            andamento.fase_atual = config_proxima
            andamento.ocorrencia_atual = 1
            andamento.inicio_fase = janela_proxima.inicio
            andamento.fim_fase = janela_proxima.fim

    if not andamento.concluido:
        janela_ocorrencia_nova = calcular_janela_ocorrencia(
            andamento.fase_atual.fase, andamento.inicio_fase, andamento.ocorrencia_atual,
        )
        andamento.fim_ocorrencia_atual = janela_ocorrencia_nova.fim