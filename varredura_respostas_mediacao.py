"""
Rascunho rápido — varredura de "quem respondeu e quando" numa reclamação/mediação.

O QUE FAZ:
  Pega o claim_id de uma reclamação, busca GET /claims/{claim_id}/messages
  e classifica cada mensagem em 3 baldes, na ordem em que aconteceram:
    - "O ML RESPONDEU"        -> sender_role == "mediator"
    - "VOCE RESPONDEU"        -> sender_role == o papel que bate com o SEU user_id
    - "A CONTRAPARTE RESPONDEU" -> qualquer outro (comprador ou vendedor, o que não for você)

  Não lê o conteúdo da mensagem (campo "message") — só sender_role + data.
  Pensado pra virar o "botão de varredura" que você comentou, não pra rodar sozinho
  agendado (webhook fica de fora por decisão sua).

NÃO TESTADO AINDA — é rascunho. Rode você, na sua máquina, e cola o resultado
(ou o erro) de volta que eu ajusto.

COMO USAR:
  python varredura_respostas_mediacao.py --claim_id=5564889989 --token=SEU_ACCESS_TOKEN

  Ou, se preferir não colar o token na linha de comando (fica no histórico do
  shell), exporta antes:
    set ML_ACCESS_TOKEN=SEU_ACCESS_TOKEN        (Windows/cmd)
    $env:ML_ACCESS_TOKEN="SEU_ACCESS_TOKEN"     (PowerShell)
  e roda só:
    python varredura_respostas_mediacao.py --claim_id=5564889989

PENDENTE (de propósito, pra não estourar o tempo agora):
  - Esse script pega o token direto (env var ou --token), sem usar a renovação
    automática que o consultar_linha_tempo_devolucao.py já tem (aquele
    "[AUTH] Token da conta SV expirando. Renovando..."). Não sei o nome exato
    da função/módulo de vocês pra isso, então não arrisquei importar errado.
    Se quiser, dá pra plugar depois — é só trocar a função obter_token() daqui
    pela de vocês.
  - Não resolve --candidato= (número do pedido) pra claim_id sozinho ainda —
    passa o claim_id direto (você já tem ele no output do outro script, ou no
    JSON de claims.search).
"""

import argparse
import os
import sys
import time
from datetime import datetime

import requests

BASE_URL = "https://api.mercadolibre.com"


def obter_token(args):
    """Placeholder simples: --token= na linha de comando, ou variável de ambiente ML_ACCESS_TOKEN."""
    if args.token:
        return args.token
    token = os.environ.get("ML_ACCESS_TOKEN")
    if not token:
        print("Faltou o token. Use --token=... ou exporte ML_ACCESS_TOKEN antes de rodar.")
        sys.exit(1)
    return token


def chamar_api(url, token, tentativas=5):
    """GET com retry simples em 429, igual ao padrão que já vimos nos scripts de vocês."""
    headers = {"Authorization": f"Bearer {token}"}
    espera = 1.0
    for tentativa in range(1, tentativas + 1):
        resposta = requests.get(url, headers=headers)
        if resposta.status_code == 429:
            print(f"  [429] Aguardando {espera:.1f}s (tentativa {tentativa}/{tentativas})")
            time.sleep(espera)
            espera *= 1.7
            continue
        resposta.raise_for_status()
        return resposta.json()
    resposta.raise_for_status()


def formatar_data(data_iso):
    """'2026-08-24T16:02:00.000-04:00' -> '24/08/2026 16:02'"""
    if not data_iso:
        return "—"
    # remove o timezone offset pra parsear só a parte de data/hora local do próprio campo
    base = data_iso.split(".")[0].split("-04:00")[0].split("-03:00")[0]
    try:
        dt = datetime.fromisoformat(base)
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return data_iso


def descobrir_meu_papel(claim_id, token, meu_user_id):
    """Olha claims/{id}, acha qual papel (complainant/respondent) bate com o seu user_id.
    Importante por causa do achado de cancel_sale: o vendedor nem sempre é 'respondent'."""
    claim = chamar_api(f"{BASE_URL}/post-purchase/v1/claims/{claim_id}", token)
    for player in claim.get("players", []):
        if player.get("user_id") == meu_user_id:
            return player.get("role")
    return None


def main():
    parser = argparse.ArgumentParser(description="Varredura de respostas (ML x você) numa reclamação")
    parser.add_argument("--claim_id", required=True, help="ID da reclamação (ex: 5564889989)")
    parser.add_argument("--token", required=False, help="Access token (senão lê ML_ACCESS_TOKEN do ambiente)")
    args = parser.parse_args()

    token = obter_token(args)
    claim_id = args.claim_id

    print(f"Reclamação {claim_id}")

    # 1) descobrir quem sou eu nessa reclamação (complainant ou respondent)
    me = chamar_api(f"{BASE_URL}/users/me", token)
    meu_user_id = me.get("id")
    meu_papel = descobrir_meu_papel(claim_id, token, meu_user_id)
    if meu_papel is None:
        print("  [aviso] Não achei seu user_id nos players dessa reclamação — "
              "vou marcar tudo que não for 'mediator' como 'contraparte'.")
    else:
        print(f"  Seu papel nessa reclamação: {meu_papel}")

    # 2) buscar as mensagens
    mensagens = chamar_api(f"{BASE_URL}/post-purchase/v1/claims/{claim_id}/messages", token)
    if not mensagens:
        print("  Nenhuma mensagem encontrada.")
        return

    # ordena da mais antiga pra mais nova
    mensagens.sort(key=lambda m: m.get("date_created") or "")

    print()
    for m in mensagens:
        sender = m.get("sender_role")
        data = formatar_data(m.get("date_created"))
        status = m.get("status")

        if sender == "mediator":
            rotulo = "O ML RESPONDEU"
        elif meu_papel is not None and sender == meu_papel:
            rotulo = "VOCÊ RESPONDEU"
        else:
            rotulo = "A CONTRAPARTE RESPONDEU"

        aviso_status = "" if status == "available" else f"  [status: {status}]"
        print(f"  {rotulo} em {data}{aviso_status}")

    print()
    print("Fim.")


if __name__ == "__main__":
    main()