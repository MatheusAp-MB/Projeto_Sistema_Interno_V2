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
- Renovação falha de verdade (ML recusou o refresh_token: 400/401...) -> levanta erro claro, sem retry
- Renovação falha por instabilidade do ML ou da rede (5xx, 408, 429, timeout) -> retry LIMITADO
  (nunca em loop), com espera crescente e a hora do lock renovada durante a espera; se todas as
  tentativas falharem, levanta FalhaAutenticacaoTemporaria (NÃO significa refresh_token inválido)
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

# Retry da renovação quando o ML está instável (5xx, 408, 429, timeout, erro de rede).
# Cada número é a espera, em segundos, ANTES da tentativa seguinte; a quantidade de números
# + 1 = total de tentativas. (10, 20) -> 3 tentativas e 30 s de espera no pior caso, abaixo
# dos 60 s que um processo que está só aguardando (TIMEOUT_ESPERA_LOCK_SEGUNDOS) tolera.
# Origem (12/10/2026): um 503 do ML na renovação do token da MB derrubou a tela com a mensagem
# "refresh_token revogado", que não era a causa.
ESPERAS_ENTRE_TENTATIVAS_RENOVACAO_SEGUNDOS = (10, 20)
STATUS_HTTP_PASSAGEIROS = (408, 429)  # além de qualquer 5xx
PASSO_DO_CARIMBO_DO_LOCK_SEGUNDOS = 5  # de quanto em quanto tempo renovar a hora do lock durante a espera


class FalhaAutenticacao(Exception):
    """Erro claro quando a renovação falha de verdade (refresh_token inválido/revogado)."""
    pass


class FalhaAutenticacaoTemporaria(FalhaAutenticacao):
    """
    A renovação não foi concluída porque o ML (ou a rede) falhou — 5xx, 408, 429,
    timeout. NÃO indica refresh_token inválido: basta tentar de novo mais tarde.
    É subclasse de FalhaAutenticacao para quem já captura o erro continuar funcionando.
    """
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


def _status_e_passageiro(status_code: int) -> bool:
    """5xx, 408 e 429 são falhas do lado do ML ou da rede: vale tentar de novo."""
    return status_code >= 500 or status_code in STATUS_HTTP_PASSAGEIROS


def _renovar_carimbo_do_lock(lock_path: Path):
    """
    Reescreve, dentro do lock, a hora atual. Sem isso, uma renovação que demora (retry com
    espera) passaria dos LOCK_MAX_IDADE_SEGUNDOS, outro processo trataria o lock como órfão e
    renovaria ao mesmo tempo — e o refresh_token do ML só vale uma vez.
    Escrita atômica (arquivo temporário + replace) para ninguém ler o lock pela metade.
    Se falhar, segue sem erro: no pior caso o carimbo fica um passo mais velho.
    """
    if not lock_path.exists():
        return  # sem lock nosso, não cria um

    try:
        temporario = lock_path.with_name(lock_path.stem + "_novo.lock")
        temporario.write_text(str(int(time.time())), encoding="utf-8")
        os.replace(temporario, lock_path)
    except OSError:
        pass


def _esperar_mantendo_o_lock(segundos: int, lock_path: Path):
    """Espera `segundos` em passos curtos, renovando a hora do lock a cada passo."""
    restante = segundos
    while restante > 0:
        passo = min(PASSO_DO_CARIMBO_DO_LOCK_SEGUNDOS, restante)
        time.sleep(passo)
        restante -= passo
        _renovar_carimbo_do_lock(lock_path)


def _renovar_token(estado, conta: str):
    """
    Chama a API do ML para trocar o refresh_token atual (da conta) por um par novo.

    - 200 -> devolve o par novo.
    - 5xx, 408, 429, timeout ou erro de rede (ML/rede instável) -> tenta de novo, com as
      esperas de ESPERAS_ENTRE_TENTATIVAS_RENOVACAO_SEGUNDOS; se todas falharem, levanta
      FalhaAutenticacaoTemporaria.
    - Qualquer outra resposta (400 invalid_grant, 401...) -> FalhaAutenticacao na hora, sem
      retry: o ML recusou o refresh_token.

    O mesmo refresh_token é reenviado em cada tentativa. O par novo só é gravado no .env por
    quem chama (obter_token_valido), depois de um 200 — então uma falha aqui nunca altera o .env.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": estado["client_id"],
        "client_secret": estado["client_secret"],
        "refresh_token": estado["refresh_token"],
    }

    lock_path = _caminho_lock(conta)
    total_de_tentativas = len(ESPERAS_ENTRE_TENTATIVAS_RENOVACAO_SEGUNDOS) + 1
    ultima_falha = ""  # vazio = nenhuma falha passageira até agora

    for numero in range(1, total_de_tentativas + 1):
        _renovar_carimbo_do_lock(lock_path)

        try:
            resposta = requests.post(TOKEN_URL, data=payload, timeout=30)
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ) as erro:
            ultima_falha = f"erro de conexão ({type(erro).__name__})"
        else:
            if resposta.status_code == 200:
                return resposta.json()

            if not _status_e_passageiro(resposta.status_code):
                nota_de_falha_anterior = ""
                if ultima_falha:
                    nota_de_falha_anterior = (
                        f" Observação: antes desta resposta houve uma falha passageira "
                        f"({ultima_falha}) nesta mesma renovação; é possível que o ML tenha "
                        f"processado a tentativa anterior e a resposta tenha se perdido "
                        f"(o refresh_token do ML só vale uma vez)."
                    )
                raise FalhaAutenticacao(
                    f"[FALHA AUTENTICAÇÃO] Renovação da conta {conta} rejeitada pelo ML "
                    f"(status {resposta.status_code}). Provável refresh_token "
                    f"revogado/expirado. É necessário rodar autorizacao_inicial.py "
                    f"novamente para a conta {conta}. Resposta: {resposta.text}"
                    f"{nota_de_falha_anterior}"
                )

            ultima_falha = f"status {resposta.status_code}"

        if numero < total_de_tentativas:
            espera = ESPERAS_ENTRE_TENTATIVAS_RENOVACAO_SEGUNDOS[numero - 1]
            console.print(
                f"[bold yellow][AUTH][/bold yellow] Renovação da conta {conta} falhou "
                f"({ultima_falha}). Nova tentativa em {espera}s "
                f"(tentativa {numero + 1} de {total_de_tentativas})..."
            )
            _esperar_mantendo_o_lock(espera, lock_path)

    raise FalhaAutenticacaoTemporaria(
        f"[FALHA AUTENTICAÇÃO TEMPORÁRIA] O ML não concluiu a renovação do token da conta "
        f"{conta} em {total_de_tentativas} tentativas (última falha: {ultima_falha}). "
        f"Isso NÃO indica refresh_token inválido: é instabilidade do ML ou da rede. "
        f"Tente novamente em alguns minutos. NÃO rode autorizacao_inicial.py por causa "
        f"deste erro (o .env não foi alterado)."
    )


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