# scripts_exploracao_ML/investigar_cobertura_picture_por_nivel.py
#
# Função Objetivo: Responde uma pergunta específica que o censo geral
# (investigar_campos_dump_categorias.py) não separa: em quantas categorias
# o campo "picture" tem uma URL de verdade (não None), e como essa
# cobertura varia por nível de profundidade da árvore (path_from_root).
# Objetivo prático: decidir se dá pra confiar no ícone da API pros
# primeiros níveis do novo layout, e confirmar que as folhas profundas
# precisam de um ícone genérico de fallback.
#
# Não chama a API, só lê o dump_categorias_mlb.json já baixado. Não
# grava nada no banco.
#
# Uso: python scripts_exploracao_ML/investigar_cobertura_picture_por_nivel.py

import json
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()
CAMINHO_DUMP = Path(__file__).parent / "dump_categorias_mlb.json"


def main():
    if not CAMINHO_DUMP.exists():
        console.print(f"[red]Não achei {CAMINHO_DUMP} — roda o baixar_dump_categorias_ml.py primeiro.[/red]")
        return

    with open(CAMINHO_DUMP, "r", encoding="utf-8") as f:
        dados = json.load(f)

    com_imagem_por_nivel = defaultdict(int)
    sem_imagem_por_nivel = defaultdict(int)

    for detalhe in dados.values():
        nivel = len(detalhe.get("path_from_root") or []) or 1
        if detalhe.get("picture"):
            com_imagem_por_nivel[nivel] += 1
        else:
            sem_imagem_por_nivel[nivel] += 1

    tabela = Table(title="Cobertura de 'picture' por nível da árvore")
    tabela.add_column("Nível", style="bold")
    tabela.add_column("Com imagem real")
    tabela.add_column("Sem imagem (None)")
    tabela.add_column("% com imagem")

    for nivel in sorted(set(com_imagem_por_nivel) | set(sem_imagem_por_nivel)):
        com = com_imagem_por_nivel[nivel]
        sem = sem_imagem_por_nivel[nivel]
        total = com + sem
        tabela.add_row(str(nivel), str(com), str(sem), f"{com / total * 100:.1f}%")

    console.print(tabela)


if __name__ == "__main__":
    main()