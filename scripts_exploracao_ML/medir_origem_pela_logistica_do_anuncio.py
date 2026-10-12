# scripts_exploracao_ML/medir_origem_pela_logistica_do_anuncio.py
#
# Função Objetivo: MEDIR, só com o que JÁ ESTÁ NO BANCO (zero chamadas à API), como ficaria a classificação Full × Fora do Full da tela de Vendas
# se a regra passasse a ser a do vault: tipo logístico "fulfillment" = Full; QUALQUER outro (Coleta/cross_docking, Agência, Flex...) = Fora do Full.
#
# A regra proposta, na ordem (a primeira que servir decide):
#   1) a linha tem store_id                              → Fora do Full  (estoque próprio, o ML informa a loja)
#   2) a linha tem node_id de um depósito do vendedor    → Fora do Full  (o nó próprio, mesmo antes de o ML mandar o store_id)
#   3) a linha tem qualquer outro node_id                → Full          (centros do Full: BRSP10, BRPE01, BRPR01...)
#   4) a linha NÃO tem node_id nem store_id (as "Sem origem") → olha o ANÚNCIO (o cadastro que já está no banco, a mesma logística do selo "Logística"):
#         anúncio que hoje NÃO é Full E que NUNCA vendeu por um centro do Full no banco → Fora do Full
#         anúncio Full, anúncio fora do cadastro ou anúncio que JÁ vendeu pelo Full     → continua "Sem origem" (não dá para decidir sem consultar o envio)
#
# O script responde, em 5 partes:
#   PARTE 1: quanto muda (por mês e "de onde para onde") entre a regra de HOJE (classificar_origem) e a regra proposta.
#   PARTE 2: as vendas hoje "Sem origem", separadas pela logística do anúncio: quantas iriam para Fora e quantas continuariam sem origem.
#   PARTE 3: TODOS os anúncios (MLB) do banco, do que mais vendeu para o que menos vendeu: logística, Flex ligado ou não, unidades por origem e o
#            % de Fora do Full de cada um. É onde se vê ONDE está o volume e de qual tipo de anúncio vem o "Fora do Full".
#   PARTE 4: nas vendas que têm origem conhecida (nó ou loja), origem real × logística de HOJE do anúncio. ATENÇÃO: antes de 26/03/2026 as vendas de
#            estoque próprio vinham SEM origem, então a coluna "Un Fora" dessa época sempre sai pequena: esta parte NÃO prova a regra 4, só mostra o quadro.
#   PARTE 5: os nós do banco e o destino de cada um na regra proposta (para conferir BRPE01 / BRPR01 / nó próprio).
#
# REGRAS: só SELECT no banco. ZERO chamadas à API: este script nem importa o cliente da API nem o gerenciador de token. Nada é gravado no banco.
# O seller_id não existe aqui; o nó próprio (BRP + código do vendedor + 1) aparece mascarado como BRP***1. O JSON é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → Os "nós próprios" desta medição saem do próprio banco: os nós que aparecem JUNTO com um store_id. Na regra final, a fonte seria a
#                  lista de depósitos do vendedor (GET /users/{id}/stores/search?tags=stock_location): 1 chamada por conta, guardada no banco.
# * [EXPLICAÇÃO] → A logística do anúncio é a de HOJE (a última importação do cadastro), não a do dia da venda. Por isso a PARTE 4 existe: ela mede,
#                  com milhares de vendas de origem conhecida, o quanto essa troca de tempo atrapalha antes de a regra 4 ir para o código.
# * [EXPLICAÇÃO] → Quantidades são sempre em UNIDADES (soma de quantidade), nunca em pedidos, e só de vendas não canceladas (como a tela).

import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


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
from gestao_vendas.funcoes_auxiliares.vendas_ml import STATUS_CANCELADO, classificar_origem
from mercado_livre.models import AnuncioMercadoLivre, VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale): decide o banco lido
TOPO_DE_ANUNCIOS = 30                 # quantos anúncios (MLB) mostrar na PARTE 3 (ordenados por unidades sem origem)
POUCO_DADO_ABAIXO_DE = 30             # abaixo disso (unidades) a leitura avisa que a amostra é pequena para tirar conclusão
MLBS_POR_CONSULTA = 500               # o cadastro dos anúncios é lido em blocos (evita um IN gigante no MySQL)
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_origem_pela_logistica_do_anuncio_{CONTA}.json"
CAMPOS_DA_VENDA = ("mlb", "quantidade", "dia_venda", "node_id", "store_id")
CAMPOS_DO_ANUNCIO = ("mlb", "tipo_de_anuncio__tipo_logistico", "tipo_de_anuncio__flex", "tipo_de_anuncio__status", "tipo_de_anuncio__tipo_anuncio")

ORIGENS = ("full", "fora", "indefinido")
NOME_DA_ORIGEM = {"full": "Full", "fora": "Fora do Full", "indefinido": "Sem origem"}
LOGISTICA = {                         # os 7 valores de TipoLogistico do cadastro (mesmos rótulos do selo "Logística" do Hub)
    "fulfillment": "FULL (fulfillment)",
    "cross_docking": "Coleta (cross_docking)",
    "xd_drop_off": "Agência (xd_drop_off)",
    "self_service": "Flex Puro (self_service)",
    "not_specified": "Legado (not_specified)",
    "drop_off": "Correios (drop_off)",
    "custom": "Por nossa conta (custom)",
}
LOGISTICA_CURTA = {"fulfillment": "FULL", "cross_docking": "Coleta", "xd_drop_off": "Agência", "self_service": "Flex Puro", "not_specified": "Legado",
                   "drop_off": "Correios", "custom": "Por nossa conta"}     # para tabelas largas (PARTE 3)
SEM_TIPO = "(anúncio sem tipo)"
SEM_CADASTRO = "(MLB fora do cadastro)"
ORDEM_DOS_GRUPOS = list(LOGISTICA) + [SEM_TIPO, SEM_CADASTRO]
GRUPOS_SEM_RESPOSTA = {"fulfillment", SEM_TIPO, SEM_CADASTRO}    # nesses a regra 4 NÃO decide: a linha continua "Sem origem"

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(100, 24)).columns - 1, 40))
t = escape
resultado = {}                        # tudo o que vai para o JSON


# ============================== utilitários ==============================

def n(valor):
    return f"{valor:,}".replace(",", ".")


def pct(parte, total):
    return 100 * parte / total if total else 0.0


def tpct(parte, total):
    return f"{pct(parte, total):.1f}%" if total else "-"


def data(dia):
    return dia.strftime("%d/%m/%Y") if dia else "-"


def rotulo(grupo):
    return LOGISTICA.get(grupo, grupo)


def posicao_do_grupo(grupo):
    return ORDEM_DOS_GRUPOS.index(grupo) if grupo in ORDEM_DOS_GRUPOS else len(ORDEM_DOS_GRUPOS)


def mascarar_no(no, nos_proprios):
    """O nó próprio é 'BRP' + código do vendedor + '1': mostra BRP***1. Qualquer nó longo demais para ser de centro do Full também é mascarado."""
    if not no:
        return "(sem node_id)"
    if no in nos_proprios or len(no) > 8:
        return no[:3] + "***" + no[-1:]
    return no


def nova_tabela(titulo, *colunas):
    tabela = Table(title=titulo, title_justify="left", box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
    for nome, alinhamento in colunas:
        tabela.add_column(nome, justify=alinhamento, no_wrap=(alinhamento == "right"))   # número e data nunca quebram nem viram "…"; o texto da esquerda quebra
    return tabela


def soma_por(linhas, chave):
    total = Counter()
    for l in linhas:
        total[chave(l)] += l["quantidade"]
    return total


# ============================== leitura do banco ==============================

def ler_vendas():
    """Vendas NÃO canceladas, 1 dict por linha (só os campos usados). Só SELECT, em blocos de 5000."""
    consulta = VendaItemMercadoLivre.objects.exclude(status=STATUS_CANCELADO).values_list(*CAMPOS_DA_VENDA).iterator(chunk_size=5000)
    return [dict(zip(CAMPOS_DA_VENDA, linha)) for linha in consulta]


def ler_anuncios(mlbs):
    """{mlb: {logistica, flex, status, tipo}} do cadastro (AnuncioMercadoLivre → tipo_de_anuncio). MLB que não está no cadastro fica fora do dict."""
    lista, saida = sorted(mlbs), {}
    for inicio in range(0, len(lista), MLBS_POR_CONSULTA):
        consulta = AnuncioMercadoLivre.objects.filter(mlb__in=lista[inicio:inicio + MLBS_POR_CONSULTA]).values_list(*CAMPOS_DO_ANUNCIO)
        for mlb, logistica, flex, status, tipo in consulta:
            saida[mlb] = {"logistica": logistica or None, "flex": flex, "status": status, "tipo": tipo}
    return saida


# ============================== a regra proposta ==============================

def grupo_do_anuncio(mlb, anuncios):
    anuncio = anuncios.get(mlb)
    if anuncio is None:
        return SEM_CADASTRO
    return anuncio["logistica"] or SEM_TIPO


def regra_proposta(l, nos_proprios):
    """(origem, motivo) da regra de 4 passos descrita no cabeçalho. `l` já tem o campo 'grupo' (logística de hoje do anúncio)."""
    if l["store_id"]:
        return "fora", "store_id"
    if l["node_id"]:
        return ("fora", "nó próprio") if l["node_id"] in nos_proprios else ("full", "nó do Full")
    if l["grupo"] in GRUPOS_SEM_RESPOSTA:
        return "indefinido", "anúncio Full ou sem cadastro"
    if l["mlb_ja_vendeu_pelo_full"]:
        return "indefinido", "o MLB já vendeu pelo Full"
    return "fora", "logística do anúncio"


def preparar(vendas, anuncios):
    nos_proprios = {l["node_id"] for l in vendas if l["store_id"] and l["node_id"]}
    # * [EXPLICAÇÃO] → "Já vendeu pelo Full" = o MLB tem alguma venda com node_id de centro do Full (nó que não é do vendedor e sem store_id) no banco.
    #                  Pedido do Full sempre traz o stock (o ML só omitiu o stock nas vendas de Coleta), então um MLB que já vendeu pelo Full pode ter
    #                  vendas do Full sem origem: nele a regra 4 não decide.
    mlbs_que_ja_venderam_pelo_full = {l["mlb"] for l in vendas if l["node_id"] and not l["store_id"] and l["node_id"] not in nos_proprios}
    for l in vendas:
        l["atual"] = classificar_origem(l["node_id"], l["store_id"])
        l["grupo"] = grupo_do_anuncio(l["mlb"], anuncios)
        l["mlb_ja_vendeu_pelo_full"] = l["mlb"] in mlbs_que_ja_venderam_pelo_full
        l["proposta"], l["motivo"] = regra_proposta(l, nos_proprios)
        l["origem_conhecida"] = bool(l["node_id"] or l["store_id"])
    return nos_proprios


# ============================== PARTE 1: quanto muda ==============================

def parte_1_quanto_muda(vendas):
    total = sum(l["quantidade"] for l in vendas)
    atual, proposta = soma_por(vendas, lambda l: l["atual"]), soma_por(vendas, lambda l: l["proposta"])

    resumo = nova_tabela("Unidades por origem: regra de HOJE × regra proposta", ("Origem", "left"), ("Hoje", "right"), ("% hoje", "right"),
                         ("Proposta", "right"), ("% proposta", "right"), ("Diferença", "right"))
    for origem in ORIGENS:
        dif = proposta[origem] - atual[origem]
        resumo.add_row(NOME_DA_ORIGEM[origem], n(atual[origem]), tpct(atual[origem], total), n(proposta[origem]), tpct(proposta[origem], total),
                       f"{dif:+,}".replace(",", ".") if dif else "0")
    resumo.add_row("Total", n(total), "", n(total), "", "", end_section=False)
    console.print(resumo)

    meses = sorted({l["dia_venda"].strftime("%Y-%m") for l in vendas})
    por_mes_atual = defaultdict(Counter)
    por_mes_proposta = defaultdict(Counter)
    for l in vendas:
        mes = l["dia_venda"].strftime("%Y-%m")
        por_mes_atual[mes][l["atual"]] += l["quantidade"]
        por_mes_proposta[mes][l["proposta"]] += l["quantidade"]
    tabela_mes = nova_tabela("Por mês (unidades): hoje → proposta", ("Mês", "left"), ("Un", "right"), ("Full hoje", "right"), ("Fora hoje", "right"),
                             ("S/orig. hoje", "right"), ("Full prop.", "right"), ("Fora prop.", "right"), ("S/orig. prop.", "right"))
    linhas_mes = []
    for mes in meses:
        a, p = por_mes_atual[mes], por_mes_proposta[mes]
        un = sum(a.values())
        tabela_mes.add_row(mes, n(un), n(a["full"]), n(a["fora"]), n(a["indefinido"]), n(p["full"]), n(p["fora"]), n(p["indefinido"]))
        linhas_mes.append({"mes": mes, "un": un, "hoje": dict(a), "proposta": dict(p)})
    console.print(tabela_mes)

    de_para = Counter()
    for l in vendas:
        de_para[(l["atual"], l["proposta"])] += l["quantidade"]
    tabela_de_para = nova_tabela("De onde para onde (unidades): linhas = regra de HOJE, colunas = regra proposta", ("Hoje ↓  /  Proposta →", "left"),
                                 *[(NOME_DA_ORIGEM[o], "right") for o in ORIGENS], ("Total", "right"))
    for origem_atual in ORIGENS:
        celulas = []
        for origem_nova in ORIGENS:
            valor = de_para[(origem_atual, origem_nova)]
            celulas.append(f"[bold yellow]{n(valor)}[/]" if valor and origem_atual != origem_nova else n(valor))
        tabela_de_para.add_row(NOME_DA_ORIGEM[origem_atual], *celulas, n(sum(de_para[(origem_atual, o)] for o in ORIGENS)))
    console.print(tabela_de_para)
    console.print("[dim]Amarelo = unidades que MUDAM de grupo.[/]\n")

    resultado["parte_1"] = {"un_total": total, "hoje": dict(atual), "proposta": dict(proposta), "por_mes": linhas_mes,
                            "de_para": {f"{a}->{p}": v for (a, p), v in de_para.items()}}
    return {"total": total, "atual": atual, "proposta": proposta, "de_para": de_para}


# ============================== PARTE 2: as sem origem, pela logística do anúncio ==============================

def parte_2_sem_origem(vendas):
    sem = [l for l in vendas if l["atual"] == "indefinido"]
    un_sem = sum(l["quantidade"] for l in sem)
    if not sem:
        console.print("[green]Nenhuma venda sem origem no banco: nada a medir na PARTE 2.[/]\n")
        resultado["parte_2"] = {"un_sem_origem": 0, "por_logistica": []}
        return {"sem": [], "un_sem": 0, "para_fora": 0, "continuam": 0, "mlbs_fora": 0, "mlbs_continuam": 0, "ultimo_dia": None}

    grupos = defaultdict(lambda: {"un": 0, "fora": 0, "continuam": 0, "linhas": 0, "mlbs": set(), "primeiro": None, "ultimo": None})
    mlbs_fora, mlbs_continuam = set(), set()
    for l in sem:
        g = grupos[l["grupo"]]
        g["un"] += l["quantidade"]
        g["linhas"] += 1
        g["mlbs"].add(l["mlb"])
        if l["proposta"] == "fora":
            g["fora"] += l["quantidade"]
            mlbs_fora.add(l["mlb"])
        else:
            g["continuam"] += l["quantidade"]
            mlbs_continuam.add(l["mlb"])
        g["primeiro"] = l["dia_venda"] if g["primeiro"] is None or l["dia_venda"] < g["primeiro"] else g["primeiro"]
        g["ultimo"] = l["dia_venda"] if g["ultimo"] is None or l["dia_venda"] > g["ultimo"] else g["ultimo"]

    tabela = nova_tabela(f"As {n(un_sem)} un 'Sem origem' de hoje, pela logística ATUAL do anúncio e a regra 4", ("Logística do anúncio hoje", "left"), ("Un", "right"),
                         ("% das sem origem", "right"), ("→ Fora do Full", "right"), ("Continuam sem origem", "right"), ("Linhas", "right"), ("MLBs", "right"),
                         ("De", "right"), ("Até", "right"))
    lista = []
    for grupo in sorted(grupos, key=posicao_do_grupo):
        g = grupos[grupo]
        tabela.add_row(t(rotulo(grupo)), n(g["un"]), tpct(g["un"], un_sem), n(g["fora"]), n(g["continuam"]), n(g["linhas"]), n(len(g["mlbs"])),
                       data(g["primeiro"]), data(g["ultimo"]))
        lista.append({"logistica_do_anuncio": grupo, "un": g["un"], "para_fora": g["fora"], "continuam_sem_origem": g["continuam"], "linhas": g["linhas"],
                      "mlbs": len(g["mlbs"]), "primeiro_dia": g["primeiro"], "ultimo_dia": g["ultimo"]})
    para_fora = sum(g["fora"] for g in grupos.values())
    tabela.add_row("Total", n(un_sem), "100%", n(para_fora), n(un_sem - para_fora), n(len(sem)), n(len({l["mlb"] for l in sem})),
                   data(min(l["dia_venda"] for l in sem)), data(max(l["dia_venda"] for l in sem)))
    console.print(tabela)
    console.print("[dim]'Continuam sem origem' = anúncio Full, fora do cadastro, ou MLB que já vendeu por um centro do Full (a regra 4 não decide).[/]\n")
    resultado["parte_2"] = {"un_sem_origem": un_sem, "por_logistica": lista}
    return {"sem": sem, "un_sem": un_sem, "para_fora": para_fora, "continuam": un_sem - para_fora, "mlbs_fora": len(mlbs_fora),
            "mlbs_continuam": len(mlbs_continuam), "ultimo_dia": max(l["dia_venda"] for l in sem)}


# ============================== PARTE 3: por anúncio (TODOS os MLBs do banco) ==============================

def parte_3_por_mlb(vendas, anuncios):
    por_mlb = defaultdict(lambda: {"un": 0, "full_no": 0, "fora_no": 0, "sem": 0, "fora_regra4": 0, "primeiro": None, "ultimo": None})
    for l in vendas:
        a, q = por_mlb[l["mlb"]], l["quantidade"]
        a["un"] += q
        if l["atual"] == "indefinido":
            a["sem"] += q
            a["fora_regra4"] += q if l["proposta"] == "fora" else 0
        elif l["proposta"] == "full":
            a["full_no"] += q
        else:
            a["fora_no"] += q
        a["primeiro"] = l["dia_venda"] if a["primeiro"] is None or l["dia_venda"] < a["primeiro"] else a["primeiro"]
        a["ultimo"] = l["dia_venda"] if a["ultimo"] is None or l["dia_venda"] > a["ultimo"] else a["ultimo"]

    total = sum(a["un"] for a in por_mlb.values())
    ordenados = sorted(por_mlb, key=lambda m: -por_mlb[m]["un"])
    tabela = nova_tabela(f"Todos os anúncios (MLB) do banco: {n(len(ordenados))} (mostrando até {TOPO_DE_ANUNCIOS}), do que mais vendeu para o que menos vendeu",
                         ("MLB", "left"), ("Logística hoje", "left"), ("Flex", "left"), ("Status", "left"), ("Un", "right"), ("% do produto", "right"),
                         ("Full (nó)", "right"), ("Fora (nó/loja)", "right"), ("Sem origem hoje", "right"), ("Fora na proposta", "right"),
                         ("% Fora", "right"), ("1ª venda", "right"), ("Última venda", "right"))
    lista = []
    for mlb in ordenados:
        a, ad = por_mlb[mlb], anuncios.get(mlb)
        grupo = grupo_do_anuncio(mlb, anuncios)
        flex = (ad or {}).get("flex")
        flex_texto = "Com Flex" if flex else ("Sem Flex" if flex is not None else "-")
        status = (ad or {}).get("status") or "-"
        fora = a["fora_no"] + a["fora_regra4"]
        lista.append({"mlb": mlb, "logistica_hoje": grupo, "flex": flex, "status": status, "un": a["un"], "full_no": a["full_no"], "fora_no_ou_loja": a["fora_no"],
                      "sem_origem_hoje": a["sem"], "fora_na_proposta": fora, "primeiro_dia": a["primeiro"], "ultimo_dia": a["ultimo"]})
        if len(lista) <= TOPO_DE_ANUNCIOS:
            tabela.add_row(mlb, t(LOGISTICA_CURTA.get(grupo, grupo)), flex_texto, t(status), n(a["un"]), tpct(a["un"], total), n(a["full_no"]), n(a["fora_no"]),
                           n(a["sem"]), n(fora), tpct(fora, a["un"]), data(a["primeiro"]), data(a["ultimo"]))
    soma = lambda campo: sum(por_mlb[m][campo] for m in ordenados)
    fora_total = soma("fora_no") + soma("fora_regra4")
    tabela.add_row("Total", "", "", "", n(total), "100%", n(soma("full_no")), n(soma("fora_no")), n(soma("sem")), n(fora_total), tpct(fora_total, total), "", "")
    console.print(tabela)
    console.print("[dim]Full (nó) / Fora (nó/loja) = vendas COM origem conhecida (node_id ou store_id). 'Fora na proposta' = Fora (nó/loja) + as sem origem que a regra 4 manda para Fora.[/]\n")
    resultado["parte_3"] = lista
    return lista


# ============================== PARTE 4: teste de confiança ==============================

def matriz_de_confianca(vendas, filtro):
    """{grupo: Counter(full, fora)} só com vendas de origem CONHECIDA (node_id ou store_id), pela origem real da regra proposta."""
    matriz = defaultdict(Counter)
    for l in vendas:
        if l["origem_conhecida"] and filtro(l):
            matriz[l["grupo"]][l["proposta"]] += l["quantidade"]
    return matriz


def mostrar_matriz(titulo, matriz):
    tabela = nova_tabela(titulo, ("Logística do anúncio HOJE", "left"), ("Un Full", "right"), ("Un Fora", "right"), ("Total", "right"),
                         ("% Fora", "right"), ("Regra 4 diria", "left"))
    lista = []
    for grupo in sorted(matriz, key=posicao_do_grupo):
        full, fora = matriz[grupo]["full"], matriz[grupo]["fora"]
        diz_fora = grupo not in GRUPOS_SEM_RESPOSTA
        tabela.add_row(t(rotulo(grupo)), n(full), n(fora), n(full + fora), tpct(fora, full + fora), "Fora do Full" if diz_fora else "não decide")
        lista.append({"logistica_do_anuncio": grupo, "un_full": full, "un_fora": fora})
    if not matriz:
        tabela.add_row("(nenhuma venda com origem conhecida)", "-", "-", "-", "-", "-")
    console.print(tabela)
    return lista


def parte_4_confianca(vendas, ultimo_dia_sem_origem):
    todo = matriz_de_confianca(vendas, lambda l: True)
    resultado["parte_4"] = {"todo_o_periodo": mostrar_matriz("Vendas COM origem conhecida, em todo o período: origem real × logística do anúncio hoje", todo)}
    ate_corte = None
    if ultimo_dia_sem_origem:
        ate_corte = matriz_de_confianca(vendas, lambda l: l["dia_venda"] <= ultimo_dia_sem_origem)
        resultado["parte_4"]["ate_o_ultimo_dia_sem_origem"] = mostrar_matriz(
            f"Só até {data(ultimo_dia_sem_origem)} (último dia com venda sem origem): a época em que a regra 4 seria usada", ate_corte)
    console.print("[dim]'Un Fora' = venda com store_id ou nó próprio; 'Un Full' = venda com nó de centro do Full. Só entram vendas com origem conhecida.[/]\n")
    return {"todo": todo, "ate_corte": ate_corte}


# ============================== PARTE 5: nós do banco ==============================

def parte_5_nos(vendas, nos_proprios):
    por_no = defaultdict(lambda: {"un": 0, "proposta": Counter(), "atual": Counter(), "lojas": set(), "primeiro": None, "ultimo": None})
    for l in vendas:
        if not l["node_id"]:
            continue
        b = por_no[l["node_id"]]
        b["un"] += l["quantidade"]
        b["proposta"][l["proposta"]] += l["quantidade"]
        b["atual"][l["atual"]] += l["quantidade"]
        if l["store_id"]:
            b["lojas"].add(l["store_id"])
        b["primeiro"] = l["dia_venda"] if b["primeiro"] is None or l["dia_venda"] < b["primeiro"] else b["primeiro"]
        b["ultimo"] = l["dia_venda"] if b["ultimo"] is None or l["dia_venda"] > b["ultimo"] else b["ultimo"]
    tabela = nova_tabela("Nós (node_id) do banco e o destino de cada um", ("Nó", "left"), ("Un", "right"), ("Hoje a tela diz", "left"),
                         ("Regra proposta diz", "left"), ("Veio com store_id?", "left"), ("De", "right"), ("Até", "right"))
    lista = []
    for no in sorted(por_no, key=lambda x: -por_no[x]["un"]):
        b = por_no[no]
        hoje = NOME_DA_ORIGEM[b["atual"].most_common(1)[0][0]]
        prop = NOME_DA_ORIGEM[b["proposta"].most_common(1)[0][0]]
        mudou = hoje != prop
        nome = mascarar_no(no, nos_proprios)
        tabela.add_row(nome, n(b["un"]), hoje, f"[bold yellow]{prop}[/]" if mudou else prop, "sim" if b["lojas"] else "não", data(b["primeiro"]), data(b["ultimo"]))
        lista.append({"no": nome, "un": b["un"], "hoje": hoje, "proposta": prop, "veio_com_store_id": bool(b["lojas"]),
                      "primeiro_dia": b["primeiro"], "ultimo_dia": b["ultimo"]})
    console.print(tabela)
    console.print("[dim]Amarelo = o destino do nó MUDA. O nó próprio aparece como BRP***1 (o código do vendedor não é mostrado nem gravado).[/]\n")
    resultado["parte_5"] = lista


# ============================== leitura final ==============================

def montar_leitura(p1, p2, p3):
    linhas = []
    total = p1["total"]
    sem_hoje = p1["atual"]["indefinido"]
    linhas.append(f"Hoje {n(sem_hoje)} un ({tpct(sem_hoje, total)} das {n(total)} un) estão em 'Sem origem'.")
    if p2["un_sem"]:
        linhas.append(f"Pela regra 4, {n(p2['para_fora'])} un ({tpct(p2['para_fora'], p2['un_sem'])} das sem origem) vão para Fora do Full (em {n(p2['mlbs_fora'])} MLBs que hoje "
                      f"não são Full e nunca venderam por centro do Full) e {n(p2['continuam'])} un ({tpct(p2['continuam'], p2['un_sem'])}) continuam sem origem "
                      f"(em {n(p2['mlbs_continuam'])} MLBs: anúncio Full, fora do cadastro ou que já vendeu pelo Full).")
        linhas.append("A PARTE 4 não prova a regra 4: antes de 26/03/2026 as vendas de estoque próprio vinham sem origem, então a coluna 'Un Fora' dessa época sai sempre "
                      "pequena. A evidência da regra está por MLB (PARTE 3): 'Full (nó)' zerado = o MLB nunca vendeu por centro do Full.")
    fora_total = p1["proposta"]["fora"]
    linhas.append(f"Fora do Full na proposta: {n(fora_total)} un ({tpct(fora_total, total)} das {n(total)} un).")
    if p3:
        topo = p3[0]
        flex = "com Flex" if topo["flex"] else ("sem Flex" if topo["flex"] is not None else "Flex desconhecido")
        linhas.append(f"O maior anúncio ({topo['mlb']}, {LOGISTICA_CURTA.get(topo['logistica_hoje'], topo['logistica_hoje'])}, {flex}) tem {n(topo['un'])} un = "
                      f"{tpct(topo['un'], total)} das vendas e só {n(topo['fora_na_proposta'])} un Fora ({tpct(topo['fora_na_proposta'], topo['un'])}).")
        full_com_flex = [a for a in p3 if a["logistica_hoje"] == "fulfillment" and a["flex"]]
        if full_com_flex:
            un, fora = sum(a["un"] for a in full_com_flex), sum(a["fora_na_proposta"] for a in full_com_flex)
            linhas.append(f"Anúncios FULL com Flex ligado: {n(len(full_com_flex))} MLBs, {n(un)} un, só {n(fora)} un Fora ({tpct(fora, un)}). Se você esperava mais venda de "
                          f"Flex/Coleta nesses anúncios, o motivo não aparece no banco: só uma amostra de envios (logistic.type) dos pedidos deles mostraria.")
    mudam_para_full = p1["de_para"][("fora", "full")]
    if mudam_para_full:
        linhas.append(f"Trocar a regra do prefixo 'BRP' pelos nós próprios move {n(mudam_para_full)} un de 'Fora do Full' para 'Full' (centros do Full que começam com BRP).")
    linhas.append("Limites: a logística e o Flex do anúncio são os de HOJE (não os do dia da venda) e os nós próprios saíram do banco; na regra final eles viriam do código "
                  "do vendedor ou da lista de depósitos (no máximo 1 chamada por conta).")
    return linhas


def salvar_json():
    CAMINHO_SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main():
    console.print(f"\n[bold]Origem das vendas pela logística do anúncio — conta {CONTA}[/]  [dim](só banco: ZERO chamadas à API)[/]\n")
    vendas = ler_vendas()
    if not vendas:
        console.print("[yellow]Nenhuma venda não cancelada no banco desta conta.[/]")
        return
    anuncios = ler_anuncios({l["mlb"] for l in vendas})
    nos_proprios = preparar(vendas, anuncios)
    resultado["gerado_em"] = datetime.now().isoformat(timespec="seconds")
    resultado["conta"] = CONTA
    resultado["base"] = {"linhas": len(vendas), "un": sum(l["quantidade"] for l in vendas), "primeiro_dia": min(l["dia_venda"] for l in vendas),
                         "ultimo_dia": max(l["dia_venda"] for l in vendas), "mlbs": len({l["mlb"] for l in vendas}), "mlbs_no_cadastro": len(anuncios),
                         "nos_proprios_achados_no_banco": len(nos_proprios)}
    console.print(f"[dim]Lidas {n(len(vendas))} linhas ({n(resultado['base']['un'])} un, {data(resultado['base']['primeiro_dia'])} a "
                  f"{data(resultado['base']['ultimo_dia'])}), {n(resultado['base']['mlbs'])} MLBs ({n(len(anuncios))} no cadastro). "
                  f"Nós próprios achados no banco (nó que veio junto com store_id): {n(len(nos_proprios))}.[/]\n")

    console.rule("PARTE 1 — quanto muda")
    p1 = parte_1_quanto_muda(vendas)
    console.rule("PARTE 2 — as 'Sem origem', pela logística do anúncio")
    p2 = parte_2_sem_origem(vendas)
    console.rule("PARTE 3 — todos os anúncios (MLB)")
    p3 = parte_3_por_mlb(vendas, anuncios)
    console.rule("PARTE 4 — teste de confiança da regra 4")
    p4 = parte_4_confianca(vendas, p2["ultimo_dia"])
    console.rule("PARTE 5 — nós do banco")
    parte_5_nos(vendas, nos_proprios)

    console.rule("LEITURA")
    leitura = montar_leitura(p1, p2, p3)
    for linha in leitura:
        console.print(f"• {linha}")
    resultado["leitura"] = [linha.replace("[yellow]", "").replace("[/]", "") for linha in leitura]
    salvar_json()
    console.print(f"\n[dim]JSON salvo em: {t(CAMINHO_SAIDA.name)}. Chamadas à API: 0. Sem seller_id, sem token, sem dado de comprador.[/]")


if __name__ == "__main__":
    main()
