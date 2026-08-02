# agenda_videos/tests/test_camada1_calculo_datas_fase.py

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
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Camada 1 — cálculo puro de dia útil'


# ===================================================================
# ultimo_dia_util_ou_hoje — corrige pra TRÁS (nunca avança), só mexe
# se cair em fim de semana.
# ===================================================================

def test_ultimo_dia_util_ou_hoje_mantem_dia_de_semana(tabela_resultados):
    segunda = date(2026, 8, 3)
    resultado = ultimo_dia_util_ou_hoje(segunda)
    passou = resultado == segunda
    registrar_resultado(
        tabela_resultados, 'ultimo_dia_util_mantem_dia_de_semana',
        'segunda 03/08', 'mantém 03/08 (já é dia útil)', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_ultimo_dia_util_ou_hoje_sabado_volta_pra_sexta(tabela_resultados):
    sabado = date(2026, 8, 1)
    sexta_anterior = date(2026, 7, 31)
    resultado = ultimo_dia_util_ou_hoje(sabado)
    passou = resultado == sexta_anterior
    registrar_resultado(
        tabela_resultados, 'ultimo_dia_util_sabado_volta_pra_sexta',
        'sábado 01/08', 'volta pra sexta 31/07', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_ultimo_dia_util_ou_hoje_domingo_volta_pra_sexta(tabela_resultados):
    domingo = date(2026, 8, 2)
    sexta_anterior = date(2026, 7, 31)
    resultado = ultimo_dia_util_ou_hoje(domingo)
    passou = resultado == sexta_anterior
    registrar_resultado(
        tabela_resultados, 'ultimo_dia_util_domingo_volta_pra_sexta',
        'domingo 02/08', 'volta pra sexta 31/07', f'{resultado:%d/%m}', passou,
    )
    assert passou


# ===================================================================
# adicionar_dias_uteis — avança N dias ÚTEIS a partir de uma data que já
# deve ser dia útil (pula fim de semana no meio do caminho).
# ===================================================================

def test_adicionar_dias_uteis_zero_dias_mantem_a_mesma_data(tabela_resultados):
    segunda = date(2026, 8, 3)
    resultado = adicionar_dias_uteis(segunda, 0)
    passou = resultado == segunda
    registrar_resultado(
        tabela_resultados, 'adicionar_dias_uteis_zero_dias',
        'segunda 03/08 + 0 dias úteis', 'mantém 03/08', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_adicionar_dias_uteis_dentro_da_mesma_semana(tabela_resultados):
    segunda = date(2026, 8, 3)
    terca = date(2026, 8, 4)
    resultado = adicionar_dias_uteis(segunda, 1)
    passou = resultado == terca
    registrar_resultado(
        tabela_resultados, 'adicionar_dias_uteis_mesma_semana',
        'segunda 03/08 + 1 dia útil', 'terça 04/08', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_adicionar_dias_uteis_pula_fim_de_semana(tabela_resultados):
    sexta = date(2026, 8, 7)
    segunda_seguinte = date(2026, 8, 10)
    resultado = adicionar_dias_uteis(sexta, 1)
    passou = resultado == segunda_seguinte
    registrar_resultado(
        tabela_resultados, 'adicionar_dias_uteis_pula_fim_de_semana',
        'sexta 07/08 + 1 dia útil', 'segunda 10/08', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_adicionar_dias_uteis_conta_certo_atravessando_o_fim_de_semana(tabela_resultados):
    quinta = date(2026, 8, 6)
    segunda_seguinte = date(2026, 8, 10)  # sexta(1) -> sáb/dom pulados -> segunda(2)
    resultado = adicionar_dias_uteis(quinta, 2)
    passou = resultado == segunda_seguinte
    registrar_resultado(
        tabela_resultados, 'adicionar_dias_uteis_atravessa_fim_de_semana',
        'quinta 06/08 + 2 dias úteis', 'segunda 10/08', f'{resultado:%d/%m}', passou,
    )
    assert passou


# ===================================================================
# proximo_dia_util — SEMPRE avança pelo menos 1 dia (nunca fica na
# própria data_base, mesmo se ela já for dia útil). Usado só na ação
# manual de "Agendar" (dar folga mínima de 1 dia).
# ===================================================================

def test_proximo_dia_util_dia_de_semana_avanca_1_dia(tabela_resultados):
    segunda = date(2026, 8, 3)
    terca = date(2026, 8, 4)
    resultado = proximo_dia_util(segunda)
    passou = resultado == terca
    registrar_resultado(
        tabela_resultados, 'proximo_dia_util_avanca_1_dia',
        'segunda 03/08', 'terça 04/08', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_proximo_dia_util_sexta_pula_pra_segunda(tabela_resultados):
    sexta = date(2026, 8, 7)
    segunda_seguinte = date(2026, 8, 10)
    resultado = proximo_dia_util(sexta)
    passou = resultado == segunda_seguinte
    registrar_resultado(
        tabela_resultados, 'proximo_dia_util_sexta_pula_pra_segunda',
        'sexta 07/08', 'segunda 10/08', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_proximo_dia_util_sabado_pula_pra_segunda(tabela_resultados):
    sabado = date(2026, 8, 1)
    segunda_seguinte = date(2026, 8, 3)
    resultado = proximo_dia_util(sabado)
    passou = resultado == segunda_seguinte
    registrar_resultado(
        tabela_resultados, 'proximo_dia_util_sabado_pula_pra_segunda',
        'sábado 01/08', 'segunda 03/08', f'{resultado:%d/%m}', passou,
    )
    assert passou


def test_proximo_dia_util_domingo_pula_pra_segunda(tabela_resultados):
    domingo = date(2026, 8, 2)
    segunda_seguinte = date(2026, 8, 3)
    resultado = proximo_dia_util(domingo)
    passou = resultado == segunda_seguinte
    registrar_resultado(
        tabela_resultados, 'proximo_dia_util_domingo_pula_pra_segunda',
        'domingo 02/08', 'segunda 03/08', f'{resultado:%d/%m}', passou,
    )
    assert passou