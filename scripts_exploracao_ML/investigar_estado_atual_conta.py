# scripts_exploracao_ML/investigar_estado_atual_conta.py
#
# Objetivo: capturar o estado ATUAL de reputação/status da conta (MB, a
# mesma usada em todos os testes de discount.type=fs_optional), pra comparar
# manualmente com o que ficou salvo no JSON do teste histórico
# (investigacao_reputacao_seller_status_abaixo_79.json, bloco "contexto")
# -- não como parâmetro de request (isso já foi testado e confirmado "sem
# efeito nenhum"), mas como o valor REAL da conta hoje.
#
# Motivação: replicação literal dos parâmetros exatos que geraram
# fs_optional da última vez (mesmo item, mesma caixa sintética 5x5x5/8500g,
# mesmo Chinelo 13x28x39/601g, mesmos 3 preços, os 2 valores de
# free_shipping) voltou 0/12 -- sempre "mandatory". Como não sobrou nenhuma
# variável de REQUEST ainda não testada, a hipótese que falta descartar é
# que algo mudou fora do request: o estado real da conta (reputação,
# power_seller_status, vínculo com Loja Oficial) entre a observação
# original e hoje.
#
# Só leitura -- não toca no banco, não grava nada além do arquivo de saída.

import argparse
import json
import sys
from pathlib import Path

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

parser = argparse.ArgumentParser(description="Estado atual de reputação/status da conta no ML.")
parser.add_argument("--conta", default="MB", choices=["MB", "SV"])
args = parser.parse_args()

CONTA = args.conta
PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / "investigacao_estado_atual_conta.json"

resultado = {"conta": CONTA}

try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_estado_atual_conta",
    )
    user_id = resposta_me.json()["id"]
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao autenticar / obter user_id: {erro}")
    sys.exit(1)

try:
    resposta_user = chamar_api(
        "GET", f"/users/{user_id}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_estado_atual_conta",
    )
    seller_reputation = resposta_user.json().get("seller_reputation", {})
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao buscar seller_reputation: {erro}")
    sys.exit(1)

info_loja_oficial = None
vinculado_loja_oficial = None
try:
    resposta_brands = chamar_api(
        "GET", f"/users/{user_id}/brands",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_estado_atual_conta",
    )
    info_loja_oficial = resposta_brands.json()
    vinculado_loja_oficial = True
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    if "Erro 404" in str(erro):
        vinculado_loja_oficial = False
    else:
        print(f"Erro inesperado ao checar /brands (não é o 404 esperado): {erro}")

resultado["level_id_bruto"] = seller_reputation.get("level_id")
resultado["power_seller_status_bruto"] = seller_reputation.get("power_seller_status")
resultado["vinculado_loja_oficial_hoje"] = vinculado_loja_oficial
resultado["info_loja_oficial"] = info_loja_oficial
resultado["reputation_metrics"] = seller_reputation.get("metrics")
resultado["reputation_transactions"] = seller_reputation.get("transactions")

texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    f.write(texto_json_oculto)

print(f"\nEstado ATUAL da conta {CONTA}:")
print(f"  level_id: {resultado['level_id_bruto']}")
print(f"  power_seller_status: {resultado['power_seller_status_bruto']}")
print(f"  vinculado a Loja Oficial hoje: {vinculado_loja_oficial}")
print(f"\nCompare esses 3 valores com o bloco 'contexto' salvo em "
      f"investigacao_reputacao_seller_status_abaixo_79.json (se você ainda tiver esse arquivo) -- "
      f"'level_id_bruto', 'power_seller_status_bruto' e 'loja_oficial' de quando fs_optional foi visto.")
print(f"\nRetorno completo salvo em: {CAMINHO_SAIDA}")