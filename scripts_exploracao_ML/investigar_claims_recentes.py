# scripts_exploracao_ML/investigar_claims_recentes.py
#
# Objetivo ÚNICO: buscar as reclamações/devoluções mais recentes envolvendo
# você como vendedor, via GET /post-purchase/v1/claims/search, pra achar um
# numero_pedido real com devolução de verdade pra usar como objeto de teste
# do autocomplete do Sistema de Devoluções. NENHUM outro endpoint é chamado
# além deste (e do /users/me, só pra descobrir o seu próprio ID de vendedor,
# que é parâmetro obrigatório da busca — sem ele a API recusa com 400).
#
# Não chama /orders, /shipments, /post-purchase/v2/claims/$ID/returns nem
# nenhum outro recurso — isso fica pra depois, com o numero_pedido em mãos.
#
# O arquivo de saída guarda só os campos essenciais de cada claim (id,
# resource_id, type, stage, status, reason_id, date_created, players
# reduzido a role+user_id, e resolution inteiro) — o resto (available_actions,
# fulfilled, quantity_type, claim_version, site_id, last_updated,
# related_entities...) é real na API mas não ajuda a decidir mediador ou
# applied_coverage, só infla o arquivo sem necessidade.
#
# Só leitura. Não toca no banco. Sobrescreve o arquivo de saída (nunca
# acrescenta) a cada execução.

import json
import sys
from pathlib import Path

# Permite rodar este script direto (python scripts_exploracao_ML/investigar_claims_recentes.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"    # "MB" (Magazine) ou "SV" (Samvale) — troque pra investigar a outra conta
LIMITE = 20     # quantas reclamações/devoluções mais recentes trazer
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_claims_recentes_{CONTA}.json"


def filtrar_campos_essenciais_do_claim(claim_bruto):
    # Descarta o que só serve pra decidir uma ação de UI (available_actions,
    # due_date por ação) ou pra rastrear o recurso por dentro (fulfilled,
    # quantity_type, claim_version, site_id, related_entities) — nada disso
    # ajuda a decidir se o claim teve mediador ou qual cobertura foi aplicada.
    players_essenciais = [
        {"role": player.get("role"), "user_id": player.get("user_id")}
        for player in claim_bruto.get("players", [])
    ]
    return {
        "id": claim_bruto.get("id"),
        "resource_id": claim_bruto.get("resource_id"),
        "type": claim_bruto.get("type"),
        "stage": claim_bruto.get("stage"),
        "status": claim_bruto.get("status"),
        "reason_id": claim_bruto.get("reason_id"),
        "date_created": claim_bruto.get("date_created"),
        "players": players_essenciais,
        "resolution": claim_bruto.get("resolution"),
    }


try:
    # Passo 1 (pré-requisito, não é exploração de outro endpoint): descobrir
    # o próprio user_id do vendedor — a busca de claims exige players.user_id
    # como filtro obrigatório, e sem acesso ao site do ML não tem como pegar
    # esse número de outro jeito.
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="investigar_claims_recentes",
    )
    user_id = resposta_me.json()["id"]
    print(f"Conta {CONTA} — user_id descoberto: {user_id}")

    # Passo 2 (o único que interessa de verdade): buscar as reclamações mais
    # recentes em que esse user_id aparece como respondent (o vendedor).
    # Sem filtro de type de propósito — a própria doc do ML mostrou o valor
    # inconsistente entre "return" e "returns" em páginas diferentes, então
    # é mais seguro trazer tudo recente e olhar o campo "type" na mão do que
    # arriscar um filtro que descarta silenciosamente o que procuramos.
    resposta_claims = chamar_api(
        "GET", "/post-purchase/v1/claims/search",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={
            "players.user_id": user_id,
            "players.role": "respondent",
            "status": "closed",  # "opened" pra ver as pendentes/ao vivo em vez das já resolvidas
            "sort": "date_created:desc",
            "limit": LIMITE,
        },
        nome_log="investigar_claims_recentes",
    )
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"Erro ao chamar a API: {erro}")
else:
    resultado_cru = resposta_claims.json()  # cru só em memória — o que vai pro arquivo é o filtrado abaixo

    claims_filtrados = [
        filtrar_campos_essenciais_do_claim(claim)
        for claim in resultado_cru.get("data", [])
    ]
    resultado_reduzido = {
        "paging": resultado_cru.get("paging"),  # total real de claims que existem, além do LIMITE trazido
        "data": claims_filtrados,
    }

    # Oculta SÓ o seu próprio user_id (o do vendedor) antes de salvar — o
    # único dado que você pediu pra não ficar me passando. Faz isso em cima
    # do texto já serializado, pra pegar o ID em qualquer posição do JSON
    # (ex: dentro de "players[].user_id"), sem precisar mapear campo por
    # campo. Não mascara o id do comprador (complainant) nem mais nada.
    texto_json = json.dumps(resultado_reduzido, ensure_ascii=False, indent=2)
    texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:  # "w" sobrescreve — zera o arquivo a cada execução
        f.write(texto_json_oculto)

    print(f"Retorno reduzido ({len(claims_filtrados)} reclamação(ões), só campos essenciais, "
          f"user_id oculto) salvo em: {CAMINHO_SAIDA}")
    print("Suba esse arquivo na conversa pra eu analisar.")