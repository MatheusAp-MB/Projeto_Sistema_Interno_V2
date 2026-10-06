# scripts_exploracao_ML/investigar_grupos_technical_specs.py
#
# Função Objetivo: descobrir, com dado real, ONDE ficam as características
# "secundárias" de uma categoria do Mercado Livre.
#
# Ponto de partida: a tela "Características dos anúncios" usa SÓ o grupo
# "MAIN" da resposta de GET /categories/$CATEGORY_ID/technical_specs/input e
# descarta todos os outros grupos dessa mesma resposta (ver
# api_mercado_livre/atributos_ml.py, método buscar_card_categoria). Este
# script olha a resposta INTEIRA, sem descartar nada, e responde:
#   1) Quais grupos existem (id, rótulo) e quantos campos cada um tem.
#   2) Os campos dos outros grupos têm o MESMO formato dos do MAIN?
#      (mesmas chaves no grupo, no componente e no atributo)
#   3) Quais etiquetas (tags) cada grupo carrega.
#   4) Existem atributos em GET /categories/$CATEGORY_ID/attributes que não
#      aparecem em NENHUM grupo?
#   5) Dos atributos que o anúncio já tem preenchidos, em que grupo cada um cai?
#
# Nada é suposto: os nomes dos grupos e das etiquetas são lidos da própria
# resposta, não de uma lista escrita aqui.
#
# Custo: 3 chamadas GET (o item, a ficha da categoria e os atributos da
# categoria). Só leitura. Não toca no banco e não grava nada além dos
# arquivos de saída (4 arquivos .json em scripts_exploracao_ML/, que o
# .gitignore já cobre pela regra "scripts_exploracao_ML/*.json"):
#   investigacao_grupos_<MLB>_technical_specs_input.json  -> resposta CRUA da ficha
#   investigacao_grupos_<MLB>_categoria_attributes.json   -> resposta CRUA dos atributos
#   investigacao_grupos_<MLB>_item_atributos.json         -> só id/categoria/título/attributes do item
#                                                            (de propósito NÃO guarda o resto do item:
#                                                            endereço do vendedor, estoque, preço...)
#   investigacao_grupos_<MLB>_resumo.json                 -> o resumo desta análise (o menor, o mais
#                                                            fácil de me mandar na conversa)

import json
import sys
from collections import Counter
from pathlib import Path

# Permite rodar este script direto (python scripts_exploracao_ML/investigar_grupos_technical_specs.py),
# de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
MLB = "MLB2696429175"  # SKU F7891988006671.001 (Guarany PCP-1,25) — categoria Pulverizadores Manuais
CONTA = "MB"           # "MB" (Magazine) ou "SV" (Samvale) — CONFIRME de qual empresa é esse MLB antes de rodar
# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
PASTA_LOGS = PASTA_SCRIPT / "logs"
NOME_LOG = "investigar_grupos_technical_specs"
MLB_LIMPO = MLB.strip().upper()

SEM_GRUPO = "(nenhum grupo)"
LIMITE_LINHAS_NA_TELA = 60   # por tabela; o arquivo de resumo sempre sai completo


def t(valor) -> str:
    """Texto vindo da API pode ter colchetes ("[x]"); o rich leria como formatação — escapa antes de mostrar."""
    return escape(str(valor))


def caminho_saida(sufixo: str) -> Path:
    return PASTA_SCRIPT / f"investigacao_grupos_{MLB_LIMPO}_{sufixo}.json"


def salvar_json(sufixo: str, conteudo) -> Path:
    caminho = caminho_saida(sufixo)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=2)
    return caminho


def buscar(endpoint: str, params: dict = None):
    """1 chamada GET. Se a API recusar, mostra o motivo e para — não tenta de novo."""
    try:
        resposta = chamar_api(
            "GET", endpoint,
            pasta_logs=PASTA_LOGS, conta=CONTA,
            params=params, nome_log=NOME_LOG,
        )
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        console.print(f"[red]Erro ao chamar {endpoint}: {erro}[/red]")
        sys.exit(1)
    return resposta.json()


# ---------------------------------------------------------------------------
# Leitura "sem opinião" da resposta: tags podem vir como lista (technical_specs)
# ou como dict {tag: true} (/attributes) — os dois viram uma lista ordenada.
# ---------------------------------------------------------------------------
def tags_ativas(objeto) -> list:
    tags = objeto.get("tags") if isinstance(objeto, dict) else None
    if isinstance(tags, dict):
        return sorted(str(k) for k, v in tags.items() if v)
    if isinstance(tags, list):
        return sorted(str(t) for t in tags)
    return []


def rotulo_de(objeto, padrao="") -> str:
    if not isinstance(objeto, dict):
        return padrao
    return str(objeto.get("label") or objeto.get("name") or padrao)


def valor_do_item(atributo_item) -> str:
    """Como o anúncio tem esse atributo hoje (texto curto para a tabela)."""
    if atributo_item is None:
        return ""
    if str(atributo_item.get("value_id")) == "-1":
        return "N/A"
    nome = atributo_item.get("value_name")
    if nome not in (None, ""):
        return str(nome)
    nomes = [str(v.get("name")) for v in (atributo_item.get("values") or [])
             if isinstance(v, dict) and v.get("name")]
    return ", ".join(nomes) if nomes else "(vazio)"


def indexar_definicoes(atributos_da_categoria) -> dict:
    """{atributo_id: definição resumida} a partir de GET /categories/{id}/attributes."""
    definicoes = {}
    if not isinstance(atributos_da_categoria, list):
        return definicoes
    for attr in atributos_da_categoria:
        attr_id = attr.get("id")
        if not attr_id:
            continue
        definicoes[attr_id] = {
            "name": attr.get("name"),
            "value_type": attr.get("value_type"),
            "value_max_length": attr.get("value_max_length"),
            "n_opcoes": len(attr.get("values") or []),
            "tem_unidades": bool(attr.get("allowed_units")),
            "tags": tags_ativas(attr),
        }
    return definicoes


def resumir_grupos(technical_specs, item_por_id: dict, definicoes: dict) -> list:
    """Percorre TODOS os grupos -> componentes -> atributos, sem descartar nenhum."""
    grupos = []
    lista_de_grupos = technical_specs.get("groups") if isinstance(technical_specs, dict) else None
    for grupo in lista_de_grupos or []:
        atributos = []
        tipos_componente = Counter()
        chaves_componente, chaves_atributo = set(), set()

        def registrar(attr, componente=None):
            chaves_atributo.update(attr.keys())
            attr_id = attr.get("id")
            definicao = definicoes.get(attr_id) or {}
            ui_config = (componente or {}).get("ui_config") or {}
            atributos.append({
                "id": attr_id,
                "rotulo": rotulo_de(attr) or rotulo_de(componente) or str(attr_id),
                "componente": (componente or {}).get("component"),
                "rotulo_do_componente": rotulo_de(componente) if componente else "",
                "tags": tags_ativas(attr),
                "allow_custom_value": ui_config.get("allow_custom_value"),
                "chaves_do_atributo": sorted(attr.keys()),
                "value_type": definicao.get("value_type"),
                "value_max_length": definicao.get("value_max_length"),
                "n_opcoes": definicao.get("n_opcoes"),
                "tem_unidades": definicao.get("tem_unidades"),
                "tags_em_attributes": definicao.get("tags"),
                "tem_definicao_em_attributes": attr_id in definicoes,
                "preenchido_no_item": attr_id in item_por_id,
                "valor_no_item": valor_do_item(item_por_id.get(attr_id)),
            })

        for componente in grupo.get("components") or []:
            chaves_componente.update(componente.keys())
            tipos_componente[str(componente.get("component"))] += 1
            for attr in componente.get("attributes") or []:
                registrar(attr, componente)
        # Robustez: se algum grupo trouxer atributos direto nele (sem componente), também entram.
        for attr in grupo.get("attributes") or []:
            registrar(attr)

        grupos.append({
            "id": grupo.get("id"),
            "rotulo": rotulo_de(grupo, str(grupo.get("id"))),
            "chaves_do_grupo": sorted(grupo.keys()),
            "n_componentes": len(grupo.get("components") or []),
            "n_atributos": len(atributos),
            "tipos_de_componente": dict(tipos_componente),
            "chaves_do_componente": sorted(chaves_componente),
            "chaves_do_atributo": sorted(chaves_atributo),
            "tags_do_grupo": dict(Counter(t for a in atributos for t in a["tags"]).most_common()),
            "atributos": atributos,
        })
    return grupos


def comparar_formato_com_main(grupos: list) -> dict:
    """Para cada grupo que não é o MAIN: que chaves ele tem a mais / a menos que o MAIN."""
    main = next((g for g in grupos if g["id"] == "MAIN"), None)
    if main is None:
        return {}
    diferencas = {}
    for g in grupos:
        if g is main:
            continue
        diferencas[g["id"]] = {}
        for nivel in ("chaves_do_grupo", "chaves_do_componente", "chaves_do_atributo"):
            neste, no_main = set(g[nivel]), set(main[nivel])
            diferencas[g["id"]][nivel] = {
                "so_neste_grupo": sorted(neste - no_main),
                "so_no_MAIN": sorted(no_main - neste),
            }
    return diferencas


def tabela_de_atributos(grupo: dict) -> Table:
    tabela = Table(
        title=f"Grupo {t(grupo['id'])} — {t(grupo['rotulo'])} — {grupo['n_atributos']} atributo(s)",
        title_justify="left", show_lines=False,
    )
    for coluna in ("ID na API", "Rótulo", "Componente", "Tags", "Tipo", "Opções", "No anúncio"):
        tabela.add_column(coluna, overflow="fold")
    for a in grupo["atributos"][:LIMITE_LINHAS_NA_TELA]:
        tabela.add_row(
            t(a["id"]), t(a["rotulo"]), t(a["componente"] or ""),
            t(", ".join(a["tags"])), t(a["value_type"] or "—"),
            t(a["n_opcoes"]) if a["n_opcoes"] is not None else "—",
            t(a["valor_no_item"]) if a["preenchido_no_item"] else "[dim]não preenchido[/dim]",
        )
    if len(grupo["atributos"]) > LIMITE_LINHAS_NA_TELA:
        tabela.caption = f"... e mais {len(grupo['atributos']) - LIMITE_LINHAS_NA_TELA} (tudo está no arquivo de resumo)"
    return tabela


def main():
    console.print(Panel.fit(
        f"Item: [bold]{MLB_LIMPO}[/bold]   Conta: [bold]{CONTA}[/bold]\n"
        "3 chamadas GET, só leitura — nada é gravado no banco nem enviado ao ML.",
        title="Investigando os grupos de características da categoria", style="cyan",
    ))

    # 1) O item: só pra descobrir a categoria e quais atributos ele já tem preenchidos.
    item = buscar(f"/items/{MLB_LIMPO}", params={"include_internal_attributes": "true"})
    category_id = item.get("category_id")
    if not category_id:
        console.print("[red]A resposta do item não trouxe category_id — veja o log em scripts_exploracao_ML/logs.[/red]")
        sys.exit(1)
    atributos_do_item = item.get("attributes") or []
    item_por_id = {a.get("id"): a for a in atributos_do_item if a.get("id")}
    salvar_json("item_atributos", {
        "id": item.get("id"), "category_id": category_id,
        "domain_id": item.get("domain_id"), "title": item.get("title"),
        "attributes": atributos_do_item,
    })

    # 2) A ficha da categoria — a resposta inteira, todos os grupos.
    technical_specs = buscar(f"/categories/{category_id}/technical_specs/input")
    salvar_json("technical_specs_input", technical_specs)

    # 3) Os atributos da categoria — pra cruzar com os grupos.
    atributos_da_categoria = buscar(f"/categories/{category_id}/attributes")
    salvar_json("categoria_attributes", atributos_da_categoria)

    definicoes = indexar_definicoes(atributos_da_categoria)
    grupos = resumir_grupos(technical_specs, item_por_id, definicoes)
    formato_vs_main = comparar_formato_com_main(grupos)

    ids_em_algum_grupo = {a["id"] for g in grupos for a in g["atributos"]}
    grupos_por_atributo = {}
    for g in grupos:
        for a in g["atributos"]:
            grupos_por_atributo.setdefault(a["id"], []).append(g["id"])
    repetidos = {attr_id: lista for attr_id, lista in grupos_por_atributo.items() if len(lista) > 1}

    fora_de_grupo = [
        {"id": attr_id, **definicao}
        for attr_id, definicao in definicoes.items() if attr_id not in ids_em_algum_grupo
    ]
    sem_definicao = sorted(i for i in ids_em_algum_grupo if i not in definicoes)

    item_por_grupo = {}
    for attr_id in item_por_id:
        for nome_grupo in grupos_por_atributo.get(attr_id, [SEM_GRUPO]):
            item_por_grupo.setdefault(nome_grupo, []).append(attr_id)

    # ----- tela -----
    chaves_topo = sorted(technical_specs.keys()) if isinstance(technical_specs, dict) else []
    console.print(f"\nCategoria: [bold]{t(category_id)}[/bold]  |  domain_id: {t(item.get('domain_id'))}  |  {t(item.get('title'))}")
    console.print(f"Chaves do topo da resposta de technical_specs/input: {t(chaves_topo)}")
    if not grupos:
        console.print("[yellow]Nenhum grupo encontrado em \"groups\" — o formato é outro; abra o arquivo "
                      f"{caminho_saida('technical_specs_input').name} (resposta crua).[/yellow]")

    resumo_grupos = Table(title="Grupos encontrados", title_justify="left")
    for coluna in ("ID", "Rótulo", "Componentes", "Atributos", "Tipos de componente", "Tags mais comuns"):
        resumo_grupos.add_column(coluna, overflow="fold")
    for g in grupos:
        resumo_grupos.add_row(
            t(g["id"]), t(g["rotulo"]), str(g["n_componentes"]), str(g["n_atributos"]),
            t(", ".join(f"{k} ×{v}" for k, v in g["tipos_de_componente"].items())),
            t(", ".join(f"{k} ×{v}" for k, v in list(g["tags_do_grupo"].items())[:8])),
        )
    console.print(resumo_grupos)

    for g in grupos:
        console.print()
        console.print(tabela_de_atributos(g))

    console.print("\n[bold]O formato dos outros grupos é igual ao do MAIN?[/bold]")
    if not formato_vs_main:
        console.print("  (não há grupo MAIN na resposta, ou só existe ele — nada a comparar)")
    for grupo_id, niveis in formato_vs_main.items():
        iguais = all(not v["so_neste_grupo"] and not v["so_no_MAIN"] for v in niveis.values())
        console.print(f"  Grupo {t(grupo_id)}: " + ("[green]mesmas chaves do MAIN[/green]" if iguais else "[yellow]chaves diferentes[/yellow]"))
        for nivel, v in niveis.items():
            if v["so_neste_grupo"] or v["so_no_MAIN"]:
                console.print(f"    {nivel}: só neste grupo = {t(v['so_neste_grupo'])} | só no MAIN = {t(v['so_no_MAIN'])}")

    if repetidos:
        console.print(f"\n[yellow]Atributos que aparecem em mais de um grupo:[/yellow] {t(repetidos)}")

    console.print(f"\n[bold]Atributos de /categories/{t(category_id)}/attributes que NÃO estão em nenhum grupo:[/bold] {len(fora_de_grupo)} de {len(definicoes)}")
    if fora_de_grupo:
        tabela_fora = Table(title_justify="left")
        for coluna in ("ID na API", "Nome", "Tipo", "Opções", "Tags"):
            tabela_fora.add_column(coluna, overflow="fold")
        for d in fora_de_grupo[:LIMITE_LINHAS_NA_TELA]:
            tabela_fora.add_row(t(d["id"]), t(d["name"]), t(d["value_type"]), str(d["n_opcoes"]), t(", ".join(d["tags"])))
        if len(fora_de_grupo) > LIMITE_LINHAS_NA_TELA:
            tabela_fora.caption = f"... e mais {len(fora_de_grupo) - LIMITE_LINHAS_NA_TELA} (tudo está no arquivo de resumo)"
        console.print(tabela_fora)
    if sem_definicao:
        console.print(f"[yellow]Estão em algum grupo mas não existem em /attributes:[/yellow] {t(sem_definicao)}")

    console.print(f"\n[bold]Atributos que o anúncio já tem preenchidos ({len(item_por_id)}), por grupo:[/bold]")
    for nome_grupo, ids in item_por_grupo.items():
        console.print(f"  {t(nome_grupo)}: {len(ids)} -> {t(ids)}")

    # ----- arquivo de resumo (o que me mandar na conversa) -----
    caminho_resumo = salvar_json("resumo", {
        "mlb": MLB_LIMPO, "conta": CONTA,
        "categoria": {"id": category_id, "domain_id": item.get("domain_id"), "titulo_do_item": item.get("title")},
        "chaves_do_topo_technical_specs": chaves_topo,
        "grupos": grupos,
        "formato_dos_grupos_vs_MAIN": formato_vs_main,
        "atributos_em_mais_de_um_grupo": repetidos,
        "categoria_attributes": {
            "total": len(definicoes),
            "fora_de_qualquer_grupo": fora_de_grupo,
            "em_grupo_sem_definicao_em_attributes": sem_definicao,
            "tags_dos_que_estao_fora_de_grupo": dict(Counter(t for d in fora_de_grupo for t in d["tags"]).most_common()),
        },
        "item": {"n_atributos_preenchidos": len(item_por_id), "por_grupo": item_por_grupo},
    })

    console.print(Panel.fit(
        f"Resumo (me mande este): {caminho_resumo.name}\n"
        f"Resposta crua da ficha: {caminho_saida('technical_specs_input').name}\n"
        f"Resposta crua dos atributos: {caminho_saida('categoria_attributes').name}\n"
        f"Atributos do item: {caminho_saida('item_atributos').name}\n"
        f"Pasta: {PASTA_SCRIPT}",
        title="Arquivos salvos", style="green",
    ))


if __name__ == "__main__":
    main()
