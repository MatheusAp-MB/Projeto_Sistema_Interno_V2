# scripts_exploracao_ML/comparar_atributos_item_vs_grupo_main.py

# Função Objetivo: valida a hipótese central da investigação de Características/Atributos ML
# — que o bloco "Características principais" da tela do anúncio corresponde ao grupo de
# atributos com id "MAIN" dentro de GET /categories/$CATEGORY_ID/technical_specs/input
# (confirmado na doc oficial: esse grupo vem com "label": "Características principales").
# Ver Checkpoint - Investigação da API de Atributos do Mercado Livre, no vault.
#
# Achado do 1º teste (investigar_atributos_item.py, 01/10/2026): a resposta de
# GET /items/$ITEM_ID NÃO traz attribute_group_id/attribute_group_name em nenhum atributo
# (diferente do exemplo da doc) — então não dá pra saber, só pelo item, quais atributos
# preenchidos são "Características principais". Este script resolve isso buscando o grupo
# MAIN separadamente, pela categoria do item, e cruzando pelo id de cada atributo.
#
# Lê o JSON já salvo por investigar_atributos_item.py (não refaz a chamada GET /items) e
# busca ao vivo só o technical_specs/input da categoria desse item — category_id vem direto
# do JSON já salvo, sem precisar hardcodar de novo.
#
# Pra cada atributo do grupo MAIN, mostra: rótulo da tela, se é "required", se está
# preenchido no item e qual o valor atual — e sinaliza separadamente (a) atributos
# preenchidos no item que NÃO pertencem ao MAIN, e (b) obrigatórios do MAIN ausentes no item.
#
# Só leitura. Não toca no banco, não grava nada além do arquivo de saída (o retorno bruto
# de technical_specs/input, pelo mesmo motivo do script anterior: nada filtrado na origem).

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Permite rodar este script direto (python scripts_exploracao_ML/comparar_atributos_item_vs_grupo_main.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MLB = "MLB2616936722"
CONTA = "MB"  # mesma conta usada em investigar_atributos_item.py pra esse MLB
# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
PASTA_LOGS = PASTA_SCRIPT / "logs"
CAMINHO_ITEM_SALVO = PASTA_SCRIPT / f"investigacao_atributos_{MLB}.json"
CAMINHO_SAIDA_TECHNICAL_SPECS = PASTA_SCRIPT / f"investigacao_technical_specs_input_{MLB}.json"


def carregar_item_salvo():
    if not CAMINHO_ITEM_SALVO.exists():
        console.print(
            f"[red]Não achei {CAMINHO_ITEM_SALVO.name} — roda primeiro "
            f"investigar_atributos_item.py pra esse MLB.[/red]"
        )
        sys.exit(1)
    with open(CAMINHO_ITEM_SALVO, "r", encoding="utf-8") as f:
        return json.load(f)


def buscar_technical_specs_input(category_id):
    resposta = chamar_api(
        "GET", f"/categories/{category_id}/technical_specs/input",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="comparar_atributos_item_vs_grupo_main",
    )
    return resposta.json()


def extrair_ids_do_grupo_main(technical_specs):
    """
    Varre groups -> components -> attributes e devolve, só pro grupo cujo id
    é "MAIN", um dict {attribute_id: {label, required}}. required é lido da
    tag "required" dentro de attribute["tags"] — doc mostra "tags" como lista
    de strings neste recurso (diferente do dict usado em /categories/$ID/attributes),
    mas tratamos os dois formatos por segurança.
    """
    ids_main = {}
    for grupo in technical_specs.get("groups", []):
        if grupo.get("id") != "MAIN":
            continue
        for componente in grupo.get("components", []):
            for atributo in componente.get("attributes", []):
                attr_id = atributo.get("id")
                if not attr_id:
                    continue
                tags = atributo.get("tags") or []
                if isinstance(tags, dict):
                    obrigatorio = bool(tags.get("required"))
                else:
                    obrigatorio = "required" in tags
                ids_main[attr_id] = {
                    "label": componente.get("label") or atributo.get("name") or attr_id,
                    "required": obrigatorio,
                }
    return ids_main


def main():
    item = carregar_item_salvo()
    category_id = item.get("category_id")
    if not category_id:
        console.print(f"[red]O JSON salvo não tem category_id — confere {CAMINHO_ITEM_SALVO.name}.[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        f"Item: [bold]{MLB}[/bold] — {item.get('title', '')}\n"
        f"Categoria: [bold]{category_id}[/bold] — domain_id: {item.get('domain_id', '')}",
        title="Cruzando atributos do item com o grupo MAIN da categoria",
        style="cyan",
    ))

    try:
        technical_specs = buscar_technical_specs_input(category_id)
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        console.print(f"[red]Erro ao chamar a API: {erro}[/red]")
        sys.exit(1)

    with open(CAMINHO_SAIDA_TECHNICAL_SPECS, "w", encoding="utf-8") as f:
        json.dump(technical_specs, f, ensure_ascii=False, indent=2)
    console.print(f"Retorno bruto de technical_specs/input salvo em: {CAMINHO_SAIDA_TECHNICAL_SPECS.name}\n")

    ids_main = extrair_ids_do_grupo_main(technical_specs)
    atributos_do_item = {a["id"]: a for a in item.get("attributes", []) if a.get("id")}

    qtd_obrigatorios = sum(1 for v in ids_main.values() if v["required"])
    console.print(
        f"[bold]Grupo MAIN da categoria {category_id}:[/bold] {len(ids_main)} atributo(s) "
        f"({qtd_obrigatorios} marcado(s) 'required')"
    )
    console.print(f"[bold]Item {MLB}:[/bold] {len(atributos_do_item)} atributo(s) preenchido(s)\n")

    tabela = Table(title="MAIN — Características principais, atributo por atributo")
    tabela.add_column("Atributo (id)")
    tabela.add_column("Rótulo na tela")
    tabela.add_column("Obrigatório?")
    tabela.add_column("Preenchido no item?")
    tabela.add_column("Valor atual no item")

    for attr_id, info in ids_main.items():
        preenchido = attr_id in atributos_do_item
        valor_atual = atributos_do_item[attr_id].get("value_name", "") if preenchido else ""
        tabela.add_row(
            attr_id,
            info["label"],
            "[yellow]Sim[/yellow]" if info["required"] else "Não",
            "[green]Sim[/green]" if preenchido else "[red]NÃO[/red]",
            valor_atual,
        )
    console.print(tabela)

    fora_do_main = [attr_id for attr_id in atributos_do_item if attr_id not in ids_main]
    if fora_do_main:
        console.print(
            f"\n[dim]{len(fora_do_main)} atributo(s) preenchido(s) no item que NÃO estão "
            f"no grupo MAIN: {', '.join(fora_do_main)}[/dim]"
        )

    faltando_obrigatorio = [
        attr_id for attr_id, info in ids_main.items()
        if info["required"] and attr_id not in atributos_do_item
    ]
    if faltando_obrigatorio:
        console.print(
            f"\n[bold red]ATENÇÃO — obrigatório(s) do MAIN ausente(s) no item: "
            f"{', '.join(faltando_obrigatorio)}[/bold red]"
        )
    else:
        console.print("\n[bold green]Nenhum atributo MAIN marcado 'required' está faltando neste item.[/bold green]")


if __name__ == "__main__":
    main()