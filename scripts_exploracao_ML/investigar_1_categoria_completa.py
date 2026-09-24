# scripts_exploracao_ML/investigar_1_categoria_completa.py
import json
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
CAMINHO_DUMP = Path(__file__).parent / "dump_categorias_mlb.json"

CAMPOS_PRIMEIRO_NIVEL_JA_TRATADOS = {
    "id", "name", "permalink", "total_items_in_this_category",
    "path_from_root", "children_categories", "attribute_types",
    "settings", "channels_settings", "translations",
}


def carregar_dump():
    if not CAMINHO_DUMP.exists():
        console.print(f"[red]Não achei {CAMINHO_DUMP} — roda primeiro o baixar_dump_categorias_ml.py.[/red]")
        sys.exit(1)
    with open(CAMINHO_DUMP, "r", encoding="utf-8") as f:
        return json.load(f)


def escolher_categoria(dados, argumento):
    """
    Decide qual categoria mostrar:
    - Sem argumento: escolhe automaticamente uma categoria rica em dados E com
      itens reais publicados (evita cair numa categoria vazia ou de serviço,
      que não representa bem um catálogo de produto físico).
    - Argumento bate com uma chave (ID) exata: usa direto.
    - Argumento não bate com nenhum ID: trata como busca por nome (parcial,
      sem diferenciar maiúscula/minúscula).
    """
    if argumento is None:
        console.print(
            "[yellow]Nenhuma categoria informada — escolhendo automaticamente uma categoria rica em dados "
            "e com itens reais publicados (evitando cair numa categoria vazia ou de serviço), "
            "pra servir de exemplo representativo.[/yellow]\n"
        )

        def pontuar(detalhe):
            attrs = detalhe.get("attribute_types")
            pontuacao_attrs = len(attrs) if isinstance(attrs, (dict, list)) else 0
            return (
                len(detalhe.get("settings", {}) or {})
                + len(detalhe.get("channels_settings", []) or [])
                + len(detalhe.get("translations", {}) or {})
                + pontuacao_attrs
            )

        candidatos = [
            (cat_id, detalhe) for cat_id, detalhe in dados.items()
            if (detalhe.get("total_items_in_this_category") or 0) > 1000
        ]
        if not candidatos:
            candidatos = list(dados.items())

        melhor_id, melhor_detalhe = max(candidatos, key=lambda par: pontuar(par[1]))
        return melhor_id, melhor_detalhe

    if argumento in dados:
        return argumento, dados[argumento]

    termo = argumento.lower()
    encontrados = [
        (cat_id, detalhe) for cat_id, detalhe in dados.items()
        if termo in (detalhe.get("name") or "").lower()
    ]
    if not encontrados:
        console.print(f"[red]Não achei nenhuma categoria com ID ou nome contendo '{argumento}'.[/red]")
        sys.exit(1)
    if len(encontrados) > 1:
        console.print(f"[yellow]{len(encontrados)} categorias encontradas com '{argumento}' no nome — mostrando as 15 primeiras. Rode de novo passando o ID exato pra ver os detalhes de uma delas:[/yellow]")
        tabela = Table()
        tabela.add_column("ID")
        tabela.add_column("Nome")
        tabela.add_column("Nº de itens na categoria")
        for cat_id, detalhe in encontrados[:15]:
            tabela.add_row(cat_id, detalhe.get("name", ""), str(detalhe.get("total_items_in_this_category", "")))
        console.print(tabela)
        sys.exit(0)
    return encontrados[0]


def tabela_chave_valor(titulo, itens):
    tabela = Table(title=titulo, show_lines=False)
    tabela.add_column("Campo", style="bold")
    tabela.add_column("Valor")
    for chave, valor in itens:
        tabela.add_row(str(chave), str(valor))
    return tabela


def mostrar_identidade(cat_id, detalhe):
    settings = detalhe.get("settings", {}) or {}
    linhas = [
        ("ID", cat_id),
        ("Nome", detalhe.get("name")),
        ("Permalink", detalhe.get("permalink")),
        ("Total de itens na categoria", detalhe.get("total_items_in_this_category")),
        ("É folha? (sem filhos)", "Sim" if not detalhe.get("children_categories") else "Não"),
        ("listing_allowed (aceita anúncio novo)", settings.get("listing_allowed")),
        ("status", settings.get("status")),
        ("vertical", settings.get("vertical")),
        ("catalog_domain", settings.get("catalog_domain")),
    ]
    console.print(Panel.fit(
        "\n".join(f"[bold]{k}:[/bold] {v}" for k, v in linhas),
        title="Identidade rápida",
        style="cyan",
    ))


def mostrar_outros_campos_primeiro_nivel(detalhe):
    """
    Rede de segurança: qualquer campo de primeiro nível que eu não tratei
    explicitamente em nenhuma outra seção aparece aqui, automaticamente.
    Garante que nada fica escondido só no JSON bruto do final.
    """
    outros = [
        (chave, valor) for chave, valor in detalhe.items()
        if chave not in CAMPOS_PRIMEIRO_NIVEL_JA_TRATADOS
    ]
    if not outros:
        return
    itens = []
    for chave, valor in outros:
        valor_str = json.dumps(valor, ensure_ascii=False) if isinstance(valor, (list, dict)) else valor
        itens.append((chave, valor_str))
    console.print(tabela_chave_valor(f"Outros campos de primeiro nível ({len(outros)}) — não cobertos pelas seções acima", itens))


def mostrar_caminho_hierarquia(detalhe):
    caminho = detalhe.get("path_from_root", []) or []
    if not caminho:
        console.print("[dim](sem path_from_root)[/dim]\n")
        return
    tabela = Table(title="path_from_root — hierarquia da raiz até esta categoria")
    tabela.add_column("Nível")
    tabela.add_column("ID")
    tabela.add_column("Nome")
    for nivel, passo in enumerate(caminho, start=1):
        tabela.add_row(str(nivel), passo.get("id", ""), passo.get("name", ""))
    console.print(tabela)


def mostrar_filhos(detalhe):
    filhos = detalhe.get("children_categories", []) or []
    if not filhos:
        console.print("[dim](sem children_categories — categoria folha)[/dim]\n")
        return
    tabela = Table(title=f"children_categories — {len(filhos)} filho(s) direto(s)")
    tabela.add_column("ID")
    tabela.add_column("Nome")
    tabela.add_column("Total de itens")
    for filho in filhos:
        tabela.add_row(filho.get("id", ""), filho.get("name", ""), str(filho.get("total_items_in_this_category", "")))
    console.print(tabela)


def mostrar_settings(detalhe):
    settings = detalhe.get("settings", {}) or {}
    if not settings:
        console.print("[dim](sem settings)[/dim]\n")
        return
    itens = []
    for chave, valor in settings.items():
        valor_str = json.dumps(valor, ensure_ascii=False) if isinstance(valor, (list, dict)) else valor
        itens.append((chave, valor_str))
    console.print(tabela_chave_valor(f"settings — TODOS os {len(settings)} campos", itens))


def mostrar_attribute_types(detalhe):
    attrs = detalhe.get("attribute_types")
    if not attrs:
        console.print("[dim](sem attribute_types)[/dim]\n")
        return
    if isinstance(attrs, dict):
        console.print(tabela_chave_valor("attribute_types", list(attrs.items())))
    else:
        console.print(Panel(f"{attrs!r} (tipo: {type(attrs).__name__} — não é um dict de atributos reais, parece ser só um marcador/link pro endpoint separado /categories/{{id}}/attributes)", title="attribute_types"))


def mostrar_channels_settings(detalhe):
    canais = detalhe.get("channels_settings", []) or []
    if not canais:
        console.print("[dim](sem channels_settings)[/dim]\n")
        return
    for entrada in canais:
        canal = entrada.get("channel", "?")
        settings_canal = entrada.get("settings", {}) or {}
        itens = []
        for chave, valor in settings_canal.items():
            valor_str = json.dumps(valor, ensure_ascii=False) if isinstance(valor, (list, dict)) else valor
            itens.append((chave, valor_str))
        console.print(tabela_chave_valor(f"channels_settings — canal '{canal}' ({len(settings_canal)} campos)", itens))


def mostrar_translations(detalhe):
    traducoes = detalhe.get("translations", {}) or {}
    if not traducoes:
        console.print("[dim](sem translations)[/dim]\n")
        return
    tabela = Table(title=f"translations — {len(traducoes)} idioma(s)")
    tabela.add_column("Idioma")
    tabela.add_column("Nome traduzido")
    tabela.add_column("Profundidade (path_from_root)")
    tabela.add_column("Qtd. filhos")
    for idioma, dado in traducoes.items():
        tabela.add_row(
            idioma,
            str(dado.get("name", "")),
            str(len(dado.get("path_from_root", []) or [])),
            str(len(dado.get("children_categories", []) or [])),
        )
    console.print(tabela)


def mostrar_json_bruto_completo(cat_id, detalhe):
    console.print(Panel(
        "Abaixo o JSON bruto e completo desta categoria, exatamente como veio da API — "
        "nada foi resumido, cortado ou descartado. Essa é a fonte de verdade final, "
        "caso algum campo não tenha aparecido nas tabelas organizadas acima.",
        title=f"JSON bruto completo — {cat_id}",
        style="green",
    ))
    console.print_json(json.dumps(detalhe, ensure_ascii=False))


def main():
    argumento = sys.argv[1] if len(sys.argv) > 1 else None
    dados = carregar_dump()
    cat_id, detalhe = escolher_categoria(dados, argumento)

    console.print(Panel.fit(
        f"Categoria selecionada: [bold]{cat_id}[/bold] — {detalhe.get('name', '')}",
        style="bold magenta",
    ))
    console.print()

    mostrar_identidade(cat_id, detalhe)
    console.print()
    mostrar_outros_campos_primeiro_nivel(detalhe)
    console.print()
    mostrar_caminho_hierarquia(detalhe)
    console.print()
    mostrar_filhos(detalhe)
    console.print()
    mostrar_settings(detalhe)
    console.print()
    mostrar_attribute_types(detalhe)
    console.print()
    mostrar_channels_settings(detalhe)
    console.print()
    mostrar_translations(detalhe)
    console.print()
    mostrar_json_bruto_completo(cat_id, detalhe)

    console.print(Panel(
        "Pra ver outra categoria:\n"
        f"  python {Path(__file__).name} <ID_DA_CATEGORIA>\n"
        f"  python {Path(__file__).name} \"<pedaço do nome>\"   (busca por nome)",
        title="Como usar",
        style="dim",
    ))


if __name__ == "__main__":
    main()