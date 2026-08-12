"""
core/auth/gerenciador_token.py

Momento 2 da autenticação: ponto único de entrada para obter um token válido.

Todo app (performance, futuramente pedidos, ads...) deve chamar
SEMPRE obter_token_valido(conta) antes de fazer qualquer requisição à API.
Nenhum app deve ler o .env diretamente nem decidir sozinho se precisa renovar.

`conta` é obrigatório ("MB" ou "SV") — cada conta tem seu próprio
CLIENT_ID/CLIENT_SECRET/ACCESS_TOKEN/REFRESH_TOKEN/USER_ID/TOKEN_CRIADO_EM
no .env, prefixados (ex: MB_ACCESS_TOKEN, SV_ACCESS_TOKEN). Nunca existe
valor "genérico" sem prefixo — decisão consciente, pra nunca haver ambiguidade
de qual conta um token pertence.

Comportamento:
- Token válido (mais de 30min para expirar) -> devolve direto, sem tocar na API
- Token perto de expirar -> tenta renovar (com lock por conta, contra concorrência)
- Lock encontrado com mais de 15s -> considerado órfão, descartado
- Renovação falha de verdade -> levanta erro claro, sem retry automático em loop
"""

import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv, set_key
from rich.console import Console

console = Console()

ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"
PASTA_LOCK = Path(__file__).resolve().parent

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

DURACAO_TOKEN_SEGUNDOS = 21600        # 6 horas
RENOVAR_ANTES_SEGUNDOS = 1800         # 30 minutos de antecedência
ESPERA_LOCK_SEGUNDOS = 3              # quanto esperar entre tentativas de reler o .env
TIMEOUT_ESPERA_LOCK_SEGUNDOS = 60     # tempo máximo esperando outro processo renovar
LOCK_MAX_IDADE_SEGUNDOS = 15          # acima disso, lock é considerado órfão


class FalhaAutenticacao(Exception):
    """Erro claro quando a renovação falha de verdade (refresh_token inválido/revogado)."""
    pass


def mascarar(valor, visiveis=4):
    if not valor or len(valor) <= visiveis:
        return "****"
    return "*" * (len(valor) - visiveis) + valor[-visiveis:]


def _caminho_lock(conta: str) -> Path:
    """1 arquivo de lock por conta — renovar MB nunca deve travar a renovação da SV."""
    return PASTA_LOCK / f".token_{conta}.lock"


def _ler_estado_env(conta: str):
    """Lê o estado atual do .env pra uma conta específica, sempre na hora (nunca cacheado em memória)."""
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    return {
        "client_id": os.getenv(f"{conta}_CLIENT_ID"),
        "client_secret": os.getenv(f"{conta}_CLIENT_SECRET"),
        "access_token": os.getenv(f"{conta}_ACCESS_TOKEN"),
        "refresh_token": os.getenv(f"{conta}_REFRESH_TOKEN"),
        "token_criado_em": int(os.getenv(f"{conta}_TOKEN_CRIADO_EM", 0)),
    }


def _token_ainda_valido(estado):
    """Verifica se falta mais de 30min para o token expirar."""
    if not estado["access_token"] or not estado["token_criado_em"]:
        return False

    agora = int(time.time())
    expira_em = estado["token_criado_em"] + DURACAO_TOKEN_SEGUNDOS
    segundos_restantes = expira_em - agora

    return segundos_restantes > RENOVAR_ANTES_SEGUNDOS


def _renovar_token(estado, conta: str):
    """Chama a API do ML para trocar o refresh_token atual (da conta) por um par novo."""
    payload = {
        "grant_type": "refresh_token",
        "client_id": estado["client_id"],
        "client_secret": estado["client_secret"],
        "refresh_token": estado["refresh_token"],
    }

    resposta = requests.post(TOKEN_URL, data=payload, timeout=30)

    if resposta.status_code != 200:
        raise FalhaAutenticacao(
            f"[FALHA AUTENTICAÇÃO] Renovação da conta {conta} rejeitada pelo ML "
            f"(status {resposta.status_code}). Provável refresh_token "
            f"revogado/expirado. É necessário rodar autorizacao_inicial.py "
            f"novamente para a conta {conta}. Resposta: {resposta.text}"
        )

    return resposta.json()


def _salvar_token_atomico(dados_novos, conta: str):
    """
    Escreve o novo token (da conta) em arquivo temporário primeiro, e só
    substitui o .env real depois que a escrita terminou — evita .env
    corrompido se o processo for interrompido no meio. Nome do temp inclui
    a conta pra MB e SV nunca disputarem o mesmo arquivo temporário se
    renovarem ao mesmo tempo, em processos diferentes.
    """
    caminho_temp = ENV_PATH.parent / f".env.tmp_{conta}"

    caminho_temp.write_text(ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    set_key(str(caminho_temp), f"{conta}_ACCESS_TOKEN", dados_novos["access_token"])
    set_key(str(caminho_temp), f"{conta}_REFRESH_TOKEN", dados_novos["refresh_token"])
    set_key(str(caminho_temp), f"{conta}_TOKEN_CRIADO_EM", str(int(time.time())))

    os.replace(caminho_temp, ENV_PATH)  # substituição atômica garantida pelo SO


def _liberar_lock(lock_path: Path):
    if lock_path.exists():
        lock_path.unlink()


def _tentar_criar_lock(lock_path: Path) -> bool:
    """
    Cria o arquivo de lock (da conta) de forma exclusiva (falha se já existir).
    Se já existir, verifica a idade — se for mais velho que
    LOCK_MAX_IDADE_SEGUNDOS, considera órfão e descarta antes de tentar de novo.
    """
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(int(time.time())).encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        try:
            idade = int(time.time()) - int(lock_path.read_text().strip())
        except (ValueError, FileNotFoundError):
            idade = LOCK_MAX_IDADE_SEGUNDOS + 1  # lock ilegível -> trata como órfão

        if idade > LOCK_MAX_IDADE_SEGUNDOS:
            console.print(f"[bold red][AUTH][/bold red] Lock órfão detectado (idade {idade}s). Descartando.")
            _liberar_lock(lock_path)
            return _tentar_criar_lock(lock_path)

        return False


def obter_token_valido(conta: str) -> str:
    """
    Ponto único de entrada. Qualquer app chama esta função antes de
    fazer uma requisição à API do ML, informando `conta` ("MB" ou "SV"),
    e recebe um access_token garantidamente válido daquela conta.
    """
    estado = _ler_estado_env(conta)

    if _token_ainda_valido(estado):
        return estado["access_token"]

    lock_path = _caminho_lock(conta)

    # Token perto de expirar ou expirado -> precisa renovar
    if _tentar_criar_lock(lock_path):
        try:
            console.print(f"[bold yellow][AUTH][/bold yellow] Token da conta {conta} expirando. Renovando...")
            dados_novos = _renovar_token(estado, conta)
            _salvar_token_atomico(dados_novos, conta)
            console.print(f"[bold green][AUTH][/bold green] Token da conta {conta} renovado: {mascarar(dados_novos['access_token'])}")
            return dados_novos["access_token"]
        finally:
            _liberar_lock(lock_path)
    else:
        # Outro processo já está renovando essa mesma conta -> espera e relê o .env
        console.print(f"[bold yellow][AUTH][/bold yellow] Outro processo já está renovando a conta {conta}. Aguardando...")
        tempo_esperado = 0

        while tempo_esperado < TIMEOUT_ESPERA_LOCK_SEGUNDOS:
            time.sleep(ESPERA_LOCK_SEGUNDOS)
            tempo_esperado += ESPERA_LOCK_SEGUNDOS

            estado_atualizado = _ler_estado_env(conta)
            if _token_ainda_valido(estado_atualizado):
                return estado_atualizado["access_token"]

        raise FalhaAutenticacao(
            f"[FALHA AUTENTICAÇÃO] Esperou pela renovação da conta {conta} por outro processo, "
            "mas o tempo limite foi atingido sem sucesso."
        )