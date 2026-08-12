"""
core/estrutura_api/cliente_api.py

Camada única de comunicação com a API do Mercado Livre.
Todo app deve chamar a API através de chamar_api(), nunca via requests direto.
"""

import re
import time
import random
import json
import logging
from pathlib import Path
from rich.logging import RichHandler

import requests

from api_mercado_livre.core.auth.gerenciador_token import obter_token_valido

BASE_URL = "https://api.mercadolibre.com"

TIMEOUT_CONEXAO_SEGUNDOS = 10
TIMEOUT_LEITURA_SEGUNDOS = 30
TETO_ESPERA_SEGUNDOS = 30
MARGEM_RETRY_AFTER_SEGUNDOS = 2
ESPERA_RETRY_206_SEGUNDOS = 2

DADOS_SENSIVEIS = {"access_token", "refresh_token",
                   "client_secret", "password", "authorization"}


def _mascarar_endpoint(endpoint: str) -> str:
    """Mascara qualquer ID numérico de usuário dentro da URL, antes de logar."""
    return re.sub(r"(/users/)\d+", r"\1***", endpoint)


class ErroAPI(Exception):
    """Erro genérico após esgotar tentativas ou erro não recuperável."""
    pass


class ErroAutenticacaoAPI(Exception):
    """401 mesmo com token considerado válido. Caso grave e distinto — não tenta de novo sozinho."""
    pass


def _configurar_logger(pasta_logs: Path):
    pasta_logs = Path(pasta_logs)
    pasta_logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"cliente_api.{pasta_logs}")
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        handler_arquivo = logging.FileHandler(
            pasta_logs / "api.log", encoding="utf-8")
        handler_arquivo.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))

        handler_console = RichHandler(rich_tracebacks=True, show_path=False)

        logger.addHandler(handler_arquivo)
        logger.addHandler(handler_console)
    return logger


def _log_seguro(logger, mensagem: str, dados: dict = None):
    if dados:
        dados_limpos = {k: ("***" if k.lower() in DADOS_SENSIVEIS else v)
                        for k, v in dados.items()}
        logger.info(f"{mensagem} | {dados_limpos}")
    else:
        logger.info(mensagem)


def _calcular_espera_backoff(tentativa: int, resposta) -> float:
    """Usa Retry-After se a API informar; senão backoff exponencial + jitter, com teto de 30s."""
    retry_after = resposta.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after) + MARGEM_RETRY_AFTER_SEGUNDOS
        except ValueError:
            pass

    espera_calculada = (2 ** tentativa) + random.uniform(0, 1)
    return min(espera_calculada, TETO_ESPERA_SEGUNDOS)


def chamar_api(metodo: str, endpoint: str, pasta_logs, conta: str, params: dict = None, json_body: dict = None, max_tentativas: int = 5):
    """
    Ponto único de chamada à API do ML.

    metodo: "GET", "POST", etc.
    endpoint: caminho relativo, ex: "/items" (BASE_URL adicionado automaticamente)
    pasta_logs: Path da pasta de logs do app que está chamando (ex: APP_performance/logs)
    """
    logger = _configurar_logger(pasta_logs)
    url = f"{BASE_URL}{endpoint}"

    for tentativa in range(max_tentativas):
        token = obter_token_valido(conta)
        headers = {"Authorization": f"Bearer {token}"}

        _log_seguro(logger, f"Chamando {metodo} {_mascarar_endpoint(endpoint)}", {
                    "params": params, "tentativa": tentativa + 1})

        try:
            resposta = requests.request(
                metodo, url, headers=headers, params=params, json=json_body,
                timeout=(TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS),
            )
        except requests.exceptions.Timeout:
            logger.error(
                f"Timeout em {metodo} {_mascarar_endpoint(endpoint)} (tentativa {tentativa + 1})")
            if tentativa == max_tentativas - 1:
                raise ErroAPI(
                    f"Timeout esgotado após {max_tentativas} tentativas em {_mascarar_endpoint(endpoint)}")
            continue

        if resposta.status_code == 200:
            logger.info(f"OK {metodo} {_mascarar_endpoint(endpoint)} (200)")
            return resposta

        if resposta.status_code == 206:
            logger.warning(
                f"206 (parcial) em {_mascarar_endpoint(endpoint)}. Retentando em {ESPERA_RETRY_206_SEGUNDOS}s...")
            time.sleep(ESPERA_RETRY_206_SEGUNDOS)
            token = obter_token_valido(conta)
            headers = {"Authorization": f"Bearer {token}"}
            resposta_retry = requests.request(
                metodo, url, headers=headers, params=params, json=json_body,
                timeout=(TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS),
            )
            if resposta_retry.status_code == 200:
                logger.info(
                    f"OK na 2ª tentativa após 206 em {_mascarar_endpoint(endpoint)}")
                return resposta_retry
            logger.warning(
                f"Ainda parcial após retry em {_mascarar_endpoint(endpoint)}. Retornando parcial.")
            return resposta_retry

        if resposta.status_code == 401:
            logger.error(
                f"401 em {_mascarar_endpoint(endpoint)} mesmo com token considerado válido.")
            raise ErroAutenticacaoAPI(
                f"API rejeitou o token (401) em {_mascarar_endpoint(endpoint)}, mesmo válido pelo gerenciador_token. "
                f"Possível revogação manual. Resposta: {resposta.text}"
            )

        if resposta.status_code == 429:
            espera = _calcular_espera_backoff(tentativa, resposta)
            logger.warning(
                f"429 em {_mascarar_endpoint(endpoint)}. Aguardando {espera:.1f}s (tentativa {tentativa + 1}/{max_tentativas})")
            time.sleep(espera)
            continue

        logger.error(
            f"Erro {resposta.status_code} em {_mascarar_endpoint(endpoint)}: {resposta.text}")
        raise ErroAPI(
            f"Erro {resposta.status_code} em {_mascarar_endpoint(endpoint)}: {resposta.text}")

    raise ErroAPI(
        f"Número máximo de tentativas ({max_tentativas}) esgotado em {_mascarar_endpoint(endpoint)}")


# ─── CACHE LOCAL ──────────────────────────────────────────

def salvar_cache(chave: str, dados, pasta_cache):
    pasta_cache = Path(pasta_cache)
    pasta_cache.mkdir(parents=True, exist_ok=True)
    caminho = pasta_cache / f"{chave}.json"
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"timestamp": time.time(), "dados": dados},
                  f, ensure_ascii=False, indent=2)


def carregar_cache(chave: str, pasta_cache, max_idade_horas: float = 6):
    pasta_cache = Path(pasta_cache)
    caminho = pasta_cache / f"{chave}.json"
    if not caminho.exists():
        return None
    with open(caminho, "r", encoding="utf-8") as f:
        conteudo = json.load(f)
    idade_horas = (time.time() - conteudo["timestamp"]) / 3600
    if idade_horas > max_idade_horas:
        return None
    return conteudo["dados"]
