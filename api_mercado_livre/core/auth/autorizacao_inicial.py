"""
core/auth/autorizacao_inicial.py

Momento 1 da autenticação: autorização inicial via OAuth2 + PKCE.
Roda manualmente, uma única vez (ou raramente, se o refresh_token expirar/for revogado).

Não deve ser chamado por nenhum app automaticamente.
"""

import os
import secrets
import hashlib
import base64
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv, set_key
from rich.console import Console

console = Console()

# Caminho do .env na raiz do projeto (3 níveis acima deste arquivo)
ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"

AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


def gerar_pkce():
    """Gera o par code_verifier / code_challenge exigido pelo PKCE."""
    code_verifier = secrets.token_urlsafe(64)[:128]

    sha256_hash = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(sha256_hash).decode("utf-8").rstrip("=")

    return code_verifier, code_challenge


def montar_url_autorizacao(client_id, redirect_uri, code_challenge):
    """Monta a URL que o usuário deve abrir no navegador para autorizar o app."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def extrair_code_da_url(url_colada):
    """
    Extrai o parâmetro 'code' da URL completa que o navegador mostra
    após o redirecionamento (ex: https://localhost:8080/callback?code=XXXX).
    Aceita também o usuário colando só o código puro, sem URL.
    """
    if "code=" not in url_colada:
        # Usuário colou só o código, sem a URL completa
        return url_colada.strip()

    query = urlparse(url_colada).query
    params = parse_qs(query)
    return params["code"][0]


def trocar_code_por_token(client_id, client_secret, redirect_uri, code, code_verifier):
    """Troca o 'code' de autorização pelo access_token + refresh_token."""
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    resposta = requests.post(TOKEN_URL, data=payload, timeout=30)
    resposta.raise_for_status()
    return resposta.json()


def salvar_tokens_no_env(dados_token):
    """
    Salva access_token, refresh_token, user_id e o timestamp de criação no .env.
    Usa set_key (python-dotenv), que atualiza só as chaves informadas,
    sem apagar o restante do arquivo.
    """
    set_key(str(ENV_PATH), "ACCESS_TOKEN", dados_token["access_token"])
    set_key(str(ENV_PATH), "REFRESH_TOKEN", dados_token["refresh_token"])
    set_key(str(ENV_PATH), "USER_ID", str(dados_token["user_id"]))
    set_key(str(ENV_PATH), "TOKEN_CRIADO_EM", str(int(time.time())))


def mascarar(valor, visiveis=4):
    """Mostra só os últimos N caracteres de um valor sensível, para log seguro."""
    if not valor or len(valor) <= visiveis:
        return "****"
    return "*" * (len(valor) - visiveis) + valor[-visiveis:]


def main():
    load_dotenv(dotenv_path=ENV_PATH)

    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    redirect_uri = os.getenv("REDIRECT_URI")

    if not all([client_id, client_secret, redirect_uri]):
        console.print("[bold red][ERRO][/bold red] CLIENT_ID, CLIENT_SECRET ou REDIRECT_URI faltando no .env.")
        return

    code_verifier, code_challenge = gerar_pkce()
    url_autorizacao = montar_url_autorizacao(client_id, redirect_uri, code_challenge)

    console.print("\n[bold cyan][PASSO 1][/bold cyan] Abrindo o navegador para autorização...")
    console.print(f"Se não abrir automaticamente, acesse:\n[underline]{url_autorizacao}[/underline]\n")
    webbrowser.open(url_autorizacao)

    console.print("[bold cyan][PASSO 2][/bold cyan] Após autorizar, copie a URL completa para a qual você foi redirecionado.")
    url_colada = input("Cole aqui: ").strip()

    code = extrair_code_da_url(url_colada)
    console.print(f"[bold green][OK][/bold green] Code extraído: {mascarar(code)}")

    console.print("\n[bold cyan][PASSO 3][/bold cyan] Trocando code por token...")
    dados_token = trocar_code_por_token(
        client_id, client_secret, redirect_uri, code, code_verifier
    )

    console.print(f"[bold green][OK][/bold green] access_token recebido: {mascarar(dados_token['access_token'])}")
    console.print(f"[bold green][OK][/bold green] refresh_token recebido: {mascarar(dados_token['refresh_token'])}")

    salvar_tokens_no_env(dados_token)
    console.print(f"\n[bold green][OK][/bold green] Tokens salvos em {ENV_PATH}")


if __name__ == "__main__":
    main()