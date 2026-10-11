# scripts_exploracao_ML/investigar_vendas_de_1_mlb_por_janela.py
#
# Objetivo ÚNICO: ver, pra 1 MLB, quantos pedidos e quantas unidades foram
# vendidos em 1, 3, 7, 15, 30 e 90 DIAS COMPLETOS (00h a 24h, horário de Brasília,
# terminando na meia-noite de hoje) e em hoje (parcial), via GET /orders/search.
#
# Só leitura (GET). Não toca no banco. Não chama /shipments. Sobrescreve o
# arquivo de saída a cada execução. Não guarda dados do comprador.

import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                # "MB" (Magazine) ou "SV" (Samvale)
MLB = "MLB5838465508"       # anúncio a investigar
# ========================================

# Janelas em DIAS COMPLETOS (00h a 24h, horário de Brasília), terminando na meia-noite de hoje.
# Hoje fica de fora das janelas porque o dia ainda não acabou; aparece numa linha à parte.
JANELAS = [
    ("1 dia (ontem)", 1),
    ("3 dias", 3),
    ("7 dias", 7),
    ("15 dias", 15),
    ("30 dias", 30),
    ("90 dias", 90),
]
DIAS_TOTAL = 90         # dias completos analisados (mais hoje, que é parcial)
LIMITE_POR_PAGINA = 50   # tamanho de página já observado em /orders/search
MAX_PAGINAS = 40         # trava de segurança (40 x 50 = 2000 pedidos)
NOME_LOG = "investigar_vendas_de_1_mlb_por_janela"

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_vendas_{MLB}_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

contador = {"chamadas": 0, "segundos": 0.0}
# 1 coluna de margem abaixo da largura do terminal: sem isso, no Windows a linha que ocupa a largura
# toda gruda na linha de baixo (mesmo cuidado que impostos/.../preenchimento_cst_produtos.py já tem)
console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(80, 24)).columns - 1, 20))
t = escape  # protege texto vindo da API de ser lido como marcação do rich


def formatar_data_para_filtro(instante):
    """Mesmo formato que já deu 200 OK nos outros scripts (ex: 2026-09-10T14:55:24.348-0300)."""
    texto = instante.isoformat(timespec="milliseconds")
    return texto[:-6] + texto[-6:].replace(":", "")


def ler_data(texto):
    if not texto:
        return None
    return datetime.fromisoformat(texto).astimezone(FUSO)


def chamar_orders_search(user_id, modo_filtro, inicio, fim, offset=0):
    params = {
        "seller": user_id,
        "order.date_created.from": formatar_data_para_filtro(inicio),
        "order.date_created.to": formatar_data_para_filtro(fim),
        "sort": "date_desc",
        "limit": LIMITE_POR_PAGINA,
    }
    params["item" if modo_filtro == "item" else "q"] = MLB
    if offset:
        params["offset"] = offset
    tempo_inicio = time.perf_counter()
    resposta = chamar_api(
        "GET", "/orders/search",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params=params, nome_log=NOME_LOG,
    )
    contador["chamadas"] += 1
    contador["segundos"] += time.perf_counter() - tempo_inicio
    return resposta.json()


def pedido_tem_o_mlb(pedido):
    return any(
        (item_do_pedido.get("item") or {}).get("id") == MLB
        for item_do_pedido in (pedido.get("order_items") or [])
    )


def buscar_todos_os_pedidos(user_id, inicio, fim):
    """Traz todos os pedidos da janela. Retorna (dict {order_id: pedido}, info do que aconteceu)."""
    info = {
        "modo_filtro": "item",
        "usou_plano_b_q": False,
        "total_segundo_a_api": 0,
        "paginas": 0,
        "offset_funcionou": None,   # None = não precisou testar (total <= 1 página)
        "fatiado_por_dia": False,
        "fatias_com_mais_de_uma_pagina": 0,
        "bateu_limite_de_paginas": False,
    }
    modo = "item"
    primeira = chamar_orders_search(user_id, modo, inicio, fim)
    resultados = primeira.get("results") or []
    total = (primeira.get("paging") or {}).get("total") or 0

    # Plano B: o filtro 'item' tem descrição ambígua na doc ("ID o título").
    # Se não trouxe nada, ou trouxe pedidos que não são do MLB, tenta 'q' (a doc diz que q pesquisa por ID do item).
    if total == 0 or (resultados and not any(pedido_tem_o_mlb(p) for p in resultados)):
        modo = "q"
        info["modo_filtro"] = "q"
        info["usou_plano_b_q"] = True
        primeira = chamar_orders_search(user_id, modo, inicio, fim)
        resultados = primeira.get("results") or []
        total = (primeira.get("paging") or {}).get("total") or 0

    info["total_segundo_a_api"] = total
    info["paginas"] = 1
    pedidos = {p["id"]: p for p in resultados}

    offset = LIMITE_POR_PAGINA
    while offset < total:
        if info["paginas"] >= MAX_PAGINAS:
            info["bateu_limite_de_paginas"] = True
            break
        pagina = chamar_orders_search(user_id, modo, inicio, fim, offset=offset)
        info["paginas"] += 1
        resultados = pagina.get("results") or []
        if not resultados:
            break
        novos = [p for p in resultados if p["id"] not in pedidos]
        if not novos:
            # a página veio só com pedidos que já tínhamos: o 'offset' foi ignorado pela API
            info["offset_funcionou"] = False
            break
        info["offset_funcionou"] = True
        for p in novos:
            pedidos[p["id"]] = p
        offset += LIMITE_POR_PAGINA

    # Plano C: se o 'offset' não funciona, busca dia a dia (cada dia cabe numa página, em geral).
    if info["offset_funcionou"] is False and len(pedidos) < total:
        info["fatiado_por_dia"] = True
        pedidos = {}
        fim_fatia = fim
        while fim_fatia > inicio:
            inicio_fatia = max(fim_fatia - timedelta(days=1), inicio)
            pagina = chamar_orders_search(user_id, modo, inicio_fatia, fim_fatia)
            info["paginas"] += 1
            if ((pagina.get("paging") or {}).get("total") or 0) > LIMITE_POR_PAGINA:
                info["fatias_com_mais_de_uma_pagina"] += 1
            for p in (pagina.get("results") or []):
                pedidos[p["id"]] = p
            fim_fatia = inicio_fatia

    return pedidos, info


def valores_unicos(itens, campo):
    vistos = []
    for item_do_pedido in itens:
        valor = (item_do_pedido.get("item") or {}).get(campo)
        if valor not in vistos:
            vistos.append(valor)
    return vistos


def montar_registro(pedido):
    itens_do_mlb = [
        item_do_pedido for item_do_pedido in (pedido.get("order_items") or [])
        if (item_do_pedido.get("item") or {}).get("id") == MLB
    ]
    if not itens_do_mlb:
        return None
    envio = pedido.get("shipping") or {}
    return {
        "order_id": pedido.get("id"),
        "status": pedido.get("status"),
        "date_created": pedido.get("date_created"),
        "date_closed": pedido.get("date_closed"),
        "unidades_do_mlb": sum((i.get("quantity") or 0) for i in itens_do_mlb),
        "outros_itens_no_pedido": len(pedido.get("order_items") or []) - len(itens_do_mlb),
        "variation_id": valores_unicos(itens_do_mlb, "variation_id"),
        "seller_sku": valores_unicos(itens_do_mlb, "seller_sku"),
        "seller_custom_field": valores_unicos(itens_do_mlb, "seller_custom_field"),
        "pack_id": pedido.get("pack_id"),
        "shipping_id": envio.get("id"),
    }


def somar_na_janela(registros, campo_data, inicio, fim):
    pedidos = 0
    unidades = 0
    for r in registros:
        instante = r[campo_data]
        if instante is not None and inicio <= instante < fim:
            pedidos += 1
            unidades += r["unidades_do_mlb"]
    return pedidos, unidades


def n_br(valor, casas=0):
    """Número no padrão brasileiro: 1.234 e 12,50."""
    texto_numero = f"{valor:,.{casas}f}"
    return texto_numero.replace(",", "X").replace(".", ",").replace("X", ".")


def barra(valor, maximo, largura=20):
    """Barrinha proporcional ao valor (ASCII se o terminal não aceitar Unicode)."""
    if not maximo or valor <= 0:
        return ""
    caractere = "#" if console.options.ascii_only else "\u2588"
    return caractere * max(1, round(valor / maximo * largura))


def estilo_celula(valor, maximo, texto_celula):
    """Cor da célula do calendário: cinza = zero; verde mais forte = mais unidades."""
    if valor <= 0:
        return f"[dim]{texto_celula}[/]"
    proporcao = valor / maximo if maximo else 0
    if proporcao >= 0.66:
        return f"[bold white on green]{texto_celula}[/]"
    if proporcao >= 0.33:
        return f"[bold green]{texto_celula}[/]"
    return f"[green]{texto_celula}[/]"


def texto_valores(valores):
    partes = ["[dim]vazio[/]" if v is None else t(str(v)) for v in valores]
    return ", ".join(partes) if partes else "[dim]vazio[/]"


agora = datetime.now(FUSO)
hoje_00h = agora.replace(hour=0, minute=0, second=0, microsecond=0)
inicio_busca = hoje_00h - timedelta(days=DIAS_TOTAL)   # ex.: 12/07 00:00
# A doc diz que o filtro de data só usa até a hora (descarta minutos). Por isso o fim vai até 00h de
# amanhã: nada de hoje fica de fora, e como ainda não existe pedido de amanhã, na prática é "até agora".
fim_busca = hoje_00h + timedelta(days=1)

# user_id vem do .env da raiz do repo (<CONTA>_USER_ID), mesmo padrão de api_mercado_livre/__init__.py
load_dotenv(dotenv_path=_RAIZ_DO_PROJETO / ".env")
user_id = os.getenv(f"{CONTA}_USER_ID")
if not user_id:
    console.print(f"[bold red]{CONTA}_USER_ID não encontrado no .env da raiz do repo.[/]")
    sys.exit(1)

try:
    console.print(
        f"Conta [bold]{CONTA}[/] | [bold]{MLB}[/] — buscando os pedidos de {inicio_busca:%d/%m/%Y} 00h até agora "
        f"({DIAS_TOTAL} dias completos + hoje parcial)..."
    )
    pedidos_da_api, info = buscar_todos_os_pedidos(user_id, inicio_busca, fim_busca)
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f"[bold red]Erro ao chamar a API:[/] {t(erro)}")
    sys.exit(1)

# ---------- monta os registros (um por pedido que realmente contém o MLB) ----------
registros = []
pedidos_sem_o_mlb = []
for pedido in pedidos_da_api.values():
    registro = montar_registro(pedido)
    if registro is None:
        pedidos_sem_o_mlb.append(pedido.get("id"))
        continue
    registro["_criado"] = ler_data(registro["date_created"])
    registro["_fechado"] = ler_data(registro["date_closed"])
    registros.append(registro)
registros.sort(key=lambda r: r["_criado"] or agora, reverse=True)

# ---------- apresentação no terminal (rich + pandas) ----------
# pandas organiza os números (agrupa por dia, preenche dias sem venda com 0, monta a grade
# semanas x dias da semana); rich desenha as tabelas. A busca e o JSON de saída não mudam.
completo = (
    len(pedidos_da_api) >= info["total_segundo_a_api"]
    and not info["bateu_limite_de_paginas"]
    and info["fatias_com_mais_de_uma_pagina"] == 0
)
hoje = pd.Timestamp(agora.date())
nomes_dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# ----- números por dia (pandas) -----
df_vendas = pd.DataFrame(
    [
        {"order_id": r["order_id"], "dia": pd.Timestamp(r["_criado"].date()), "unidades": r["unidades_do_mlb"]}
        for r in registros if r["_criado"] is not None
    ],
    columns=["order_id", "dia", "unidades"],
)
dias_do_periodo = pd.date_range(end=hoje, periods=DIAS_TOTAL + 1, freq="D")   # 90 dias completos + hoje
diario = (
    df_vendas.groupby("dia")
    .agg(pedidos=("order_id", "count"), unidades=("unidades", "sum"))
    .reindex(dias_do_periodo, fill_value=0)
    .astype(int)
)
tabela_dias = [
    {
        "data": data.date().isoformat(), "pedidos": int(linha["pedidos"]), "unidades": int(linha["unidades"]),
        "parcial": bool(data == hoje),
    }
    for data, linha in diario.iloc[::-1].iterrows()
]
dias_zerados = int((diario["unidades"].iloc[:-1] == 0).sum())   # só dias completos (hoje é parcial e fica de fora)
maior_dia = int(diario["unidades"].max())

# ----- cabeçalho -----
console.print()
console.print(Panel(
    f"[bold]Anúncio[/]  {MLB}     [bold]Conta[/]  {CONTA}\n"
    f"[bold]Gerado em[/]  {agora:%d/%m/%Y %H:%M} (horário de Brasília)\n"
    f"[bold]Período[/]  {inicio_busca:%d/%m/%Y} a {(hoje_00h - timedelta(days=1)):%d/%m/%Y} "
    f"({DIAS_TOTAL} dias completos, 00h a 24h) + hoje parcial",
    title="Vendas de 1 anúncio por janela", border_style="cyan", expand=False,
))

# ----- 1) como a busca se comportou -----
console.rule("[bold]1) Como a busca se comportou")
tabela_busca = Table(show_header=False)
tabela_busca.add_column("Item")
tabela_busca.add_column("Resultado")
if info["usou_plano_b_q"]:
    tabela_busca.add_row("Filtro que funcionou", "[yellow]q[/] (plano B: o filtro 'item' não trouxe pedidos do MLB)")
else:
    tabela_busca.add_row("Filtro que funcionou", "[green]item[/]")
tabela_busca.add_row("Total segundo a API (90 dias + hoje)", n_br(info["total_segundo_a_api"]))
cor_trazidos = "green" if len(pedidos_da_api) >= info["total_segundo_a_api"] else "yellow"
tabela_busca.add_row("Pedidos trazidos (sem repetir)", f"[{cor_trazidos}]{n_br(len(pedidos_da_api))}[/]")
cor_sem_mlb = "yellow" if pedidos_sem_o_mlb else "green"
tabela_busca.add_row(f"Pedidos que vieram sem o {MLB}", f"[{cor_sem_mlb}]{n_br(len(pedidos_sem_o_mlb))}[/]")
tabela_busca.add_row("Páginas/chamadas de busca", n_br(info["paginas"]))
texto_offset = {
    None: "[dim]não precisou (cabe numa página)[/]",
    True: "[green]SIM, funcionou[/]",
    False: "[yellow]NÃO funcionou (a API ignorou)[/]",
}[info["offset_funcionou"]]
tabela_busca.add_row("Parâmetro 'offset'", texto_offset)
if info["fatiado_por_dia"]:
    cor_fatias = "yellow" if info["fatias_com_mais_de_uma_pagina"] else "green"
    tabela_busca.add_row(
        "Busca refeita dia a dia",
        f"dias com mais de 1 página (dados incompletos): [{cor_fatias}]{info['fatias_com_mais_de_uma_pagina']}[/]",
    )
console.print(tabela_busca)
if completo:
    console.print("[bold green]Dados completos:[/] todos os pedidos informados pela API foram trazidos.")
else:
    console.print("[bold yellow]ATENÇÃO:[/] os números abaixo podem estar INCOMPLETOS (veja a tabela acima).")
if info["bateu_limite_de_paginas"]:
    console.print("[bold yellow]Bateu a trava de páginas do script.[/]")
if not registros:
    console.print("[yellow]Nenhum pedido deste MLB foi encontrado no período.[/]")

# ----- 2) janelas -----
console.rule("[bold]2) Vendas por janela")
tabela_janelas = []
for nome, dias_da_janela in JANELAS:
    inicio_janela = hoje_00h - timedelta(days=dias_da_janela)
    p_criacao, u_criacao = somar_na_janela(registros, "_criado", inicio_janela, hoje_00h)
    p_conf, u_conf = somar_na_janela(registros, "_fechado", inicio_janela, hoje_00h)
    media = u_criacao / dias_da_janela
    tabela_janelas.append({
        "janela": nome, "dias": dias_da_janela,
        "de": inicio_janela.isoformat(), "ate_exclusive": hoje_00h.isoformat(),
        "pedidos_por_criacao": p_criacao, "unidades_por_criacao": u_criacao,
        "media_unidades_por_dia": round(media, 3),
        "pedidos_por_confirmacao": p_conf, "unidades_por_confirmacao": u_conf,
    })
maior_media = max(j["media_unidades_por_dia"] for j in tabela_janelas)

# hoje (parcial): à parte, não entra nas janelas nem nas médias
p_hoje, u_hoje = somar_na_janela(registros, "_criado", hoje_00h, fim_busca)
p_hoje_conf, u_hoje_conf = somar_na_janela(registros, "_fechado", hoje_00h, fim_busca)
hoje_parcial = {
    "de": hoje_00h.isoformat(), "ate_agora": agora.isoformat(),
    "pedidos_por_criacao": p_hoje, "unidades_por_criacao": u_hoje,
    "pedidos_por_confirmacao": p_hoje_conf, "unidades_por_confirmacao": u_hoje_conf,
}

tabela_das_janelas = Table(
    title=f"Dias completos (00h a 24h, Brasília), até {hoje_00h:%d/%m/%Y} 00:00 — hoje fica à parte",
    title_justify="left", header_style="bold",
    caption=(
        "Pedidos / Unid. = pela criação do pedido (date_created).  Pedidos* / Unid.* = pela confirmação (date_closed).  "
        "Hoje é parcial e não entra nas médias."
    ),
    caption_justify="left",
)
tabela_das_janelas.add_column("Janela", no_wrap=True)
tabela_das_janelas.add_column("Pedidos", justify="right")
tabela_das_janelas.add_column("Unid.", justify="right")
tabela_das_janelas.add_column("Média un/dia", justify="right")
tabela_das_janelas.add_column("Ritmo", no_wrap=True)
tabela_das_janelas.add_column("Pedidos*", justify="right", style="dim")
tabela_das_janelas.add_column("Unid.*", justify="right", style="dim")
for linha_janela in tabela_janelas:
    tabela_das_janelas.add_row(
        linha_janela["janela"],
        n_br(linha_janela["pedidos_por_criacao"]),
        f"[bold]{n_br(linha_janela['unidades_por_criacao'])}[/]",
        n_br(linha_janela["media_unidades_por_dia"], 2),
        f"[cyan]{barra(linha_janela['media_unidades_por_dia'], maior_media)}[/]",
        n_br(linha_janela["pedidos_por_confirmacao"]),
        n_br(linha_janela["unidades_por_confirmacao"]),
    )
tabela_das_janelas.add_section()
tabela_das_janelas.add_row(
    f"Hoje (até {agora:%H:%M})", n_br(p_hoje), f"[bold]{n_br(u_hoje)}[/]", "[dim]—[/]", "[dim]parcial[/]",
    n_br(p_hoje_conf), n_br(u_hoje_conf),
)
console.print(tabela_das_janelas)

# ----- 3) calendário (semanas x dias da semana) -----
console.rule("[bold]3) Calendário de vendas (unidades por dia)")
datas = diario.index.to_series()
dia_da_semana = datas.dt.weekday
segunda_da_semana = datas - pd.to_timedelta(dia_da_semana, unit="D")
grade = (
    pd.DataFrame({"segunda": segunda_da_semana, "dow": dia_da_semana, "unidades": diario["unidades"]})
    .pivot(index="segunda", columns="dow", values="unidades")
    .reindex(columns=range(7))
    .sort_index(ascending=False)
)
calendario = Table(
    title=f"Unidades vendidas por dia — {DIAS_TOTAL} dias completos + hoje, semanas mais recentes em cima", title_justify="left",
    header_style="bold",
    caption=(
        f"Cor mais forte = mais unidades (escala: maior dia = {n_br(maior_dia)} un).  Cinza = dia zerado.  "
        "· = fora do período.  * = hoje (dia parcial)."
    ),
    caption_justify="left",
)
calendario.add_column("Semana de", no_wrap=True)
for nome_do_dia in nomes_dias:
    calendario.add_column(nome_do_dia, justify="center", no_wrap=True, min_width=4)
calendario.add_column("Total", justify="right", style="bold")
for segunda, linha_da_grade in grade.iterrows():
    celulas = []
    total_da_semana = 0
    for dow in range(7):
        valor_da_celula = linha_da_grade[dow]
        if pd.isna(valor_da_celula):
            celulas.append("[dim]·[/]")
            continue
        valor_da_celula = int(valor_da_celula)
        total_da_semana += valor_da_celula
        eh_hoje = (segunda + pd.Timedelta(days=dow)) == hoje
        celulas.append(estilo_celula(valor_da_celula, maior_dia, f"{valor_da_celula}{'*' if eh_hoje else ''}"))
    calendario.add_row(f"{segunda:%d/%m}", *celulas, n_br(total_da_semana))
console.print(calendario)
console.print(
    f"Dias zerados (dias completos): [bold]{dias_zerados}[/] de {DIAS_TOTAL}   |   "
    f"Maior dia: [bold]{n_br(maior_dia)}[/] un"
)

# ----- 4) últimos 14 dias em detalhe -----
console.rule("[bold]4) Últimos 14 dias (detalhe)")
recentes = diario.iloc[::-1].head(14)
maior_recente = int(recentes["unidades"].max())
tabela_14_dias = Table(header_style="bold")
tabela_14_dias.add_column("Data", no_wrap=True)
tabela_14_dias.add_column("Dia", no_wrap=True)
tabela_14_dias.add_column("Pedidos", justify="right")
tabela_14_dias.add_column("Unid.", justify="right")
tabela_14_dias.add_column("Ritmo", no_wrap=True)
for data, linha in recentes.iterrows():
    unidades_do_dia = int(linha["unidades"])
    marca_hoje = "  [dim](hoje, parcial)[/]" if data == hoje else ""
    texto_unidades = f"[dim]{unidades_do_dia}[/]" if unidades_do_dia == 0 else f"[bold]{n_br(unidades_do_dia)}[/]"
    tabela_14_dias.add_row(
        f"{data:%d/%m/%Y}", nomes_dias[data.weekday()], n_br(int(linha["pedidos"])), texto_unidades,
        f"[cyan]{barra(unidades_do_dia, maior_recente)}[/]{marca_hoje}",
    )
console.print(tabela_14_dias)

# ----- 5) diagnóstico de campos -----
console.rule("[bold]5) O que os pedidos mostram (pra decidirmos os próximos passos)")
contagem_status = Counter(r["status"] for r in registros)
total_registros = len(registros)
com_pack = sum(1 for r in registros if r["pack_id"] is not None)
com_envio = sum(1 for r in registros if r["shipping_id"] is not None)
com_sku = sum(1 for r in registros if any(v is not None for v in r["seller_sku"]))
com_campo = sum(1 for r in registros if any(v is not None for v in r["seller_custom_field"]))
com_outros_itens = sum(1 for r in registros if r["outros_itens_no_pedido"] > 0)
mais_de_um_item = sum(1 for r in registros if r["unidades_do_mlb"] > 1)
atrasos = [(r["_fechado"] - r["_criado"]).total_seconds() for r in registros if r["_criado"] and r["_fechado"]]
unidades_por_variacao = Counter()
for r in registros:
    nome_variacao = ", ".join("sem variação" if v is None else str(v) for v in r["variation_id"]) or "sem variação"
    unidades_por_variacao[nome_variacao] += r["unidades_do_mlb"]

tabela_diagnostico = Table(header_style="bold")
tabela_diagnostico.add_column("O que foi observado")
tabela_diagnostico.add_column("Resultado")
tabela_diagnostico.add_row("Status dos pedidos", ", ".join(f"{t(str(s))}: {n_br(n)}" for s, n in contagem_status.items()) or "[dim]—[/]")
tabela_diagnostico.add_row("pack_id preenchido", f"{n_br(com_pack)} de {n_br(total_registros)} pedidos")
tabela_diagnostico.add_row("shipping.id preenchido", f"{n_br(com_envio)} de {n_br(total_registros)} pedidos")
tabela_diagnostico.add_row("seller_sku preenchido", f"{n_br(com_sku)} de {n_br(total_registros)} pedidos")
tabela_diagnostico.add_row("seller_custom_field preenchido", f"{n_br(com_campo)} de {n_br(total_registros)} pedidos")
tabela_diagnostico.add_row("Pedidos com outros itens junto (carrinho)", n_br(com_outros_itens))
tabela_diagnostico.add_row("Pedidos com mais de 1 unidade do MLB", n_br(mais_de_um_item))
if atrasos:
    tabela_diagnostico.add_row(
        "Diferença date_closed − date_created",
        f"mínimo {n_br(min(atrasos))}s  |  máximo {n_br(max(atrasos))}s",
    )
tabela_diagnostico.add_row(
    "Unidades por variation_id",
    ", ".join(f"{t(nome_v)}: {n_br(un)} un" for nome_v, un in unidades_por_variacao.items()) or "[dim]—[/]",
)
console.print(tabela_diagnostico)

# ----- 6) pedidos mais recentes -----
console.rule("[bold]6) Os 5 pedidos mais recentes")
if not registros:
    console.print("[dim]Nenhum pedido para mostrar.[/]")
else:
    # duas tabelas lado a lado seriam largas demais pro terminal; o número do pedido liga uma na outra
    tabela_recentes = Table(
        title="Quando e quanto", title_justify="left", header_style="bold", box=box.SIMPLE_HEAD, pad_edge=False,
        caption="Confirm. após = date_closed − date_created.", caption_justify="left",
    )
    tabela_recentes.add_column("Pedido", no_wrap=True)
    tabela_recentes.add_column("Criado", no_wrap=True)
    tabela_recentes.add_column("Confirm. após", no_wrap=True, justify="right")
    tabela_recentes.add_column("Status", no_wrap=True)
    tabela_recentes.add_column("Un.", no_wrap=True, justify="right")
    tabela_campos = Table(
        title="Campos que identificam produto e envio", title_justify="left", header_style="bold",
        box=box.SIMPLE_HEAD, pad_edge=False,
    )
    tabela_campos.add_column("Pedido", no_wrap=True)
    tabela_campos.add_column("seller_sku", overflow="fold")
    tabela_campos.add_column("seller_custom_field", overflow="fold")
    tabela_campos.add_column("variation_id", overflow="fold")
    tabela_campos.add_column("pack_id", overflow="fold")
    tabela_campos.add_column("shipping.id", overflow="fold")
    for r in registros[:5]:
        criado_curto = r["_criado"].strftime("%d/%m %H:%M:%S") if r["_criado"] else "[dim]—[/]"
        if r["_criado"] and r["_fechado"]:
            confirmado_apos = f"{int((r['_fechado'] - r['_criado']).total_seconds())}s"
        else:
            confirmado_apos = "[dim]—[/]"
        tabela_recentes.add_row(
            t(str(r["order_id"])), criado_curto, confirmado_apos, t(str(r["status"])), n_br(r["unidades_do_mlb"]),
        )
        tabela_campos.add_row(
            t(str(r["order_id"])), texto_valores(r["seller_sku"]), texto_valores(r["seller_custom_field"]),
            texto_valores(r["variation_id"]), texto_valores([r["pack_id"]]), texto_valores([r["shipping_id"]]),
        )
    console.print(tabela_recentes)
    console.print(tabela_campos)

# ---------- salva ----------
registros_para_salvar = [{k: v for k, v in r.items() if not k.startswith("_")} for r in registros]
saida = {
    "mlb": MLB,
    "conta": CONTA,
    "gerado_em": agora.isoformat(),
    "periodo": {
        "dias_completos": DIAS_TOTAL,
        "de": inicio_busca.isoformat(),
        "ate_exclusive": hoje_00h.isoformat(),
        "busca_ate": fim_busca.isoformat(),
    },
    "info_da_busca": info,
    "pedidos_vindos_sem_o_mlb": pedidos_sem_o_mlb,
    "janelas": tabela_janelas,
    "hoje_parcial": hoje_parcial,
    "por_dia": tabela_dias,
    "pedidos": registros_para_salvar,
}
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as arquivo:
    json.dump(saida, arquivo, ensure_ascii=False, indent=2)
console.print()
console.print(Panel(
    f"[bold]Chamadas à API neste script:[/] {contador['chamadas']} (somando {contador['segundos']:.1f}s só esperando a API)\n"
    f"[bold]Resultado salvo em:[/] {t(str(CAMINHO_SAIDA))}\n"
    "Suba esse arquivo na conversa (e cole o que apareceu acima) pra eu analisar.",
    border_style="green", expand=False,
))
