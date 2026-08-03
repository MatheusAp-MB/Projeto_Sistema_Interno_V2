# agenda_videos/tests/test_camada1_calculo_datas_fase.py

# Função Objetivo: Testa a matemática pura de dia útil (calculo_datas_fase.py)
# — Nível 0: não depende de nada, nem banco nem Django. Nenhuma das 3 funções
# tem cenário exclusivo/branch pra enumerar, por isso nenhuma usa match/case.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.
#
# Referência de calendário usada nos testes abaixo:
# 2026-08-01 = sábado | 2026-08-02 = domingo | 2026-08-03 = segunda
# 2026-08-06 = quinta | 2026-08-07 = sexta   | 2026-08-10 = segunda (seguinte)

from datetime import date

import pytest

from agenda_videos.funcoes_auxiliares.calculo_datas_fase import (
    ultimo_dia_util_ou_hoje, adicionar_dias_uteis, proximo_dia_util,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — cálculo puro de dia útil'


# ===================================================================
# ultimo_dia_util_ou_hoje — corrige pra TRÁS (nunca avança), só mexe se
# cair em fim de semana. Referência de "hoje" em qualquer comparação de
# atraso/vencimento.
# ===================================================================

@pytest.mark.parametrize(
    'data_base, esperado, motivo',
    [
        (date(2026, 8, 3), date(2026, 8, 3), 'segunda já é dia útil, não mexe'),
        (date(2026, 8, 1), date(2026, 7, 31), 'sábado volta pra sexta anterior'),
        (date(2026, 8, 2), date(2026, 7, 31), 'domingo volta pra sexta anterior'),
    ],
    ids=['dia_de_semana_mantem', 'sabado_volta_pra_sexta', 'domingo_volta_pra_sexta'],
)
def test_ultimo_dia_util_ou_hoje(data_base, esperado, motivo, tabela_resultados):
    # Setup: nada pra montar — valores já vêm prontos do parametrize.

    # Exercise: chama o SUT de verdade.
    resultado = ultimo_dia_util_ou_hoje(data_base)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, f'ultimo_dia_util_{data_base:%d-%m}',
        f'{data_base:%d/%m} ({data_base.strftime("%A")})', f'{esperado:%d/%m}', motivo,
        f'{resultado:%d/%m}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — função pura, sem estado, sem recurso aberto.


# ===================================================================
# adicionar_dias_uteis — avança N dias ÚTEIS a partir de data já útil,
# pulando fim de semana no meio. Usada no cálculo do limite de risco.
# ===================================================================

@pytest.mark.parametrize(
    'data_base, quantidade, esperado, motivo',
    [
        (date(2026, 8, 3), 0, date(2026, 8, 3), '0 dias úteis não move a data'),
        (date(2026, 8, 3), 1, date(2026, 8, 4), 'segunda + 1 dia útil = terça, sem fim de semana no meio'),
        (date(2026, 8, 7), 1, date(2026, 8, 10), 'sexta + 1 dia útil pula sáb/dom, cai segunda'),
        (date(2026, 8, 6), 2, date(2026, 8, 10), 'quinta + 2 dias úteis: sexta(1) -> pula fim de semana -> segunda(2)'),
    ],
    ids=[
        'zero_dias_mantem_a_mesma_data', 'dentro_da_mesma_semana',
        'pula_fim_de_semana_a_partir_de_sexta', 'conta_certo_atravessando_o_fim_de_semana',
    ],
)
def test_adicionar_dias_uteis(data_base, quantidade, esperado, motivo, tabela_resultados):
    # Setup: nada pra montar — valores já vêm prontos do parametrize.

    # Exercise: chama o SUT de verdade.
    resultado = adicionar_dias_uteis(data_base, quantidade)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, f'adicionar_dias_uteis_{data_base:%d-%m}_mais_{quantidade}',
        f'{data_base:%d/%m} ({data_base.strftime("%A")}) + {quantidade} dia(s) útil(eis)',
        f'{esperado:%d/%m}', motivo, f'{resultado:%d/%m}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — mesmo motivo do teste anterior.


# ===================================================================
# proximo_dia_util — SEMPRE avança pelo menos 1 dia (nunca fica na
# própria data_base, mesmo se já for dia útil) — diferente de
# ultimo_dia_util_ou_hoje de propósito. Usada só no clique manual "Agendar".
# ===================================================================

@pytest.mark.parametrize(
    'data_base, esperado, motivo',
    [
        (date(2026, 8, 3), date(2026, 8, 4), 'segunda avança pra terça — nunca fica no mesmo dia, mesmo já sendo útil'),
        (date(2026, 8, 7), date(2026, 8, 10), 'sexta pula sáb/dom, cai segunda'),
        (date(2026, 8, 1), date(2026, 8, 3), 'sábado pula pro dia útil seguinte, segunda'),
        (date(2026, 8, 2), date(2026, 8, 3), 'domingo pula pro dia útil seguinte, segunda'),
    ],
    ids=[
        'dia_de_semana_avanca_1_dia', 'sexta_pula_pra_segunda',
        'sabado_pula_pra_segunda', 'domingo_pula_pra_segunda',
    ],
)
def test_proximo_dia_util(data_base, esperado, motivo, tabela_resultados):
    # Setup: nada pra montar — valores já vêm prontos do parametrize.

    # Exercise: chama o SUT de verdade.
    resultado = proximo_dia_util(data_base)

    # Assert: registra antes de comparar, depois compara de verdade.
    registrar_resultado(
        tabela_resultados, f'proximo_dia_util_{data_base:%d-%m}',
        f'{data_base:%d/%m} ({data_base.strftime("%A")})', f'{esperado:%d/%m}', motivo,
        f'{resultado:%d/%m}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — mesmo motivo dos testes anteriores.