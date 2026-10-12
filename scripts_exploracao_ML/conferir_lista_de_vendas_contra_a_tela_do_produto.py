# scripts_exploracao_ML/conferir_lista_de_vendas_contra_a_tela_do_produto.py
#
# Função Objetivo: CONFERIR, com o seu banco real, se a LISTA de vendas (lista_vendas_ml.py) mostra os MESMOS números que a tela do produto (vendas_ml.py) para cada SKU:
# unidades, pedidos, faturamento, Full e fora do Full (e, dentro do SKU, as unidades de cada MLB). A lista calcula tudo de uma vez para ~1000 SKUs (sem consulta por SKU); a tela
# do produto calcula um SKU de cada vez. As regras são as mesmas, então os números têm que bater. Se um SKU não bater, o script mostra QUAL número difere.
#
# O QUE O SCRIPT FAZ (só leitura: SELECT; NENHUMA chamada ao Mercado Livre; nada é gravado no banco):
#   1) Calcula a lista inteira UMA vez para o período escolhido (a mesma conta que a tela usa).
#   2) Escolhe uma amostra de SKUs: os mais vendidos, alguns aleatórios com venda, alguns sem venda e os SKUs que você listar em SKUS_EXTRAS.
#   3) Para cada SKU da amostra, abre a tela do produto (nível "Produto") e compara com a linha da lista.
#   4) Confere também a soma da lista toda: a soma das linhas de SKU tem que ser igual à soma das linhas de MLB e à de Código ML (as 3 visões contam as MESMAS vendas).
#   5) Guarda tudo em JSON (scripts_exploracao_ML/exploracao_conferencia_da_lista_de_vendas_<CONTA>.json, sobrescrito a cada execução).
#
# COMO LER O RESULTADO: "OK" = o número da lista é igual ao da tela do produto. "DIFERE" = números diferentes: o caso típico é um MLB que serve a mais de um SKU e vendeu SEM
# seller_sku no pedido (a lista não adivinha o SKU; a tela do produto pode atribuir). "Média/dia" e "vs. anterior" NÃO são conferidos aqui de propósito: a lista usa a cobertura da
# CONTA TODA e a tela do produto usa a cobertura daquele produto (pode ser diferente se você atualizou produtos sozinhos). Só as UNIDADES somadas têm que bater sempre.
#
# * [EXPLICAÇÃO] → A tela do produto mostra o faturamento com centavos e a lista arredondado em reais: aqui os dois são comparados em centavos, a partir dos valores calculados (não dos textos da lista).

import json
import os
import random
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, "manage.py")):
            sys.path.insert(0, caminho_atual)
            return caminho_atual
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError("Não foi possível encontrar manage.py subindo a partir deste script.")


_RAIZ_DO_PROJETO = Path(_adicionar_raiz_do_projeto_ao_path())

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "projeto_sistema_interno_mb_sv.settings")
django.setup()

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from gestao_vendas.funcoes_auxiliares import lista_vendas_ml as lista
from gestao_vendas.funcoes_auxiliares import vendas_ml as tela

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale): decide o banco
PERIODO = "3meses"                    # semana | mes | 3meses | 6meses | ano
QUANTOS_DOS_MAIS_VENDIDOS = 15        # os SKUs que mais venderam no período
QUANTOS_ALEATORIOS_COM_VENDA = 15     # SKUs com venda sorteados entre os demais
QUANTOS_SEM_VENDA = 3                 # SKUs sem nenhuma venda no período (a tela do produto também tem que dizer 0)
SKUS_EXTRAS = []                      # SKUs que você quer conferir de qualquer jeito, ex.: ["ABC123"]
SEMENTE_DO_SORTEIO = 12               # mesma semente = mesma amostra
LINHAS_COM_DIFERENCA_NA_TELA = 25     # quantas diferenças mostrar na tela (o JSON leva todas)
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

FUSO = ZoneInfo("America/Sao_Paulo")
console = Console()
CAMINHO_JSON = Path(__file__).resolve().parent / f"exploracao_conferencia_da_lista_de_vendas_{CONTA}.json"


# Função Objetivo: Texto do Brasil ("R$ 8.800,00", "1.234", "61") → Decimal. Só para os números positivos da tela do produto.
def _numero_br(texto):
    limpo = re.sub(r"[^0-9,]", "", str(texto or "")).replace(",", ".")
    return Decimal(limpo) if limpo not in ("", ".") else Decimal("0")


def _celula_de_origem(produto, chave):
    return next((l for l in produto["tabela_origem"] if l["chave"] == chave), None)


# Função Objetivo: Compara a linha da lista de UM SKU com a tela do produto. Devolve (lista de diferenças em texto, dados para o JSON).
def _conferir_sku(sku, linha, calc, hoje):
    produto = tela.montar_vendas(sku, PERIODO, "produto", "", hoje, lambda **p: tela.url_da_tela("/vendas/", **p))
    m = linha["m"] if linha else {"un": 0, "ped": 0, "fat": Decimal("0"), "fu": 0, "fo": 0}
    cartao_un = next(c for c in produto["cartoes"] if c["rotulo"] == "Unidades vendidas")
    total = produto["tabela_origem_total"]
    full, fora = _celula_de_origem(produto, "full"), _celula_de_origem(produto, "fora")
    na_tela = {
        "un": int(_numero_br(cartao_un["valor"])), "ped": int(_numero_br(total["pedidos"])), "fat": _numero_br(total["fat"]),
        "fu": int(_numero_br(full["un"])) if full else 0, "fo": int(_numero_br(fora["un"])) if fora else 0,
    }
    na_lista = {"un": m["un"], "ped": m["ped"], "fat": Decimal(m["fat"]), "fu": m["fu"], "fo": m["fo"]}
    diferencas = []
    nomes = {"un": "unidades", "ped": "pedidos", "fat": "faturamento", "fu": "Full", "fo": "fora do Full"}
    for chave, nome in nomes.items():
        igual = abs(na_lista[chave] - na_tela[chave]) < Decimal("0.01") if chave == "fat" else na_lista[chave] == na_tela[chave]
        if not igual:
            diferencas.append(f"{nome}: lista {na_lista[chave]} × tela {na_tela[chave]}")
    # por MLB (só os que venderam): unidades da lista (linhas do SKU) × tabela "Por MLB" da tela
    por_mlb_lista = {}
    for mlb, qtd, *_ in calc["linhas_do_sku"].get(sku, []):
        por_mlb_lista[mlb] = por_mlb_lista.get(mlb, 0) + qtd
    por_mlb_tela = {l["mlb"]: int(_numero_br(l["un"])) for l in produto["tabela_mlb"] if _numero_br(l["un"]) > 0}
    for mlb in sorted(set(por_mlb_lista) | set(por_mlb_tela)):
        a, b = por_mlb_lista.get(mlb, 0), por_mlb_tela.get(mlb, 0)
        if a != b:
            diferencas.append(f"{mlb}: lista {a} × tela {b}")
    dados = {"sku": sku, "lista": {k: str(v) for k, v in na_lista.items()}, "tela": {k: str(v) for k, v in na_tela.items()}, "mlbs_lista": por_mlb_lista,
             "mlbs_tela": por_mlb_tela, "diferencas": diferencas}
    return diferencas, dados


def main():
    hoje = datetime.now(FUSO).date()
    console.print(f"[bold]Conferência da lista de vendas × tela do produto[/bold] · conta {CONTA} · período {PERIODO} · hoje {hoje:%d/%m/%Y}")
    calc = lista._calcular(PERIODO, hoje)
    linhas_sku = lista._linhas_de_sku(calc)
    linhas_mlb = lista._linhas_de_mlb(calc)
    linhas_cod = lista._linhas_de_codigo(calc)
    por_chave = {l["chave"]: l for l in linhas_sku}

    # ---- 1) as 3 visões contam as mesmas vendas? (e batem com a soma direta do banco) ----
    from django.db.models import Sum
    from mercado_livre.models import VendaItemMercadoLivre

    direto = (VendaItemMercadoLivre.objects.filter(dia_venda__range=(calc["de"], hoje)).exclude(status=lista.STATUS_CANCELADO)
              .aggregate(t=Sum("quantidade"))["t"] or 0)
    somas = {"SKU": sum(l["m"]["un"] for l in linhas_sku), "MLB": sum(l["m"]["un"] for l in linhas_mlb), "Código ML": sum(l["m"]["un"] for l in linhas_cod)}
    tabela = Table(title="Soma das unidades do período", box=box.SIMPLE_HEAD)
    tabela.add_column("Fonte")
    tabela.add_column("Unidades", justify="right")
    tabela.add_column("Resultado")
    tabela.add_row("Soma direta no banco (sem cancelados)", f"{direto:,}".replace(",", "."), "referência")
    for nome, valor in somas.items():
        tabela.add_row(f"Lista por {nome}", f"{valor:,}".replace(",", "."), "[green]OK[/green]" if valor == direto else "[red]DIFERE[/red]")
    console.print(tabela)

    # ---- 2) amostra de SKUs ----
    reais = [l for l in linhas_sku if l["chave"] != lista.SEM_CADASTRO]
    com_venda = sorted((l for l in reais if l["m"]["un"] > 0), key=lambda l: (-l["m"]["un"], l["chave"]))
    sem_venda = sorted(l["chave"] for l in reais if l["m"]["un"] == 0)
    mais_vendidos = [l["chave"] for l in com_venda[:QUANTOS_DOS_MAIS_VENDIDOS]]
    resto = [l["chave"] for l in com_venda[QUANTOS_DOS_MAIS_VENDIDOS:]]
    random.Random(SEMENTE_DO_SORTEIO).shuffle(resto)
    amostra = list(dict.fromkeys(mais_vendidos + resto[:QUANTOS_ALEATORIOS_COM_VENDA] + sem_venda[:QUANTOS_SEM_VENDA] + list(SKUS_EXTRAS)))
    console.print(f"\nAmostra: {len(amostra)} SKUs ({len(mais_vendidos)} mais vendidos, {min(len(resto), QUANTOS_ALEATORIOS_COM_VENDA)} sorteados, {min(len(sem_venda), QUANTOS_SEM_VENDA)} sem venda, {len(SKUS_EXTRAS)} extras)")

    # ---- 3) SKU por SKU ----
    resultados, com_diferenca = [], []
    for i, sku in enumerate(amostra, 1):
        console.print(f"  [{i}/{len(amostra)}] {escape(sku)}", end="\r")
        diferencas, dados = _conferir_sku(sku, por_chave.get(sku), calc, hoje)
        resultados.append(dados)
        if diferencas:
            com_diferenca.append(dados)
    console.print(" " * 60, end="\r")
    ok = len(resultados) - len(com_diferenca)
    console.print(f"[bold]SKUs conferidos:[/bold] {len(resultados)} · [green]iguais: {ok}[/green] · [red]com diferença: {len(com_diferenca)}[/red]")
    if com_diferenca:
        t = Table(title="SKUs com diferença", box=box.SIMPLE_HEAD)
        t.add_column("SKU")
        t.add_column("O que difere")
        for d in com_diferenca[:LINHAS_COM_DIFERENCA_NA_TELA]:
            t.add_row(escape(d["sku"]), escape(" · ".join(d["diferencas"])))
        console.print(t)
        console.print("Dica: diferença só em MLB/SKU quase sempre é um MLB que serve a mais de um SKU e vendeu sem seller_sku no pedido.")

    sem_cadastro = por_chave.get(lista.SEM_CADASTRO)
    if sem_cadastro:
        console.print(f"\nLinha 'Sem cadastro' da lista: {sem_cadastro['m']['un']} un (vendas que não dá para ligar a nenhum SKU).")
    CAMINHO_JSON.write_text(json.dumps({"conta": CONTA, "periodo": PERIODO, "hoje": str(hoje), "soma_direta": direto, "somas": somas, "sem_cadastro_un": sem_cadastro["m"]["un"] if sem_cadastro else 0,
                                        "skus": resultados}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"JSON salvo em {CAMINHO_JSON.name}")


if __name__ == "__main__":
    main()
