# agenda_videos/tests/test_calculo_datas_fase.py

# Função Objetivo: Testa a matemática pura de dia útil (calculo_datas_fase.py)
# — 1º arquivo de teste automatizado do projeto (camada mais simples: sem
# banco, sem Django, só entrada/saída). Datas fixas de propósito (nunca
# date.today()) — teste tem que dar o mesmo resultado hoje, amanhã e daqui a
# 1 ano, sempre.
#
# Referência de calendário usada nos testes abaixo:
# 2026-08-01 = sábado | 2026-08-02 = domingo | 2026-08-03 = segunda
# 2026-08-06 = quinta | 2026-08-07 = sexta   | 2026-08-10 = segunda (seguinte)

from datetime import date

from agenda_videos.funcoes_auxiliares.calculo_datas_fase import (
    ultimo_dia_util_ou_hoje, adicionar_dias_uteis, proximo_dia_util,
)


# ===================================================================
# ultimo_dia_util_ou_hoje — corrige pra TRÁS (nunca avança), só mexe
# se cair em fim de semana.
# ===================================================================

def test_ultimo_dia_util_ou_hoje_mantem_dia_de_semana():
    segunda = date(2026, 8, 3)
    assert ultimo_dia_util_ou_hoje(segunda) == segunda


def test_ultimo_dia_util_ou_hoje_sabado_volta_pra_sexta():
    sabado = date(2026, 8, 1)
    sexta_anterior = date(2026, 7, 31)
    assert ultimo_dia_util_ou_hoje(sabado) == sexta_anterior


def test_ultimo_dia_util_ou_hoje_domingo_volta_pra_sexta():
    domingo = date(2026, 8, 2)
    sexta_anterior = date(2026, 7, 31)
    assert ultimo_dia_util_ou_hoje(domingo) == sexta_anterior


# ===================================================================
# adicionar_dias_uteis — avança N dias ÚTEIS a partir de uma data que já
# deve ser dia útil (pula fim de semana no meio do caminho).
# ===================================================================

def test_adicionar_dias_uteis_zero_dias_mantem_a_mesma_data():
    segunda = date(2026, 8, 3)
    assert adicionar_dias_uteis(segunda, 0) == segunda


def test_adicionar_dias_uteis_dentro_da_mesma_semana():
    segunda = date(2026, 8, 3)
    terca = date(2026, 8, 4)
    assert adicionar_dias_uteis(segunda, 1) == terca


def test_adicionar_dias_uteis_pula_fim_de_semana():
    sexta = date(2026, 8, 7)
    segunda_seguinte = date(2026, 8, 10)
    assert adicionar_dias_uteis(sexta, 1) == segunda_seguinte


def test_adicionar_dias_uteis_conta_certo_atravessando_o_fim_de_semana():
    quinta = date(2026, 8, 6)
    segunda_seguinte = date(2026, 8, 10)  # sexta(1) -> sáb/dom pulados -> segunda(2)
    assert adicionar_dias_uteis(quinta, 2) == segunda_seguinte


# ===================================================================
# proximo_dia_util — SEMPRE avança pelo menos 1 dia (nunca fica na
# própria data_base, mesmo se ela já for dia útil). Usado só na ação
# manual de "Agendar" (dar folga mínima de 1 dia).
# ===================================================================

def test_proximo_dia_util_dia_de_semana_avanca_1_dia():
    segunda = date(2026, 8, 3)
    terca = date(2026, 8, 4)
    assert proximo_dia_util(segunda) == terca


def test_proximo_dia_util_sexta_pula_pra_segunda():
    sexta = date(2026, 8, 7)
    segunda_seguinte = date(2026, 8, 10)
    assert proximo_dia_util(sexta) == segunda_seguinte


def test_proximo_dia_util_sabado_pula_pra_segunda():
    sabado = date(2026, 8, 1)
    segunda_seguinte = date(2026, 8, 3)
    assert proximo_dia_util(sabado) == segunda_seguinte


def test_proximo_dia_util_domingo_pula_pra_segunda():
    domingo = date(2026, 8, 2)
    segunda_seguinte = date(2026, 8, 3)
    assert proximo_dia_util(domingo) == segunda_seguinte