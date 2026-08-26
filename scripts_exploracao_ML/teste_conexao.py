"""
teste_conexao.py — Teste de conexão com a API do Mercado Livre, via o
gerenciador_token.py oficial (já com suporte a múltiplas contas). Não
modifica nenhum outro arquivo do projeto — só lê e, se precisar, renova
o token daquela conta.
"""

import sys
from pathlib import Path

import requests

# Permite rodar este script direto (python scripts_exploracao_ML/teste_conexao.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.auth.gerenciador_token import FalhaAutenticacao, obter_token_valido

CONTA = "MB"  # troque para "SV" para testar a outra
# CONTA = "SV"  # troque para "MB" para testar a outra


try:
    access_token = obter_token_valido(CONTA)
except FalhaAutenticacao as erro:
    print(erro)
else:
    resposta = requests.get(
        "https://api.mercadolibre.com/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    print(f"Conta testada: {CONTA}")
    print(f"HTTP: {resposta.status_code}")
    print(resposta.json())