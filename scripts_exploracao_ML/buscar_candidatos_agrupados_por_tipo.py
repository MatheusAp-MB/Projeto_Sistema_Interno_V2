# scripts_exploracao_ML/buscar_candidatos_agrupados_por_tipo.py
#
# Objetivo ÚNICO: descobrir quais "type" de reclamação existem de verdade
# nesta conta e trazer QUANTIDADE_POR_TIPO exemplos de cada um, com
# resolution completo -- em vez de confiar em "os N mais recentes", que na
# prática vem dominado por 1 tipo só (achado real: cancel_purchase, ~40%
# das últimas 20 reclamações) e nunca mostra os tipos mais raros.
#
# Não filtra por "type" na própria chamada à API -- a doc já mostrou esse
# campo inconsistente entre páginas ("return" vs "returns"), então filtrar
# por um valor específico arrisca descartar reclamação de verdade em
# silêncio. Em vez disso, pagina só por status=closed (sem filtro de type),
# olha o "type" que cada reclamação realmente trouxe, e agrupa na mão.
#
# Guarda contra offset+limit >= 10000 (regra documentada da própria API
# pra esse endpoint) parando antes de violar isso, em vez de deixar a API
# recusar sem explicação.
#
# Só leitura. Sobrescreve o arquivo de saída (nunca acrescenta) a cada
# execução.

import json
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"               # "MB" (Magazine) ou "SV" (Samvale)
QUANTIDADE_POR_TIPO = 3    # quantos exemplos guardar de cada "type" encontrado
TAMANHO_PAGINA = 100       # mesmo teto já usado em buscar_reclamacoes_candidatas.py
MAX_PAGINAS = 15           # teto de segurança -- nunca escaneia mais que isso
                           # (15 x 100 = até 1.500 reclamações), mesmo que
                           # algum tipo raro nunca complete a quantidade
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_candidatos_por_tipo_{CONTA}.json"
LIMITE_SEGURO_OFFSET_MAIS_LIMIT = 10000  # regra da própria API: offset+limit tem que ficar abaixo disso

console = Console()


def filtrar_campos_essenciais_do_claim(claim_bruto):
    # Mesmo critério do investigar_claims_recentes.py: descarta o que só
    # serve pra UI (available_actions) ou rastreio interno (fulfilled,
    # quantity_type, claim_version, site_id, related_entities) -- nada
    # disso ajuda a decidir mediador ou applied_coverage.
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


def pagina_nao_acrescentou_nada_novo(pagina, candidatos_por_tipo):
    # Critério de parada antecipada: se a página inteira só trouxe
    # reclamação de tipo que já bateu a quota, escanear mais página tende a
    # só repetir o tipo dominante (achado real: cancel_purchase), sem
    # chance de completar os tipos que ainda faltam.
    for claim in pagina:
        tipo = claim.get("type")
        if len(candidatos_por_tipo.get(tipo, [])) < QUANTIDADE_POR_TIPO:
            return False
    return True


candidatos_por_tipo = {}
pagina_numero = 0
total_disponivel = None

try:
    resposta_me = chamar_api(
        "GET", "/users/me",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="buscar_candidatos_agrupados_por_tipo",
    )
    user_id = resposta_me.json()["id"]
    console.print(f"Conta {CONTA} — user_id descoberto: {user_id}")

    offset = 0
    while pagina_numero < MAX_PAGINAS:
        if offset + TAMANHO_PAGINA >= LIMITE_SEGURO_OFFSET_MAIS_LIMIT:
            console.print(f"  Parando antes de violar offset+limit >= {LIMITE_SEGURO_OFFSET_MAIS_LIMIT} (regra da API).")
            break

        pagina_numero += 1
        with console.status(f"[bold green]Página {pagina_numero} (offset {offset})...[/bold green]", spinner="dots"):
            resposta = chamar_api(
                "GET", "/post-purchase/v1/claims/search",
                pasta_logs=PASTA_LOGS, conta=CONTA,
                params={
                    "players.user_id": user_id,
                    "players.role": "respondent",
                    "status": "closed",
                    "sort": "date_created:desc",
                    "limit": TAMANHO_PAGINA,
                    "offset": offset,
                },
                nome_log="buscar_candidatos_agrupados_por_tipo",
            )
        dados = resposta.json()
        total_disponivel = dados.get("paging", {}).get("total", total_disponivel)
        pagina = dados.get("data", [])

        if not pagina:
            console.print("  Página vazia — não há mais reclamação pra escanear.")
            break

        for claim in pagina:
            tipo = claim.get("type")
            grupo = candidatos_por_tipo.setdefault(tipo, [])
            if len(grupo) < QUANTIDADE_POR_TIPO:
                grupo.append(filtrar_campos_essenciais_do_claim(claim))

        if pagina_nao_acrescentou_nada_novo(pagina, candidatos_por_tipo):
            console.print(f"  Página {pagina_numero} não trouxe nada novo pra nenhum tipo ainda incompleto — parando aqui.")
            break

        offset += len(pagina)

    tabela = Table(title="Candidatos encontrados por tipo", box=box.SIMPLE_HEAD, header_style="bold")
    tabela.add_column("Tipo")
    tabela.add_column("Encontrados")
    for tipo, grupo in sorted(candidatos_por_tipo.items(), key=lambda item: item[0] or ""):
        marca = "" if len(grupo) >= QUANTIDADE_POR_TIPO else "  (incompleto)"
        tabela.add_row(tipo or "(sem tipo)", f"{len(grupo)}/{QUANTIDADE_POR_TIPO}{marca}")
    console.print()
    console.print(tabela)
    console.print(f"\n  {pagina_numero} página(s) escaneada(s), de um total de {total_disponivel} reclamação(ões) fechada(s) na conta.")

except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f"\n[bold red]Erro ao chamar a API:[/bold red] {erro}")
else:
    resultado = {
        "paginas_escaneadas": pagina_numero,
        "total_disponivel_na_conta": total_disponivel,
        "quantidade_por_tipo_pedida": QUANTIDADE_POR_TIPO,
        "candidatos_por_tipo": candidatos_por_tipo,
    }

    texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
    texto_json_oculto = texto_json.replace(str(user_id), "SEU_USER_ID_OCULTO")

    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:  # "w" sobrescreve -- zera o arquivo a cada execução
        f.write(texto_json_oculto)

    console.print(f"\nResultado salvo em: {CAMINHO_SAIDA}")
    console.print("Suba esse arquivo na conversa pra eu analisar.")