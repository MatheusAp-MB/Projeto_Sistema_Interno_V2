"""
VISUALIZAÇÃO — Painel de Promoções de 1 MLB (print bonito, terminal)
=========================================================================
Junta tudo que já mapeamos sobre Promoções (tipos, status, preço-alvo,
rebate, partes ML/vendedor, vigência) num painel único e legível, usando
a lib rich — para servir de referência visual antes de desenhar a tela
real.

Só leitura — nenhuma chamada de API.
"""

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

ARQUIVO = Path("Arquivos_API/amostra_promocoes.json")
MLB_ALVO = "MLB2690742181"  # troque aqui para ver outro MLB

console = Console()


def calcular_desconto_total(promo: dict) -> float | None:
    original = promo.get("original_price")
    preco = promo.get("price")
    if not original or preco is None:
        return None
    return (1 - preco / original) * 100


def montar_linha_rebate(promo: dict) -> str:
    meli = promo.get("meli_percentage")
    seller = promo.get("seller_percentage")
    if meli is None:
        return "[dim]— sem rebate —[/dim]"
    return f"[green]ML: {meli}%[/green]  /  [yellow]Você: {seller}%[/yellow]"


def montar_valor_rebate_reais(promo: dict) -> str:
    meli = promo.get("meli_percentage")
    original = promo.get("original_price")
    if meli is None or not original:
        return "-"
    valor = original * (meli / 100)
    return f"R$ {valor:.2f}"


def main():
    with open(ARQUIVO, encoding="utf-8") as f:
        dados = json.load(f)

    mlb_info = None
    for grupo in dados["fase2_grupos"]:
        for m in grupo["mlbs"]:
            if m["mlb"] == MLB_ALVO:
                mlb_info = m
                break

    if not mlb_info:
        console.print(f"[red]MLB {MLB_ALVO} não encontrado.[/red]")
        return

    resultado = mlb_info["promocoes"]
    if resultado.get("http") != 200:
        console.print(f"[red]Erro HTTP {resultado.get('http')} para este MLB.[/red]")
        return

    promocoes = resultado.get("dados") or []

    console.print()
    console.print(Panel(
        f"[bold]{MLB_ALVO}[/bold]\n"
        f"SKU: {mlb_info.get('sku') or '—'}\n"
        f"Total de promoções elegíveis/ativas: [bold]{len(promocoes)}[/bold]",
        title="🏷️  PAINEL DE PROMOÇÕES",
        box=box.DOUBLE,
        border_style="cyan",
    ))

    if not promocoes:
        console.print("[dim]Este anúncio não tem nenhuma promoção elegível.[/dim]\n")
        return

    com_rebate = [p for p in promocoes if p.get("meli_percentage") is not None]
    sem_rebate = [p for p in promocoes if p.get("meli_percentage") is None]

    # ── TABELA: COM REBATE ──────────────────────────────────────────
    if com_rebate:
        console.print()
        console.print("[bold green]💰 PROMOÇÕES COM REBATE DO ML[/bold green]")
        tabela = Table(box=box.ROUNDED, show_lines=True)
        tabela.add_column("Campanha", style="bold")
        tabela.add_column("Status")
        tabela.add_column("Preço Original", justify="right")
        tabela.add_column("Preço-Alvo", justify="right", style="bold cyan")
        tabela.add_column("Desconto Total", justify="right")
        tabela.add_column("Divisão do Rebate")
        tabela.add_column("ML paga (R$)", justify="right", style="green")

        for p in sorted(com_rebate, key=lambda x: x.get("meli_percentage", 0), reverse=True):
            status_cor = "[bold green]started[/bold green]" if p["status"] == "started" else "[yellow]candidate[/yellow]"
            desconto = calcular_desconto_total(p)
            desconto_str = f"{desconto:.1f}%" if desconto is not None else "-"

            tabela.add_row(
                p.get("type", "?"),
                status_cor,
                f"R$ {p.get('original_price', 0):.2f}",
                f"R$ {p.get('price', 0):.2f}",
                desconto_str,
                montar_linha_rebate(p),
                montar_valor_rebate_reais(p),
            )
        console.print(tabela)

        # Destaque: melhor oferta (maior % do ML)
        melhor = max(com_rebate, key=lambda x: x.get("meli_percentage", 0))
        console.print(Panel(
            f"[bold]Melhor oferta disponível (maior % bancado pelo ML):[/bold]\n"
            f"{melhor.get('type')} — ML paga {melhor.get('meli_percentage')}% "
            f"({montar_valor_rebate_reais(melhor)}) | Status: {melhor.get('status')}",
            border_style="green",
            box=box.SIMPLE,
        ))

    # ── TABELA: SEM REBATE ──────────────────────────────────────────
    if sem_rebate:
        console.print()
        console.print("[bold red]🚫 PROMOÇÕES SEM REBATE (desconto 100% seu)[/bold red]")
        tabela2 = Table(box=box.ROUNDED, show_lines=True)
        tabela2.add_column("Campanha", style="bold")
        tabela2.add_column("Status")
        tabela2.add_column("Preço Original", justify="right")
        tabela2.add_column("Preço Promocional", justify="right")
        tabela2.add_column("Vigência")

        for p in sem_rebate:
            status_cor = "[bold green]started[/bold green]" if p["status"] == "started" else "[yellow]candidate[/yellow]"
            preco = p.get("price")
            preco_str = f"R$ {preco:.2f}" if preco else "[dim](ainda não definido)[/dim]"

            vigencia = "-"
            if p.get("start_date"):
                vigencia = f"{p['start_date'][:10]} → {p.get('finish_date', '?')[:10]}"

            tabela2.add_row(
                p.get("type", "?"),
                status_cor,
                f"R$ {p.get('original_price', 0):.2f}",
                preco_str,
                vigencia,
            )
        console.print(tabela2)

    console.print()


if __name__ == "__main__":
    main()