# api_mercado_livre/core/estrutura_api/protecao.py

# Função Objetivo: Cálculo de espera entre tentativas (backoff reativo) —
# movido pra cá de dentro de cliente_api.py (Peça 2 da reforma estrutural
# do app integracao_mercado_livre, ver vault "Modelagem de Objeto e
# Encapsulamento" / "Padrão de Robustez para Clientes de API Externa").
# Puramente estrutural: mesma fórmula, mesmo teto, mesma margem — só
# mudou de arquivo (e perdeu o "_" do nome, agora que é a interface
# pública deste módulo). Sem EspacadorDeChamadas (throttle proativo)
# nesta peça, ao contrário de api_sysemp/core/protecao.py: a API do ML,
# hoje, só é protegida de forma reativa (espera só depois de já levar um
# 429) — adicionar um limitador proativo seria mudança de comportamento,
# decidida à parte se um dia fizer sentido.

import random

TETO_ESPERA_SEGUNDOS = 30
MARGEM_RETRY_AFTER_SEGUNDOS = 2


def calcular_espera_backoff(tentativa: int, resposta) -> float:
    """Usa Retry-After se a API informar; senão backoff exponencial + jitter, com teto de 30s."""
    retry_after = resposta.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after) + MARGEM_RETRY_AFTER_SEGUNDOS
        except ValueError:
            pass

    espera_calculada = (2 ** tentativa) + random.uniform(0, 1)
    return min(espera_calculada, TETO_ESPERA_SEGUNDOS)