# scripts_exploracao_ML/comparar_vendas_com_relatorio_de_elasticidade_da_magiic.py
#
# Função Objetivo: COMPARAR, número a número, as vendas do nosso banco com o "Relatório de Elasticidade" da Magiic (o HTML que o Matheus mandou em 12/10/2026,
# filtrado pelo SKU de teste). O relatório traz as vendas de cada anúncio em janelas de 30 dias que andam para trás a partir do momento em que a página foi aberta:
# "30/0" (os últimos 30 dias), "60/30" (os 30 dias antes desses) e "90/60". Em cada janela a Magiic mostra Vendas R$, unidades, pedidos e o preço médio.
#
# O script responde 3 perguntas, nesta ordem:
#   1) ENCAIXE DAS JANELAS: com que data e a que horas a Magiic "cortou" as janelas? O script testa cortes de 15 em 15 minutos (de 11/10 às 00:00 até 12/10 às 12:00),
#      com a data de CRIAÇÃO do pedido ou a de FECHAMENTO, contando "sem cancelados" ou "só paid", e mostra quais cortes reproduzem as unidades e os pedidos da Magiic.
#   2) JANELA POR JANELA: para cada família de anúncios (anúncio + filho de catálogo, como a Magiic agrupa) e cada janela, compara unidades, pedidos e R$ da Magiic com os nossos.
#   3) O QUE EXPLICA A DIFERENÇA EM R$: a Magiic mostra DUAS contas de dinheiro no mesmo relatório: "Vendas R$" e "Preço médio". O script testa se o NOSSO faturamento
#      (preço × unidades) bate com "preço médio × unidades" da Magiic (e só o "Vendas R$" dela tem um acréscimo) e mostra, nas janelas com acréscimo, as nossas linhas.
#
# REGRAS: SÓ LEITURA e SÓ BANCO. Nenhuma chamada ao Mercado Livre, nada é gravado no banco. O JSON de saída (sem dado de comprador: o banco nem guarda) é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → Por que o script usa as MESMAS funções da tela (carregar_produto e _carregar_linhas, de vendas_ml): assim as linhas lidas são exatamente as da tela
#                  (SKU do pedido ou, sem SKU, MLB do produto). O script imprime os totais do período inteiro ao lado dos da tela (3.182 un · 3.175 pedidos · R$ 1.181.994,27)
#                  para você ver, antes de qualquer comparação, que ele leu o mesmo conjunto de vendas.
# * [EXPLICAÇÃO] → Os números da Magiic estão escritos aqui dentro (MAGIIC_TOTAIS e MAGIIC_ANUNCIOS), copiados do HTML; as famílias (anúncio + catálogo) vêm da tela Radar de
#                  Vendas da Magiic ("Principal — MLB… / Catálogo — MLB…"). A Magiic soma o catálogo dentro do anúncio de origem; por isso a comparação é por FAMÍLIA, não por MLB.
# * [EXPLICAÇÃO] → O banco não guarda total_amount, paid_amount nem frete do pedido: guarda unit_price e sale_fee do item. Se o acréscimo do "Vendas R$" da Magiic for
#                  dinheiro que o comprador pagou além do preço do produto (juros de parcelamento, frete), o script só consegue dizer ONDE ele está (qual família e qual janela),
#                  não O QUE é. Esse "o quê" só se vê no pedido do Mercado Livre.

import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
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
from gestao_vendas.funcoes_auxiliares.vendas_ml import STATUS_CANCELADO, _carregar_linhas, carregar_produto

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                                       # "MB" (Magazine) ou "SV" (Samvale): decide o banco
SKU = "F7908050719121.001"                         # o produto do relatório da Magiic
DATA_INICIAL = date(2026, 7, 11)                   # o mesmo período da tela (Últimos 3 meses de 11/10/2026)
DATA_FINAL = date(2026, 10, 11)
CORTE_DE = datetime(2026, 10, 11, 0, 0)            # primeiro corte testado (horário de Brasília): o relatório foi aberto em 11/10 (há dados dele de 18:58 desse dia)
CORTE_ATE = datetime(2026, 10, 12, 12, 0)          # último corte testado (a página pode ter sido salva depois da meia-noite)
PASSO_DO_CORTE_EM_MINUTOS = 15
LINHAS_NA_LISTA = 40                               # janela com até tantas linhas: lista todas na tela; com mais: só o resumo por preço
LINHAS_POR_JANELA_NO_JSON = 300                    # no JSON, cada janela com acréscimo leva até tantas linhas (as mais antigas primeiro) e diz o total
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_comparacao_com_elasticidade_da_magiic_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

# O que a TELA mostrou em 11/10/2026 às 21:09 para este produto no período 11/07 a 11/10 (para conferir que o script leu o mesmo conjunto de vendas).
TELA_UNIDADES, TELA_PEDIDOS, TELA_FATURAMENTO = 3182, 3175, Decimal("1181994.27")

# Janelas do relatório. A janela k vai de (corte − 30·(k+1) dias) até (corte − 30·k dias).
JANELAS = ("30/0", "60/30", "90/60")

# Linha "Totais" do relatório (todos os anúncios do SKU): (Vendas R$, unidades, pedidos).
MAGIIC_TOTAIS = {"30/0": (Decimal("353263.91"), 934, 931), "60/30": (Decimal("431956.03"), 1163, 1162), "90/60": (Decimal("357776.45"), 968, 965)}

# Cada anúncio do relatório, nas 3 janelas (na ordem de JANELAS): (Vendas R$, unidades, pedidos, preço médio). O relatório já soma o filho de catálogo no anúncio de origem.
MAGIIC_ANUNCIOS = {
    "MLB1942167064": [(299385.31, 796, 796, 375.21), (361247.30, 980, 980, 367.06), (342940.15, 932, 932, 366.38)],
    "MLB7574006382": [(29258.67, 76, 76, 383.55), (54454.74, 143, 143, 379.38), (0.00, 0, 0, 0.00)],
    "MLB5838465508": [(16085.10, 42, 42, 382.98), (11100.50, 28, 28, 396.45), (5333.72, 13, 13, 410.29)],
    "MLB2616936722": [(2716.51, 6, 6, 452.75), (0.00, 0, 0, 0.00), (1098.00, 3, 3, 366.00)],
    "MLB4479357333": [(2594.66, 6, 5, 432.44), (2235.00, 5, 5, 447.00), (0.00, 0, 0, 0.00)],
    "MLB4232612385": [(1576.96, 4, 2, 394.24), (0.00, 0, 0, 0.00), (2108.48, 5, 5, 421.70)],
    "MLB1683028746": [(1199.70, 3, 3, 399.90), (1302.69, 3, 3, 419.90), (2497.80, 6, 6, 416.30)],
    "MLB4242628323": [(447.00, 1, 1, 447.00), (829.80, 2, 2, 414.90), (2904.30, 7, 4, 414.90)],
    "MLB4479431831": [(0.00, 0, 0, 0.00), (786.00, 2, 1, 393.00), (894.00, 2, 2, 447.00)],
}

# Anúncio de origem → filhos de catálogo que a Magiic soma nele (da tela Radar de Vendas: "Principal — … / Catálogo — …").
FAMILIAS = {
    "MLB1942167064": ("MLB3346875129",), "MLB4479431831": ("MLB4479289263",), "MLB1683028746": ("MLB5593532940",),
    "MLB4232612385": ("MLB6434019392",), "MLB4242628323": ("MLB6804270586",), "MLB4479357333": ("MLB4479474011",),
}
FILHO_PARA_PAI = {filho: pai for pai, filhos in FAMILIAS.items() for filho in filhos}

# As 4 formas de contar que o script testa no encaixe: (rótulo, campo da data, regra do status).
VARIANTES = (
    ("criação do pedido · sem cancelados", "criado", "sem_cancelados"),
    ("criação do pedido · só paid", "criado", "so_paid"),
    ("fechamento do pedido · sem cancelados", "fechado", "sem_cancelados"),
    ("fechamento do pedido · só paid", "fechado", "so_paid"),
)

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))
t = escape


# ============================== utilitários ==============================

def n(valor):
    return f"{valor:,}".replace(",", ".")


def reais(valor):
    texto = f"{Decimal(valor):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def reais_com_sinal(valor):
    valor = Decimal(valor)
    return ("+" if valor > 0 else "") + reais(valor) if valor != 0 else "R$ 0,00"


def com_sinal(valor):
    return f"+{valor}" if valor > 0 else str(valor)


def quando(instante):
    return instante.strftime("%d/%m %H:%M")


def dec(valor):
    return Decimal(str(valor))


def arredondamento_do_preco_medio(unidades):
    """O preço médio da Magiic vem com 2 casas: multiplicado pelas unidades, pode errar até R$ 0,005 por unidade (mais R$ 0,01 de folga)."""
    return Decimal("0.005") * unidades + Decimal("0.01")


def tem_acrescimo(r):
    """O 'Vendas R$' da Magiic passa do 'preço médio × unidades' dela por mais que o arredondamento."""
    return r["magiic"]["acrescimo"] > arredondamento_do_preco_medio(r["magiic"]["un"])


def tem_diferenca_de_dinheiro(r):
    return abs(r["dif"]["fat"]) > Decimal("0.005")


def nova_tabela(titulo, *colunas):
    """Cada coluna é (nome, alinhamento) ou (nome, alinhamento, 'inteira'): 'inteira' nunca quebra a linha (MLB, datas)."""
    tabela = Table(title=titulo, title_justify="left", box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
    for coluna in colunas:
        tabela.add_column(coluna[0], justify=coluna[1], overflow="fold", no_wrap=len(coluna) > 2)
    return tabela


# ============================== leitura do banco ==============================

def ler_linhas():
    """As linhas de venda do SKU no período (a MESMA seleção da tela), já com o instante em Brasília. Só SELECT."""
    produto = carregar_produto(SKU)
    if produto is None:
        return None, []
    brutas = _carregar_linhas(SKU, list(produto["mlbs"]), DATA_INICIAL, DATA_FINAL,
                              extras=("criado_em_ml", "fechado_em_ml", "taxa_venda", "pack_id", "atualizado_em"))
    linhas = []
    for l in brutas:
        criado = l["criado_em_ml"].astimezone(FUSO)
        linhas.append({
            "pedido": l["order_id"], "mlb": l["mlb"], "familia": FILHO_PARA_PAI.get(l["mlb"], l["mlb"]), "qtd": l["quantidade"], "preco": l["preco_unitario"],
            "status": l["status"], "criado": criado, "fechado": (l["fechado_em_ml"].astimezone(FUSO) if l["fechado_em_ml"] else criado),
            "desconto": bool(l["com_desconto"]), "catalogo": bool(l["catalogo"]), "taxa": l["taxa_venda"], "pack": l["pack_id"],
            "lido_em": l["atualizado_em"].astimezone(FUSO),
        })
    return produto, linhas


def vale(linha, regra):
    return linha["status"] != STATUS_CANCELADO if regra == "sem_cancelados" else linha["status"] == "paid"


def somar(linhas):
    """Unidades, pedidos distintos e faturamento (preço × unidades; linha sem preço fica fora e é contada)."""
    pedidos, unidades, faturamento, sem_preco = set(), 0, Decimal("0"), 0
    for l in linhas:
        pedidos.add(l["pedido"])
        unidades += l["qtd"]
        if l["preco"] is None:
            sem_preco += l["qtd"]
        else:
            faturamento += l["preco"] * l["qtd"]
    return {"un": unidades, "pedidos": len(pedidos), "fat": faturamento, "sem_preco": sem_preco}


# ============================== 1) o encaixe das janelas ==============================

def janelas_do_corte(corte):
    return [(corte - timedelta(days=30 * (k + 1)), corte - timedelta(days=30 * k)) for k in range(3)]


def linhas_por_janela(linhas, campo, regra, corte):
    """[linhas da janela 30/0, da 60/30, da 90/60]. A janela é aberta no começo e fechada no fim: (início, fim]."""
    por_janela = [[], [], []]
    janelas = janelas_do_corte(corte)
    for l in linhas:
        if not vale(l, regra):
            continue
        for k, (inicio, fim) in enumerate(janelas):
            if inicio < l[campo] <= fim:
                por_janela[k].append(l)
                break
    return por_janela


def testar_os_cortes(linhas):
    """Para cada variante, cada corte → (unidades por janela, pedidos por janela). Junta cortes seguidos que dão o mesmo resultado numa faixa de horário."""
    cortes, atual = [], CORTE_DE.replace(tzinfo=FUSO)
    fim = CORTE_ATE.replace(tzinfo=FUSO)
    while atual <= fim:
        cortes.append(atual)
        atual += timedelta(minutes=PASSO_DO_CORTE_EM_MINUTOS)
    alvo_un = [MAGIIC_TOTAIS[j][1] for j in JANELAS]
    alvo_ped = [MAGIIC_TOTAIS[j][2] for j in JANELAS]
    faixas = []
    for indice, (rotulo, campo, regra) in enumerate(VARIANTES):
        anterior = None
        for corte in cortes:
            grupos = linhas_por_janela(linhas, campo, regra, corte)
            un = tuple(sum(l["qtd"] for l in g) for g in grupos)
            ped = tuple(len({l["pedido"] for l in g}) for g in grupos)
            if (un, ped) == anterior:
                faixas[-1]["fim"] = corte
                continue
            anterior = (un, ped)
            score = sum(abs(a - b) for a, b in zip(un, alvo_un)) + sum(abs(a - b) for a, b in zip(ped, alvo_ped))
            faixas.append({"variante": indice, "rotulo": rotulo, "campo": campo, "regra": regra, "inicio": corte, "fim": corte, "un": un, "ped": ped, "score": score})
    faixas.sort(key=lambda f: (f["score"], f["variante"], f["inicio"]))
    return faixas


def mostrar_o_encaixe(faixas):
    console.rule("[bold]1) Encaixe das janelas: em que horário a Magiic cortou?")
    alvo_un = " · ".join(n(MAGIIC_TOTAIS[j][1]) for j in JANELAS)
    alvo_ped = " · ".join(n(MAGIIC_TOTAIS[j][2]) for j in JANELAS)
    console.print(f"Alvo da Magiic (janelas {' · '.join(JANELAS)}): unidades {alvo_un} · pedidos {alvo_ped}\n")
    tabela = nova_tabela("Melhores encaixes (menor diferença primeiro)", ("Como contei", "left"), ("Corte entre", "left"), ("Unidades", "right"), ("Pedidos", "right"), ("Diferença", "right"))
    for f in faixas[:8]:
        faixa = quando(f["inicio"]) if f["inicio"] == f["fim"] else f"{quando(f['inicio'])} e {quando(f['fim'])}"
        tabela.add_row(f["rotulo"], faixa, " · ".join(n(x) for x in f["un"]), " · ".join(n(x) for x in f["ped"]),
                       "[green]EXATO[/]" if f["score"] == 0 else str(f["score"]))
    console.print(tabela)
    melhor = faixas[0]
    if melhor["score"] == 0:
        console.print(f"[green]As 3 janelas da Magiic se reproduzem EXATAMENTE[/] ({t(melhor['rotulo'])}, corte entre {quando(melhor['inicio'])} e {quando(melhor['fim'])}). "
                      f"Daqui em diante o script usa esse corte ({quando(melhor['inicio'])}).\n")
    else:
        console.print(f"[yellow]Nenhum corte reproduziu as 3 janelas por inteiro.[/] O melhor ({t(melhor['rotulo'])}, corte {quando(melhor['inicio'])}) fica a {melhor['score']} "
                      f"de distância (unidades + pedidos somados nas 3 janelas). Daqui em diante o script usa esse corte.\n")


# ============================== 2) janela por janela, por família ==============================

def comparar_por_familia(linhas, melhor):
    por_janela = linhas_por_janela(linhas, melhor["campo"], melhor["regra"], melhor["inicio"])
    nossas = {}
    for k, grupo in enumerate(por_janela):
        por_familia = defaultdict(list)
        for l in grupo:
            por_familia[l["familia"]].append(l)
        for familia, ls in por_familia.items():
            nossas[(familia, k)] = {"linhas": ls, **somar(ls)}
    familias = sorted(set(MAGIIC_ANUNCIOS) | {f for f, _ in nossas})
    linhas_da_tabela = []
    for familia in familias:
        for k in range(3):
            fat_m, un_m, ped_m, pm_m = MAGIIC_ANUNCIOS.get(familia, [(0, 0, 0, 0)] * 3)[k]
            nos = nossas.get((familia, k), {"linhas": [], "un": 0, "pedidos": 0, "fat": Decimal("0"), "sem_preco": 0})
            if not (fat_m or un_m or nos["un"]):
                continue
            fat_m, pm_m = dec(fat_m), dec(pm_m)
            linhas_da_tabela.append({
                "familia": familia, "janela": JANELAS[k], "k": k,
                "magiic": {"fat": fat_m, "un": un_m, "pedidos": ped_m, "preco_medio": pm_m, "preco_medio_x_un": pm_m * un_m, "acrescimo": fat_m - pm_m * un_m},
                "nos": {"fat": nos["fat"], "un": nos["un"], "pedidos": nos["pedidos"], "sem_preco": nos["sem_preco"]},
                "dif": {"un": nos["un"] - un_m, "pedidos": nos["pedidos"] - ped_m, "fat": nos["fat"] - fat_m, "nos_menos_preco_medio_x_un": nos["fat"] - pm_m * un_m},
                "linhas": nos["linhas"],
            })
    return linhas_da_tabela


def bate_tudo(r):
    return r["dif"]["un"] == 0 and r["dif"]["pedidos"] == 0 and abs(r["dif"]["fat"]) <= Decimal("0.005")


def mostrar_conferencia_da_leitura(linhas):
    todas = [l for l in linhas if l["status"] != STATUS_CANCELADO]
    s = somar(todas)
    console.rule("[bold]0) Conferência: o script leu as mesmas vendas da tela?")
    tabela = nova_tabela(None, ("", "left"), ("Unidades", "right"), ("Pedidos", "right"), ("Faturamento", "right"))
    tabela.add_row("Tela (11/10 às 21:09)", n(TELA_UNIDADES), n(TELA_PEDIDOS), reais(TELA_FATURAMENTO))
    tabela.add_row("Este script (sem cancelados)", n(s["un"]), n(s["pedidos"]), reais(s["fat"]))
    console.print(tabela)
    igual = (s["un"], s["pedidos"], s["fat"]) == (TELA_UNIDADES, TELA_PEDIDOS, TELA_FATURAMENTO)
    console.print("[green]Idêntico à tela.[/]" if igual else
                  "[yellow]Diferente da tela: se você coletou mais vendas depois das 21:09 ou mudou o período, é esperado; senão, avise.[/]")
    fechou_em_outro_dia = sum(1 for l in todas if l["fechado"].date() != l["criado"].date())
    console.print(f"[dim]{n(fechou_em_outro_dia)} de {n(len(todas))} linhas fecharam em um dia diferente do dia da criação do pedido. "
                  f"{n(sum(1 for l in linhas if l['status'] == STATUS_CANCELADO))} linhas canceladas ficaram fora.[/]\n")
    return s


def mostrar_janela_por_janela(tabela_dados):
    console.rule("[bold]2) Janela por janela, por anúncio (a Magiic soma o catálogo no anúncio de origem)")
    diferentes = [r for r in tabela_dados if not bate_tudo(r)]
    iguais = len(tabela_dados) - len(diferentes)
    console.print(f"{n(iguais)} de {n(len(tabela_dados))} combinações anúncio × janela batem em tudo (unidades, pedidos e R$ ao centavo). Só as {n(len(diferentes))} que divergem aparecem abaixo.\n")
    if not diferentes:
        return
    em_unidades = [r for r in diferentes if r["dif"]["un"] or r["dif"]["pedidos"]]
    if em_unidades:
        tabela = nova_tabela("Unidades e pedidos que divergem (M = Magiic · N = nosso banco)", ("Anúncio", "left", "inteira"), ("Janela", "left", "inteira"),
                             ("Un M", "right"), ("Un N", "right"), ("Pedidos M", "right"), ("Pedidos N", "right"))
        for r in em_unidades:
            m, nn = r["magiic"], r["nos"]
            tabela.add_row(r["familia"], r["janela"], n(m["un"]), n(nn["un"]), n(m["pedidos"]), n(nn["pedidos"]))
        console.print(tabela)
        console.print()
    em_dinheiro = [r for r in diferentes if tem_diferenca_de_dinheiro(r) or tem_acrescimo(r)]
    if em_dinheiro:
        tabela = nova_tabela("Dinheiro que diverge (PM = preço médio que a Magiic mostra)", ("Anúncio", "left", "inteira"), ("Janela", "left", "inteira"),
                             ("R$ Magiic", "right"), ("R$ nosso", "right"), ("Nosso − Magiic", "right"), ("Magiic: PM × un", "right"), ("Nosso − PM × un", "right"))
        for r in em_dinheiro:
            m, nn, d = r["magiic"], r["nos"], r["dif"]
            tabela.add_row(r["familia"], r["janela"], reais(m["fat"]), reais(nn["fat"]), reais_com_sinal(d["fat"]), reais(m["preco_medio_x_un"]), reais_com_sinal(d["nos_menos_preco_medio_x_un"]))
        console.print(tabela)
        console.print()


def mostrar_totais_em_reais(tabela_dados):
    console.rule("[bold]3) O dinheiro: 'Vendas R$' da Magiic × 'preço médio × unidades' da Magiic × o nosso")
    tabela = nova_tabela("Soma dos anúncios do relatório, por janela (PM = preço médio da Magiic)", ("Janela", "left", "inteira"), ("Magiic: Vendas R$", "right"),
                         ("Magiic: PM × un", "right"), ("Nosso banco", "right"), ("Nosso − Vendas", "right"), ("Nosso − PM × un", "right"))
    total = {"v": Decimal("0"), "p": Decimal("0"), "n": Decimal("0")}
    for k, janela in enumerate(JANELAS):
        linhas = [r for r in tabela_dados if r["k"] == k]
        v = sum((r["magiic"]["fat"] for r in linhas), Decimal("0"))
        p = sum((r["magiic"]["preco_medio_x_un"] for r in linhas), Decimal("0"))
        nos = sum((r["nos"]["fat"] for r in linhas), Decimal("0"))
        tabela.add_row(janela, reais(v), reais(p), reais(nos), reais_com_sinal(nos - v), reais_com_sinal(nos - p))
        total["v"] += v
        total["p"] += p
        total["n"] += nos
    tabela.add_row("[bold]Total", reais(total["v"]), reais(total["p"]), reais(total["n"]), reais_com_sinal(total["n"] - total["v"]), reais_com_sinal(total["n"] - total["p"]))
    console.print(tabela)
    console.print(f"[dim]Conferência da linha 'Totais' do relatório: Vendas R$ das 3 janelas = {reais(sum(v[0] for v in MAGIIC_TOTAIS.values()))}. "
                  f"O preço médio da Magiic vem com 2 casas, então 'preço médio × un' pode errar uns poucos reais por anúncio.[/]\n")
    return total


# ============================== o que há nas janelas com acréscimo ==============================

def mostrar_janelas_com_acrescimo(tabela_dados):
    com_acrescimo = [r for r in tabela_dados if tem_acrescimo(r) or tem_diferenca_de_dinheiro(r)]
    console.rule("[bold]4) Janelas em que o 'Vendas R$' da Magiic passa do 'preço médio × un' dela ou do nosso banco")
    if not com_acrescimo:
        console.print("Nenhuma: nesta comparação o dinheiro bate.\n")
        return []
    console.print("Acréscimo da Magiic = Vendas R$ − (preço médio × unidades), os dois mostrados por ela mesma no relatório.\n")
    resumo = []
    for r in com_acrescimo:
        m, nn, d = r["magiic"], r["nos"], r["dif"]
        ls = r["linhas"]
        un = nn["un"]
        console.print(f"[bold]{r['familia']} · janela {r['janela']}[/] — Magiic: Vendas {reais(m['fat'])}, {n(m['un'])} un, preço médio {reais(m['preco_medio'])} · "
                      f"acréscimo [bold]{reais_com_sinal(m['acrescimo'])}[/]" + (f" ({reais_com_sinal(m['acrescimo'] / m['un'])} por unidade)" if m["un"] else ""))
        console.print(f"   Nosso banco: {reais(nn['fat'])}, {n(un)} un, {n(nn['pedidos'])} pedidos · nosso − Vendas da Magiic = {reais_com_sinal(d['fat'])} · "
                      f"nosso − (preço médio × un) = {reais_com_sinal(d['nos_menos_preco_medio_x_un'])}")
        com_desconto = sum(l["qtd"] for l in ls if l["desconto"])
        de_catalogo = sum(l["qtd"] for l in ls if l["catalogo"])
        em_pack = len({l["pedido"] for l in ls if l["pack"]})
        taxa = sum((l["taxa"] or Decimal("0")) * l["qtd"] for l in ls)
        lidos = [l["lido_em"] for l in ls]
        console.print(f"   Nas nossas linhas: {n(com_desconto)} un com tag de desconto · {n(de_catalogo)} un de venda por catálogo · {n(em_pack)} pedidos em carrinho (pack) · "
                      f"taxa de venda somada {reais(taxa)}" + (f" · linhas lidas pela última vez entre {quando(min(lidos))} e {quando(max(lidos))}" if lidos else ""))
        if len(ls) <= LINHAS_NA_LISTA:
            tabela = nova_tabela(None, ("Pedido", "right", "inteira"), ("Criado", "left", "inteira"), ("Fechado", "left", "inteira"), ("Status", "left", "inteira"),
                                 ("MLB", "left", "inteira"), ("Qtd", "right", "inteira"), ("Preço un.", "right"), ("Desc.", "center", "inteira"), ("Catál.", "center", "inteira"))
            for l in sorted(ls, key=lambda x: x["criado"]):
                tabela.add_row(str(l["pedido"]), quando(l["criado"]), quando(l["fechado"]), l["status"], l["mlb"], str(l["qtd"]),
                               reais(l["preco"]) if l["preco"] is not None else "(sem preço)", "S" if l["desconto"] else "-", "S" if l["catalogo"] else "-")
            console.print(tabela)
        else:
            por_preco = Counter()
            for l in ls:
                por_preco[l["preco"]] += l["qtd"]
            tabela = nova_tabela(f"{n(len(ls))} linhas: resumo por preço unitário (os {min(8, len(por_preco))} preços com mais unidades de {n(len(por_preco))})",
                                 ("Preço un.", "right"), ("Unidades", "right"), ("% das un", "right"))
            for preco, q in por_preco.most_common(8):
                tabela.add_row(reais(preco) if preco is not None else "(sem preço)", n(q), f"{q / un * 100:.1f}%".replace(".", ",") if un else "-")
            console.print(tabela)
        console.print()
        resumo.append(r)
    return resumo


# ============================== leitura e JSON ==============================

def montar_leitura(faixas, tabela_dados, totais_reais):
    melhor = faixas[0]
    linhas = []
    if melhor["score"] == 0:
        linhas.append(f"Encaixe: as unidades e os pedidos das 3 janelas da Magiic se reproduzem EXATAMENTE com a regra '{melhor['rotulo']}' e corte entre "
                      f"{quando(melhor['inicio'])} e {quando(melhor['fim'])}. Ou seja, no nível do produto inteiro a Magiic e o nosso banco contam as mesmas vendas.")
    else:
        linhas.append(f"Encaixe: nenhum corte reproduziu as 3 janelas por inteiro; o melhor ('{melhor['rotulo']}', {quando(melhor['inicio'])}) fica a {melhor['score']} de distância "
                      f"(unidades + pedidos). Isso é compatível com a borda das janelas, mas não prova.")
    iguais = sum(1 for r in tabela_dados if bate_tudo(r))
    linhas.append(f"Anúncio × janela: {n(iguais)} de {n(len(tabela_dados))} batem em unidades, pedidos e R$ ao centavo.")
    dif_un_ped = [r for r in tabela_dados if r["dif"]["un"] or r["dif"]["pedidos"]]
    linhas.append("Unidades e pedidos: " + ("batem em todas as combinações." if not dif_un_ped else
                  "divergem em " + ", ".join(f"{r['familia']} {r['janela']} (un {com_sinal(r['dif']['un'])}, pedidos {com_sinal(r['dif']['pedidos'])})" for r in dif_un_ped[:6]) + "."))
    com_dinheiro = [r for r in tabela_dados if r["magiic"]["un"]]
    perto_do_preco_medio = [r for r in com_dinheiro if abs(r["dif"]["nos_menos_preco_medio_x_un"]) <= arredondamento_do_preco_medio(r["magiic"]["un"])]
    linhas.append(f"Dinheiro: em {n(len(perto_do_preco_medio))} de {n(len(com_dinheiro))} combinações o NOSSO faturamento é igual ao 'preço médio × unidades' que a própria Magiic mostra "
                  f"(diferença só de arredondamento). O 'Vendas R$' dela é maior que isso em {n(sum(1 for r in com_dinheiro if tem_acrescimo(r)))} delas.")
    linhas.append(f"No total das 3 janelas: Vendas R$ da Magiic {reais(totais_reais['v'])} · preço médio × un da Magiic {reais(totais_reais['p'])} · nosso banco {reais(totais_reais['n'])}.")
    linhas.append("Limite: o banco não guarda total_amount, paid_amount nem frete. Este script mostra ONDE está o acréscimo (anúncio e janela), não O QUE ele é; isso só se vê no pedido do Mercado Livre.")
    return linhas


def salvar_json(s_total, faixas, tabela_dados, leitura, totais_reais):
    def limpo(valor):
        if isinstance(valor, Decimal):
            return str(valor)
        if isinstance(valor, (datetime, date)):
            return valor.isoformat()
        raise TypeError(type(valor))

    saida = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"), "conta": CONTA, "sku": SKU, "periodo": [DATA_INICIAL, DATA_FINAL],
        "config": {"corte_de": CORTE_DE, "corte_ate": CORTE_ATE, "passo_em_minutos": PASSO_DO_CORTE_EM_MINUTOS},
        "leitura_do_banco": s_total,
        "encaixe": [{k: v for k, v in f.items() if k not in ("variante",)} for f in faixas[:20]],
        "janela_por_janela": [{k: v for k, v in r.items() if k != "linhas"} for r in tabela_dados],
        "totais_em_reais": totais_reais,
        "linhas_das_janelas_com_acrescimo": {
            f"{r['familia']} · {r['janela']}": {
                "total_de_linhas": len(r["linhas"]),
                "linhas": [{"pedido": l["pedido"], "criado": l["criado"], "fechado": l["fechado"], "status": l["status"], "mlb": l["mlb"], "qtd": l["qtd"],
                            "preco": l["preco"], "desconto": l["desconto"], "catalogo": l["catalogo"], "taxa": l["taxa"], "pack": l["pack"]}
                           for l in sorted(r["linhas"], key=lambda x: x["criado"])[:LINHAS_POR_JANELA_NO_JSON]]}
            for r in tabela_dados if tem_acrescimo(r) or tem_diferenca_de_dinheiro(r)},
        "leitura": [x.replace("[green]", "").replace("[/]", "") for x in leitura],
    }
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=limpo), encoding="utf-8")


def main():
    console.print(f"\n[bold]Vendas do banco × Relatório de Elasticidade da Magiic[/] · conta {CONTA} · SKU {SKU} · só leitura (SELECT no banco; nenhuma chamada à API)\n")
    produto, linhas = ler_linhas()
    if produto is None:
        console.print(f"[bold red]SKU {t(SKU)} não encontrado em Produto. Nada foi comparado.[/]")
        return
    if not linhas:
        console.print("[yellow]Nenhuma linha de venda no período para este SKU.[/]")
        return
    s_total = mostrar_conferencia_da_leitura(linhas)
    faixas = testar_os_cortes(linhas)
    mostrar_o_encaixe(faixas)
    tabela_dados = comparar_por_familia(linhas, faixas[0])
    mostrar_janela_por_janela(tabela_dados)
    totais_reais = mostrar_totais_em_reais(tabela_dados)
    mostrar_janelas_com_acrescimo(tabela_dados)
    console.rule("[bold]Leitura")
    leitura = montar_leitura(faixas, tabela_dados, totais_reais)
    for linha in leitura:
        console.print(f"• {t(linha)}")
    salvar_json(s_total, faixas, tabela_dados, leitura, totais_reais)
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem chamada à API e sem dado de comprador (o banco não guarda).")


if __name__ == "__main__":
    main()
