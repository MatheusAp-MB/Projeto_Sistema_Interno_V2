"""
core/estrutura_api/cliente_api.py

Camada única de comunicação com a API do Mercado Livre.
Todo app deve chamar a API através de chamar_api(), nunca via requests direto.

Reuso de conexão (29/09/2026): as duas chamadas HTTP daqui embaixo usam uma
requests.Session() persistente, com pool de conexão (HTTPAdapter), em vez da
função solta requests.request() (que abria 1 conexão TCP+TLS nova a cada
chamada, sem keep-alive). Validado isoladamente antes de aplicar aqui — ver
Checkpoint - Investigação da Comissão Real de Venda via API do Mercado Livre,
seção 15: com pool, o mesmo throughput por thread chegou a 8,1x maior (19,1 →
154,7 req/s em 50 threads, sem saturar) e o CPU sustentado caiu de ~98-100%
pra pico de 62% — o teto de paralelismo encontrado em várias frentes (frete,
comissão) era autoimposto por essa falta de reuso, não limite da API do ML.
Mudança transversal: TODO domínio que passa por chamar_api() (frete, mlbs,
detalhes, sku completo, comissão real, categorias) se beneficia, sem precisar
de nenhuma mudança do lado de quem chama. requests.Session é seguro pra uso
concorrente entre threads (o pool de conexão do urllib3 por trás dela já
cuida do próprio lock) — por isso 1 Session módulo-level, reaproveitada por
todo mundo, é suficiente (não precisa de 1 por thread nem de trava manual).
"""

import re
import time
import json
import logging
from pathlib import Path
from rich.logging import RichHandler

import requests
from requests.adapters import HTTPAdapter

from api_mercado_livre.core.auth.gerenciador_token import obter_token_valido
from api_mercado_livre.core.estrutura_api.excecoes import ErroAPI, ErroAutenticacaoAPI
from api_mercado_livre.core.estrutura_api.protecao import calcular_espera_backoff

BASE_URL = "https://api.mercadolibre.com"

TIMEOUT_CONEXAO_SEGUNDOS = 10
TIMEOUT_LEITURA_SEGUNDOS = 30
ESPERA_RETRY_206_SEGUNDOS = 2

# * [EXPLICAÇÃO] → tamanho validado em scripts_exploracao_ML/teste_paralelismo_listing_prices.py
#                  --pool: 50 threads simultâneas, throughput ainda subindo (não saturou nesse
#                  nível) — 50 é o maior valor testado com dado real, não um teto conhecido. Se
#                  algum domínio futuro precisar de mais threads simultâneas que isso, vale
#                  revalidar/aumentar com o mesmo rigor (nunca só chutar um número maior).
TAMANHO_POOL_CONEXOES = 50

DADOS_SENSIVEIS = {"access_token", "refresh_token",
                   "client_secret", "password", "authorization"}

# Sessão persistente, módulo-level — criada 1 vez, reaproveitada por toda chamada de
# chamar_api() daqui em diante (retry continua 100% em chamar_api(), por isso max_retries
# fica no default 0 aqui — não duplicar retry em 2 camadas).
_sessao = requests.Session()
_sessao.mount("https://", HTTPAdapter(pool_connections=10, pool_maxsize=TAMANHO_POOL_CONEXOES))


def _mascarar_endpoint(endpoint: str) -> str:
    """Mascara qualquer ID numérico de usuário dentro da URL, antes de logar."""
    return re.sub(r"(/users/)\d+", r"\1***", endpoint)


def _configurar_logger(pasta_logs: Path, nome_log: str = "api"):
    pasta_logs = Path(pasta_logs)
    pasta_logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"cliente_api.{pasta_logs}.{nome_log}")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False  # não deixa vazar pro logger raiz do Django (settings.py LOGGING)

        # Arquivo recebe tudo (INFO) — histórico completo de cada chamada,
        # útil pra depurar depois. Console só mostra WARNING+ (429, timeout,
        # erro real) — silêncio em requisição OK, que colidia com o redraw
        # ao vivo da barra de progresso (rich.Progress) e criava a enxurrada
        # de texto repetido.
        handler_arquivo = logging.FileHandler(
            pasta_logs / f"{nome_log}.log", encoding="utf-8")
        handler_arquivo.setLevel(logging.INFO)
        handler_arquivo.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))

        handler_console = RichHandler(rich_tracebacks=True, show_path=False)
        handler_console.setLevel(logging.WARNING)

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


def chamar_api(metodo: str, endpoint: str, pasta_logs, conta: str, params: dict = None, json_body: dict = None, max_tentativas: int = 5, nome_log: str = "api", headers_extra: dict = None):
    """
    Ponto único de chamada à API do ML.

    metodo: "GET", "POST", etc.
    endpoint: caminho relativo, ex: "/items" (BASE_URL adicionado automaticamente)
    pasta_logs: Path da pasta de logs do app que está chamando (ex: integracao_mercado_livre/logs/<Empresa>)
    nome_log: nome do arquivo de log, sem ".log" — pra scripts diferentes que compartilham a mesma
              pasta_logs não sobrescreverem o log um do outro. Default "api" preserva o comportamento
              anterior, pra qualquer chamador que não especificar.
    headers_extra: headers adicionais além do Authorization (ex: {"x-format-new": "true"},
                   exigido por /shipments desde 12/10/2025; {"X-Api-Version": "2"}, exigido por
                   certos recursos de /orders). Opcional, default None preserva 100% do
                   comportamento anterior pra quem não especificar.
    """
    logger = _configurar_logger(pasta_logs, nome_log)
    url = f"{BASE_URL}{endpoint}"

    for tentativa in range(max_tentativas):
        token = obter_token_valido(conta)
        headers = {"Authorization": f"Bearer {token}"}
        if headers_extra:
            headers.update(headers_extra)

        _log_seguro(logger, f"Chamando {metodo} {_mascarar_endpoint(endpoint)}", {
                    "params": params, "headers_extra": headers_extra, "tentativa": tentativa + 1})

        try:
            resposta = _sessao.request(
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
            if headers_extra:
                headers.update(headers_extra)
            resposta_retry = _sessao.request(
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
            espera = calcular_espera_backoff(tentativa, resposta)
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


class ClienteApiMercadoLivre:
    """Transporte com a conta presa na construção — quem usa não passa
    conta em toda chamada. Não duplica a lógica de chamar_api() (retry,
    backoff, 206, exceções): só fixa 'conta' e delega pra ela, que
    continua sendo o único lugar que sabe fazer a chamada de verdade."""

    def __init__(self, conta: str):
        self._conta = conta

    def chamar(self, metodo: str, endpoint: str, pasta_logs, params: dict = None, json_body: dict = None, max_tentativas: int = 5, nome_log: str = "api", headers_extra: dict = None):
        return chamar_api(
            metodo, endpoint, pasta_logs, self._conta,
            params=params, json_body=json_body, max_tentativas=max_tentativas,
            nome_log=nome_log, headers_extra=headers_extra,
        )


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
