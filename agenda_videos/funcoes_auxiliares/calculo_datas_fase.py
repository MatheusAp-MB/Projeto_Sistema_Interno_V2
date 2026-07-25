# agenda_videos/funcoes_auxiliares/calculo_datas_fase.py

# Função Objetivo: Calcula as janelas de data (início/fim) de uma fase inteira e de cada
# ocorrência dentro dela, seguindo as regras de negócio confirmadas com o usuário.
# Explicação em detalhe: funções puras — não tocam banco, não conhecem Django model
# nenhum, só recebem data/número e devolvem data. Regras confirmadas:
#   Diária: conta em dias úteis (pula sáb/dom); feriado NÃO é detectado (simplificação
#           deliberada — vira "Atrasado" normal, sem calendário de feriados).
#   Semanal: cada semana é sempre segunda a sexta.
#   Mensal: cada mês é do dia 1 ao último dia do mês (dias corridos).
# Transição entre fases permite "vão": se o dia seguinte ao fim da fase anterior já cai
# certinho (segunda, pra Semanal; dia 1, pra Mensal), começa nele mesmo, sem pular à toa;
# senão avança até a próxima data redonda.

from dataclasses import dataclass
from datetime import date, timedelta

from agenda_videos.models import Fase


# Função Objetivo: Representa uma janela de data (início/fim), usada tanto pra fase
# inteira quanto pra 1 ocorrência específica.
@dataclass
class JanelaData:
    inicio: date
    fim: date


# Função Objetivo: Ajusta uma data pro próximo dia útil (segunda a sexta).
# Explicação em detalhe: se já for dia útil, devolve a mesma data — nunca pula à toa.
def proximo_dia_util(data_base):
    while data_base.weekday() >= 5:  # 5=sábado, 6=domingo
        data_base += timedelta(days=1)
    return data_base


# Função Objetivo: Ajusta uma data pro ÚLTIMO dia útil (volta no tempo, não avança).
# Explicação em detalhe: usado como "referência de hoje" em qualquer comparação de
# atraso/vencimento — o prazo só corre de verdade em dia útil (confirmado com o
# usuário), então sábado/domingo precisam "virar" a sexta-feira anterior pra esse
# tipo de conta, nunca contar como se fosse 1 dia normal de prazo passando.
def ultimo_dia_util_ou_hoje(data_base):
    while data_base.weekday() >= 5:
        data_base -= timedelta(days=1)
    return data_base


# Função Objetivo: Avança N dias úteis a partir de uma data (que já deve ser dia útil).
# Explicação em detalhe: "avancar_quantidade=0" devolve a própria data_base — usado pra
# calcular a ocorrência 1 (que é o próprio início da fase, sem avançar nada).
def adicionar_dias_uteis(data_base, avancar_quantidade):
    data_atual = data_base
    dias_avancados = 0
    while dias_avancados < avancar_quantidade:
        data_atual += timedelta(days=1)
        if data_atual.weekday() < 5:
            dias_avancados += 1
    return data_atual


# Função Objetivo: Ajusta uma data pra próxima segunda-feira.
# Explicação em detalhe: se já for segunda, devolve a mesma data — nunca pula à toa.
def proxima_segunda(data_base):
    if data_base.weekday() == 0:
        return data_base
    dias_ate_segunda = 7 - data_base.weekday()
    return data_base + timedelta(days=dias_ate_segunda)


# Função Objetivo: Ajusta uma data pro próximo dia 1 de algum mês.
# Explicação em detalhe: se já for dia 1, devolve a mesma data — nunca pula à toa.
def proximo_dia_1(data_base):
    if data_base.day == 1:
        return data_base
    return adicionar_meses(date(data_base.year, data_base.month, 1), 1)


# Função Objetivo: Soma N meses a uma data (sempre devolve dia 1 do mês resultante).
def adicionar_meses(data_base, avancar_quantidade):
    mes_total = data_base.month - 1 + avancar_quantidade
    ano = data_base.year + mes_total // 12
    mes = mes_total % 12 + 1
    return date(ano, mes, 1)


# Função Objetivo: Devolve o último dia do mês de uma data qualquer.
def ultimo_dia_do_mes(data_base):
    inicio_mes_seguinte = adicionar_meses(date(data_base.year, data_base.month, 1), 1)
    return inicio_mes_seguinte - timedelta(days=1)


# Função Objetivo: Calcula a janela (início/fim) da fase inteira.
# Explicação em detalhe: "data_referencia" é o dia seguinte ao fim da fase anterior (ou a
# data de cadastro, se for a Fase Diária de um produto novo) — a função decide se precisa
# ajustar essa data (pra próximo dia útil/segunda/dia 1) ou se ela já serve como início.
def calcular_janela_fase(fase, data_referencia, periodo):
    if fase == Fase.DIARIA:
        inicio = proximo_dia_util(data_referencia)
        fim = adicionar_dias_uteis(inicio, periodo - 1)
    elif fase == Fase.SEMANAL:
        inicio = proxima_segunda(data_referencia)
        fim = inicio + timedelta(days=(periodo - 1) * 7 + 4)
    elif fase == Fase.MENSAL:
        inicio = proximo_dia_1(data_referencia)
        ultimo_mes = adicionar_meses(inicio, periodo - 1)
        fim = ultimo_dia_do_mes(ultimo_mes)
    else:
        raise ValueError(f'Fase desconhecida: {fase}')

    return JanelaData(inicio=inicio, fim=fim)


# Função Objetivo: Calcula a janela (início/fim) de 1 ocorrência específica dentro da fase.
# Explicação em detalhe: "inicio_fase" é sempre o início JÁ AJUSTADO da fase inteira
# (o resultado de calcular_janela_fase().inicio), nunca uma data bruta.
def calcular_janela_ocorrencia(fase, inicio_fase, numero_ocorrencia):
    if fase == Fase.DIARIA:
        data = adicionar_dias_uteis(inicio_fase, numero_ocorrencia - 1)
        return JanelaData(inicio=data, fim=data)
    elif fase == Fase.SEMANAL:
        inicio_semana = inicio_fase + timedelta(days=(numero_ocorrencia - 1) * 7)
        fim_semana = inicio_semana + timedelta(days=4)
        return JanelaData(inicio=inicio_semana, fim=fim_semana)
    elif fase == Fase.MENSAL:
        inicio_mes = adicionar_meses(inicio_fase, numero_ocorrencia - 1)
        fim_mes = ultimo_dia_do_mes(inicio_mes)
        return JanelaData(inicio=inicio_mes, fim=fim_mes)
    else:
        raise ValueError(f'Fase desconhecida: {fase}')