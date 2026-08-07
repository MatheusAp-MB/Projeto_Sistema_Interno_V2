# scripts_exploracao_ERP/api_sysemp/tests/test_nivel_0__protecao.py

# Função Objetivo: Nível 0 (função pura, zero dependência de banco/Django)
# da camada de proteção do cliente Sysemp — EspacadorDeChamadas (throttle
# proativo) e calcular_espera_backoff (backoff reativo). Tempo controlado
# via monkeypatch (time.monotonic/time.sleep), nunca dorme de verdade — sem
# lib de congelar tempo nova, só substitui a função dentro do próprio
# módulo (mesmo padrão já usado no projeto pra evitar dependência nova).
# Ver "Padrao de Robustez para Clientes de API Externa" no vault.

import sys
from pathlib import Path

# scripts_exploracao_ERP/ não é pacote Django — garante que a pasta certa
# esteja no sys.path antes do import local, sem depender de como o pytest
# decide o rootdir pra este arquivo.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from api_sysemp.core.protecao import (
    TETO_ESPERA_BACKOFF_SEGUNDOS,
    EspacadorDeChamadas,
    calcular_espera_backoff,
)
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 0 — api_sysemp.core.protecao'


# ===================================================================
# EspacadorDeChamadas.aguardar — garante intervalo mínimo entre chamadas,
# dormindo só o tempo que faltar. Instantes de monotonic() escolhidos com
# frações exatas em binário (0.25/0.75/1.5) pra comparação de float ser
# sempre exata, nunca approx.
# ===================================================================

def test_aguardar_primeira_chamada_nao_dorme_nada(monkeypatch, tabela_resultados):
    # Setup: nenhuma chamada anterior registrada — monotonic só é lido 1x.
    monkeypatch.setattr('api_sysemp.core.protecao.time.monotonic', lambda: 100.0)
    tempos_dormidos = []
    monkeypatch.setattr('api_sysemp.core.protecao.time.sleep', lambda segundos: tempos_dormidos.append(segundos))
    espacador = EspacadorDeChamadas(intervalo_minimo_segundos=1.0)

    # Exercise
    espacador.aguardar()

    # Assert
    resultado = tempos_dormidos
    esperado = []
    registrar_resultado(
        tabela_resultados, 'aguardar_primeira_chamada_nao_dorme_nada',
        'nenhuma chamada anterior', f'{esperado}',
        'Sem chamada anterior registrada, não há o que esperar — a 1ª chamada sempre passa direto.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar — função pura, sem recurso aberto.


def test_aguardar_chamada_rapida_demais_dorme_o_restante(monkeypatch, tabela_resultados):
    # Setup: 1ª chamada em t=100.0, 2ª em t=100.25 — só 0.25s depois,
    # intervalo mínimo exige 1.0s, falta dormir 0.75s.
    # aguardar() lê monotonic() 1x na 1ª chamada e 2x na 2ª (antes E depois
    # do sleep, pra registrar o instante real de término) — 3 valores, não 2.
    instantes = iter([100.0, 100.25, 101.0])
    monkeypatch.setattr('api_sysemp.core.protecao.time.monotonic', lambda: next(instantes))
    tempos_dormidos = []
    monkeypatch.setattr('api_sysemp.core.protecao.time.sleep', lambda segundos: tempos_dormidos.append(segundos))
    espacador = EspacadorDeChamadas(intervalo_minimo_segundos=1.0)

    # Exercise
    espacador.aguardar()
    espacador.aguardar()

    # Assert
    resultado = tempos_dormidos
    esperado = [0.75]
    registrar_resultado(
        tabela_resultados, 'aguardar_chamada_rapida_demais_dorme_o_restante',
        '1ª em t=100.0, 2ª em t=100.25, intervalo mínimo 1.0', f'{esperado}',
        'Só 0.25s se passou entre as 2 chamadas — falta dormir exatamente 1.0 - 0.25 = 0.75s pra completar o intervalo mínimo.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


def test_aguardar_chamada_apos_intervalo_ja_passado_nao_dorme(monkeypatch, tabela_resultados):
    # Setup: 1ª chamada em t=100.0, 2ª em t=101.5 — já passou do intervalo
    # mínimo de 1.0s, não precisa dormir nada.
    # aguardar() lê monotonic() 1x na 1ª chamada e 2x na 2ª (antes E depois
    # do sleep, que aqui nem acontece) — 3 valores, não 2.
    instantes = iter([100.0, 101.5, 101.5])
    monkeypatch.setattr('api_sysemp.core.protecao.time.monotonic', lambda: next(instantes))
    tempos_dormidos = []
    monkeypatch.setattr('api_sysemp.core.protecao.time.sleep', lambda segundos: tempos_dormidos.append(segundos))
    espacador = EspacadorDeChamadas(intervalo_minimo_segundos=1.0)

    # Exercise
    espacador.aguardar()
    espacador.aguardar()

    # Assert
    resultado = tempos_dormidos
    esperado = []
    registrar_resultado(
        tabela_resultados, 'aguardar_chamada_apos_intervalo_ja_passado_nao_dorme',
        '1ª em t=100.0, 2ª em t=101.5, intervalo mínimo 1.0', f'{esperado}',
        'Já se passaram 1.5s, mais que o intervalo mínimo de 1.0s — tempo_restante fica negativo, não dorme.',
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# calcular_espera_backoff — decisão binária simples (veio sugestão ou não),
# não é cenário mutuamente exclusivo enumerável no sentido do match/case,
# por isso segue com if — não força match/case numa função de 1 decisão.
# ===================================================================

@pytest.mark.parametrize(
    'tempo_sugerido, esperado, motivo',
    [
        (5, 5, 'Tempo sugerido pela própria API (5s) está abaixo do teto (30s) — usa exatamente o valor sugerido.'),
        (999, TETO_ESPERA_BACKOFF_SEGUNDOS, 'Tempo sugerido pela API (999s) passa do teto — nunca deixa a espera crescer sem limite, capa em 30s.'),
    ],
    ids=[
        'tempo_sugerido_abaixo_do_teto_usa_valor_exato',
        'tempo_sugerido_acima_do_teto_e_capado',
    ],
)
def test_calcular_espera_backoff_com_tempo_sugerido_pela_api(tempo_sugerido, esperado, motivo, tabela_resultados):
    # Setup: nada a montar — parametrize já entrega tudo pronto.

    # Exercise
    resultado = calcular_espera_backoff(numero_tentativa=1, tempo_sugerido_pela_api=tempo_sugerido)

    # Assert
    registrar_resultado(
        tabela_resultados, f'calcular_espera_backoff_sugerido_{tempo_sugerido}',
        f'tempo_sugerido_pela_api={tempo_sugerido}', f'{esperado}', motivo,
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


@pytest.mark.parametrize(
    'numero_tentativa, jitter_mockado, esperado, motivo',
    [
        (1, 0.0, 2.0, 'Sem sugestão da API: exponencial puro (2**1=2) + jitter travado em 0 pra ficar exato.'),
        (3, 0.5, 8.5, 'Exponencial (2**3=8) + jitter travado em 0.5 — 8.5, ainda abaixo do teto de 30s.'),
        (10, 0.0, TETO_ESPERA_BACKOFF_SEGUNDOS, 'Exponencial (2**10=1024) explode muito acima do teto — capado em 30s mesmo com jitter zero.'),
    ],
    ids=[
        'sem_sugestao_tentativa_1_jitter_zero',
        'sem_sugestao_tentativa_3_jitter_meio',
        'sem_sugestao_tentativa_alta_respeita_teto',
    ],
)
def test_calcular_espera_backoff_sem_sugestao_usa_exponencial_com_jitter(
    numero_tentativa, jitter_mockado, esperado, motivo, monkeypatch, tabela_resultados,
):
    # Setup: trava o jitter aleatório num valor fixo — sem isso o resultado
    # não seria reproduzível (regra do projeto: esperado sempre exato).
    monkeypatch.setattr('api_sysemp.core.protecao.random.uniform', lambda a, b: jitter_mockado)

    # Exercise
    resultado = calcular_espera_backoff(numero_tentativa=numero_tentativa, tempo_sugerido_pela_api=None)

    # Assert
    registrar_resultado(
        tabela_resultados, f'calcular_espera_backoff_exponencial_tentativa_{numero_tentativa}',
        f'numero_tentativa={numero_tentativa}, jitter={jitter_mockado}', f'{esperado}', motivo,
        f'{resultado}', resultado == esperado,
    )
    assert resultado == esperado

    # TearDown: nada a desmontar.


# ===================================================================
# Caso de falha proposital — nunca remover (ver "Modelo Padrao de Arquivo
# de Teste"). Prova que a tabela mostra FALHOU corretamente e que o pytest
# distingue falha esperada (xfailed) de falha real (failed).
# ===================================================================

@pytest.mark.xfail(reason='Falha de propósito — prova visual de como fica a linha FALHOU na tabela')
def test_calcular_espera_backoff_caso_de_falha_proposital(tabela_resultados):
    # Setup: valor errado de propósito — o teto real é 30, nunca 31.
    esperado_errado = TETO_ESPERA_BACKOFF_SEGUNDOS + 1

    # Exercise
    resultado = calcular_espera_backoff(numero_tentativa=1, tempo_sugerido_pela_api=999)

    # Assert
    registrar_resultado(
        tabela_resultados, 'calcular_espera_backoff_caso_de_falha_proposital',
        'tempo_sugerido_pela_api=999', f'{esperado_errado}',
        'Propositalmente errado — o teto real é 30, nunca 31. Existe só pra provar que a tabela mostra FALHOU corretamente.',
        f'{resultado}', resultado == esperado_errado,
    )
    assert resultado == esperado_errado

    # TearDown: nada a desmontar.