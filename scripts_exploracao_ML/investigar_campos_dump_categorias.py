# scripts_exploracao_ML/investigar_campos_dump_categorias.py

# Função Objetivo: Faz um "censo" completo dos campos existentes no dump de categorias já
# baixado (dump_categorias_mlb.json, gerado por baixar_dump_categorias_ml.py) — não descarta
# nada de antemão. Pra cada campo encontrado (de primeiro nível, dentro de "settings", e
# dentro de cada canal de "channels_settings"), mostra quantas categorias têm esse campo e,
# quando o campo tem poucos valores possíveis (enum), lista todos os valores distintos com
# a contagem de cada um. Campos de alta cardinalidade (nome, id, url, etc.) só mostram a
# contagem de distintos + alguns exemplos, pra não poluir o console.
#
# CORRIGIDO (v2): a v1 tinha um bug — campos do tipo LISTA (ex: item_conditions com
# ["new", "used"]) contavam cada item da lista como se fosse +1 categoria, inflando a
# "Presença" acima de 100%. Agora cada categoria contribui no máximo 1x por campo (via
# set de valores por categoria), então Presença nunca passa de total_categorias. Os
# valores individuais (ex: "new=12017") já estavam corretos antes — só a % de presença
# estava errada.
#
# Não chama a API — só lê o JSON já salvo localmente. Não escreve nada no banco.
#
# Uso: python -u "scripts_exploracao_ML/investigar_campos_dump_categorias.py"

import json
from collections import Counter, defaultdict
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

CAMINHO_DUMP = Path(__file__).parent / "dump_categorias_mlb.json"
LIMITE_VALORES_DISTINTOS_PRA_LISTAR = 25  # acima disso, campo é tratado como "textual/alta cardinalidade"


def montar_buffer_categoria(detalhe: dict) -> dict:
    """Retorna dict: caminho -> set(valores como string), só pra ESTA categoria. Usar um
    set garante que, mesmo que o campo seja uma lista com vários itens, essa categoria só
    "vota" 1 vez em cada valor distinto que ela tem — é isso que corrige o bug da v1."""
    buffer = {}

    def visitar(valor, caminho):
        if isinstance(valor, dict):
            for sub_chave, sub_valor in valor.items():
                visitar(sub_valor, f"{caminho}.{sub_chave}" if caminho else sub_chave)
        elif isinstance(valor, list):
            if not valor:
                buffer.setdefault(caminho, set()).add("(lista vazia)")
            else:
                destino = buffer.setdefault(caminho, set())
                for item in valor:
                    destino.add(str(item))
        else:
            buffer.setdefault(caminho, set()).add(str(valor))

    for chave, valor in detalhe.items():
        if chave == "children_categories":
            buffer.setdefault("children_categories (qtd. de filhos diretos)", set()).add(str(len(valor)))
            continue
        if chave == "path_from_root":
            buffer.setdefault("path_from_root (profundidade na árvore)", set()).add(str(len(valor)))
            continue
        if chave == "channels_settings":
            for entrada in valor:
                canal = entrada.get("channel", "?")
                for sub_chave, sub_valor in entrada.get("settings", {}).items():
                    visitar(sub_valor, f"channels_settings.{canal}.{sub_chave}")
            continue
        visitar(valor, chave)

    return buffer


def montar_tabela(titulo, caminhos, presenca_por_campo, valores_por_campo, total_categorias) -> Table:
    tabela = Table(title=titulo, show_lines=False)
    tabela.add_column("Campo", style="bold")
    tabela.add_column("Presença")
    tabela.add_column("Valores encontrados")

    for caminho in sorted(caminhos):
        presenca = presenca_por_campo[caminho]
        contador = valores_por_campo[caminho]
        distintos = len(contador)
        pct_presenca = f"{presenca}/{total_categorias} ({presenca / total_categorias * 100:.1f}%)"

        if distintos <= LIMITE_VALORES_DISTINTOS_PRA_LISTAR:
            texto_valores = ", ".join(f"{valor}={qtd}" for valor, qtd in contador.most_common())
        else:
            exemplos = ", ".join(v for v, _ in contador.most_common(5))
            texto_valores = f"[{distintos} valores distintos — alta cardinalidade] ex: {exemplos}..."

        tabela.add_row(caminho, pct_presenca, texto_valores)

    return tabela


def main():
    if not CAMINHO_DUMP.exists():
        console.print(f"[red]Não achei {CAMINHO_DUMP} — roda primeiro o baixar_dump_categorias_ml.py.[/red]")
        return

    console.print(Panel(f"Lendo {CAMINHO_DUMP} ...", style="cyan"))
    with open(CAMINHO_DUMP, "r", encoding="utf-8") as f:
        dados = json.load(f)

    total_categorias = len(dados)
    console.print(f"[bold]Total de categorias no dump:[/bold] {total_categorias}\n")

    presenca_por_campo = Counter()
    valores_por_campo = defaultdict(Counter)

    for cat_id, detalhe in dados.items():
        buffer = montar_buffer_categoria(detalhe)
        for caminho, valores in buffer.items():
            presenca_por_campo[caminho] += 1
            for v in valores:
                valores_por_campo[caminho][v] += 1

    todos_os_campos = set(presenca_por_campo.keys())
    campos_profundidade = {
        c for c in todos_os_campos
        if c.startswith("children_categories (") or c.startswith("path_from_root (")
    }
    campos_canais = {c for c in todos_os_campos if c.startswith("channels_settings.")}
    campos_settings = {c for c in todos_os_campos if c.startswith("settings.")}
    campos_primeiro_nivel = todos_os_campos - campos_profundidade - campos_canais - campos_settings

    console.print(montar_tabela("Estrutura da árvore", campos_profundidade, presenca_por_campo, valores_por_campo, total_categorias))
    console.print(montar_tabela("Campos de primeiro nível", campos_primeiro_nivel, presenca_por_campo, valores_por_campo, total_categorias))
    console.print(montar_tabela("Campos dentro de 'settings'", campos_settings, presenca_por_campo, valores_por_campo, total_categorias))
    console.print(montar_tabela("Campos dentro de 'channels_settings' (por canal)", campos_canais, presenca_por_campo, valores_por_campo, total_categorias))

    valores_itens = [
        v for detalhe in dados.values()
        if isinstance((v := detalhe.get("total_items_in_this_category")), (int, float))
    ]
    if valores_itens:
        valores_itens.sort()
        n = len(valores_itens)
        mediana = valores_itens[n // 2]
        zeradas = sum(1 for v in valores_itens if v == 0)
        console.print(Panel(
            f"total_items_in_this_category — min: {valores_itens[0]}, mediana: {mediana}, "
            f"máx: {valores_itens[-1]}, categorias com 0 itens: {zeradas}",
            title="Estatística — total_items_in_this_category", style="yellow"
        ))

    console.print(Panel("Fim do censo. Nenhum dado foi descartado — está tudo listado acima.", style="green"))


if __name__ == "__main__":
    main()