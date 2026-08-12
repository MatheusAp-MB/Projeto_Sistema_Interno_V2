"""
teste_conexao.py — Teste isolado de conexão, sem depender do
gerenciador_token.py (que ainda não suporta múltiplas contas).
Não modifica nenhum arquivo existente do projeto.
"""

import os
from dotenv import load_dotenv
import requests

load_dotenv()

CONTA = "MB"  # troque para "SV" para testar a outra

access_token = os.getenv(f"{CONTA}_ACCESS_TOKEN")

if not access_token:
    print(f"{CONTA}_ACCESS_TOKEN não encontrado no .env — confirme se a migração de pasta trouxe o .env junto.")
else:
    resposta = requests.get(
        "https://api.mercadolibre.com/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    print(f"Conta testada: {CONTA}")
    print(f"HTTP: {resposta.status_code}")
    print(resposta.json())