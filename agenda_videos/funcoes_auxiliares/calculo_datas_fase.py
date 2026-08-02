# agenda_videos/funcoes_auxiliares/calculo_datas_fase.py

# Função Objetivo: Matemática pura de dia útil — ajusta prazos e calcula
# "hoje" pra fins de atraso/vencimento. Nenhuma função aqui toca banco ou
# conhece Django model.
# Reestruturação completa (30/07) — modelo antigo (Diária/Semanal/Mensal,
# cada 1 com regra de janela própria) descartado por inteiro; modelo novo
# só usa dias corridos com ajuste pro último dia útil (ver [[Cadencia de 30
# e 90 Dias Corridos Contados do Replicado]]). Funções de janela de fase e
# os ajustes de calendário de Semanal/Mensal saíram — nenhuma fase as usa mais.

from datetime import date, timedelta


# Função Objetivo: Ajusta uma data pro ÚLTIMO dia útil (volta no tempo, nunca avança).
# * [EXPLICAÇÃO] → Usado como "referência de hoje" em qualquer comparação de
#                  atraso/vencimento — prazo só corre em dia útil, então
#                  sábado/domingo viram a sexta anterior.
def ultimo_dia_util_ou_hoje(data_base: date) -> date:
    while data_base.weekday() >= 5:
        data_base -= timedelta(days=1)
    return data_base


# Função Objetivo: Avança N dias úteis a partir de uma data (que já deve ser dia útil).
def adicionar_dias_uteis(data_base: date, avancar_quantidade: int) -> date:
    data_atual = data_base
    dias_avancados = 0
    while dias_avancados < avancar_quantidade:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5:
            dias_avancados += 1
    return data_atual