# scripts_exploracao_ERP/api_sysemp/core/protecao.py

# Função Objetivo: As 2 peças da blindagem contra chamada excessiva —
# separadas e testáveis isoladamente (composição, não uma classe só fazendo
# tudo). EspacadorDeChamadas é proativo (espera fixa entre chamadas,
# conservador enquanto não sabemos como a API se comporta sob carga);
# calcular_espera_backoff é reativo (só entra quando a própria API já
# respondeu com erro passageiro). Ver "Padrão de Robustez para Clientes de
# API Externa" no vault.

import random
import time

TETO_ESPERA_BACKOFF_SEGUNDOS = 30


class EspacadorDeChamadas:
    # Função Objetivo: Garante um intervalo mínimo entre uma chamada e a
    # próxima, dormindo (bloqueante) o tempo que faltar. Não sabe nada sobre
    # HTTP nem sobre a API — só sobre tempo.

    def __init__(self, intervalo_minimo_segundos=1.0):
        self._intervalo_minimo_segundos = intervalo_minimo_segundos
        self._instante_ultima_chamada = None

    def aguardar(self):
        if self._instante_ultima_chamada is not None:
            tempo_desde_ultima = time.monotonic() - self._instante_ultima_chamada
            tempo_restante = self._intervalo_minimo_segundos - tempo_desde_ultima
            if tempo_restante > 0:
                time.sleep(tempo_restante)
        self._instante_ultima_chamada = time.monotonic()


def calcular_espera_backoff(numero_tentativa, tempo_sugerido_pela_api=None):
    # Função Objetivo: Calcula quanto esperar antes da próxima retentativa
    # de um erro passageiro. Prioridade total pro tempo que a própria API
    # sugerir — só cai pra exponencial com jitter quando ela não informar
    # nada. Teto fixo pra nunca deixar a espera crescer sem limite.
    if tempo_sugerido_pela_api is not None:
        return min(tempo_sugerido_pela_api, TETO_ESPERA_BACKOFF_SEGUNDOS)
    espera_exponencial = 2 ** numero_tentativa
    jitter = random.uniform(0, 1)
    return min(espera_exponencial + jitter, TETO_ESPERA_BACKOFF_SEGUNDOS)