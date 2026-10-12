# scripts_exploracao_ML/confirmar_origem_das_vendas_pelos_envios.py
#
# Função Objetivo: CONFIRMAR, com o envio de verdade, a regra de origem proposta para a tela de Vendas (Full × Fora do Full). O script sorteia no banco
# 60 vendas JÁ classificadas pela regra proposta (30 "Fora do Full" e 30 "Full"), consulta o envio de cada uma (GET /shipments/{id}) e compara o
# logistic.type do envio com o que a regra disse:
#
#   a regra disse FULL      → o envio tem que ser "fulfillment"
#   a regra disse FORA      → o envio tem que ser QUALQUER OUTRO tipo (cross_docking, self_service, xd_drop_off...), nunca fulfillment
#
# A regra proposta (a mesma de medir_origem_pela_logistica_do_anuncio.py), na ordem:
#   1) tem store_id                                       → Fora do Full
#   2) tem node_id de um depósito do vendedor              → Fora do Full  (o "nó próprio", achado no banco: o nó que veio junto com store_id)
#   3) tem qualquer outro node_id                          → Full
#   4) sem node_id e sem store_id: anúncio que hoje NÃO é Full e que NUNCA vendeu por centro do Full → Fora do Full; senão continua "Sem origem"
#
# Os 60 envios saem de 4 grupos (as quantidades estão na configuração; o que faltar num grupo passa para o outro do mesmo lado):
#   FORA · nó próprio ou loja              15 → confirma as regras 1 e 2
#   FORA · sem origem, pela regra 4        15 → confirma a regra 4 (as vendas de Coleta de antes de 26/03/2026, que vinham sem stock)
#   FULL · nós BRP que a tela de HOJE chama de Fora (BRPE01, BRPR01...)   10 → confirma a regra 3 justamente onde ela MUDA a tela de hoje
#   FULL · demais nós                      20 → confirma a regra 3 no resto, e mostra se há Flex/Coleta "escondido" atrás de nó de Full
#
# REGRAS: só leitura (GET) e só SELECT no banco; nada é gravado no banco. São 60 chamadas (mais as repetições de 429/5xx), 1 por segundo. O seller_id, o
# token e qualquer dado de comprador nunca vão para a tela nem para o JSON; o nó próprio aparece como BRP***1. O JSON é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → Só entram vendas de pedidos com UMA linha no banco e com shipping.id, para o envio dizer a origem daquela venda e de mais nenhuma.
#                  A escolha é determinística (sem sorteio): a lista de cada grupo é ordenada no tempo e o script pega itens igualmente espaçados,
#                  do mais antigo ao mais novo; assim rodar de novo consulta os mesmos pedidos (e a amostra cobre o ano todo).
# * [EXPLICAÇÃO] → Por que não usa chamar_api(): ele repete o 429 sozinho e grava os params no log. Aqui cada tentativa precisa aparecer na tela. Por isso o
#                  script usa a MESMA sessão HTTP e o MESMO gerenciador de token do cliente, com um retry curto próprio (padrão dos outros scripts da pasta).
# * [EXPLICAÇÃO] → "Limite de 95%": se 0 de N envios divergirem, a regra de três diz que, com 95% de confiança, no máximo ~3/N das vendas daquele grupo
#                  podem divergir (30 envios → até ~10%; 20 envios → até ~15%). É a dimensão do que a amostra NÃO consegue excluir.

import json
import os
import shutil
import sys
import time
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

import requests
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from api_mercado_livre.core.auth.gerenciador_token import obter_token_valido
from api_mercado_livre.core.estrutura_api.cliente_api import BASE_URL, TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS, _sessao
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from gestao_vendas.funcoes_auxiliares.vendas_ml import STATUS_CANCELADO, classificar_origem
from mercado_livre.models import AnuncioMercadoLivre, VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale): decide o banco E a conta da API
FORA_DE_NO_PROPRIO_OU_LOJA = 15       # envios de vendas "Fora" que têm nó próprio ou store_id (regras 1 e 2)
FORA_PELA_REGRA_4 = 15                # envios de vendas "Fora" que vieram SEM origem e a regra 4 mandou para Fora
FULL_DE_NO_BRP_QUE_MUDA = 10          # envios de vendas "Full" cujo nó começa com BRP (hoje a tela diz Fora; a regra nova diz Full): BRPE01, BRPR01...
FULL_DOS_DEMAIS_NOS = 20              # envios de vendas "Full" dos demais nós (BRSP10, BRSP11, BRBA02, BRRJ02...)
PAUSA_ENTRE_CHAMADAS_S = 1            # silêncio antes de cada chamada nova (o mesmo ritmo do coletor)
PAUSA_APOS_429_S = 5                  # espera antes de repetir a MESMA chamada depois de 429 / 5xx / falha de rede
MAX_TENTATIVAS_POR_CHAMADA = 6        # tentativas por chamada antes de desistir dela e seguir
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_confirmacao_da_origem_por_envios_{CONTA}.json"
CAMPOS_DA_VENDA = ("order_id", "mlb", "quantidade", "dia_venda", "hora_venda", "node_id", "store_id", "shipping_id")
CAMPOS_DO_ANUNCIO = ("mlb", "tipo_de_anuncio__tipo_logistico")
MLBS_POR_CONSULTA = 500

G_FORA_PROPRIO = "FORA · nó próprio ou loja"
G_FORA_REGRA_4 = "FORA · sem origem (regra 4)"
G_FULL_BRP = "FULL · nós BRP (hoje: Fora)"
G_FULL_DEMAIS = "FULL · demais nós"
LADO = {G_FORA_PROPRIO: "fora", G_FORA_REGRA_4: "fora", G_FULL_BRP: "full", G_FULL_DEMAIS: "full"}
PEDIDO_DE_ENVIOS = {G_FORA_PROPRIO: FORA_DE_NO_PROPRIO_OU_LOJA, G_FORA_REGRA_4: FORA_PELA_REGRA_4, G_FULL_BRP: FULL_DE_NO_BRP_QUE_MUDA, G_FULL_DEMAIS: FULL_DOS_DEMAIS_NOS}

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(100, 24)).columns - 1, 40))
t = escape
user_id = None
chamadas = []                         # 1 dict por TENTATIVA (vai para o JSON, sem o corpo da resposta)
ultimo_fim = {"t": None}


# ============================== utilitários ==============================

def sem_id(texto):
    """Troca o seller_id por *** antes de mostrar qualquer texto que veio da API."""
    texto = str(texto)
    return texto.replace(str(user_id), "***") if user_id else texto


def dig(obj, *caminho):
    """Entra em dicts aninhados sem estourar: dig(envio, 'logistic', 'type')."""
    for chave in caminho:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(chave)
    return obj


def mascarar_no(no, nos_proprios=()):
    """O nó próprio é 'BRP' + código do vendedor + '1': mostra BRP***1. Nó longo demais para ser de centro do Full também é mascarado."""
    if not no:
        return "(sem node_id)"
    if no in nos_proprios or len(no) > 8 or (user_id and str(user_id) in no):
        return no[:3] + "***" + no[-1:]
    return no


def n(valor):
    return f"{valor:,}".replace(",", ".")


def data(dia):
    return dia.strftime("%d/%m/%Y") if dia else "-"


# ============================== o banco e a regra proposta ==============================

def ler_vendas():
    """Vendas NÃO canceladas, 1 dict por linha (só os campos usados). Só SELECT, em blocos de 5000."""
    consulta = VendaItemMercadoLivre.objects.exclude(status=STATUS_CANCELADO).values_list(*CAMPOS_DA_VENDA).iterator(chunk_size=5000)
    return [dict(zip(CAMPOS_DA_VENDA, linha)) for linha in consulta]


def ler_logistica_dos_anuncios(mlbs):
    """{mlb: tipo_logistico de HOJE do anúncio}. MLB fora do cadastro (ou sem tipo) fica fora do dict."""
    lista, saida = sorted(mlbs), {}
    for inicio in range(0, len(lista), MLBS_POR_CONSULTA):
        consulta = AnuncioMercadoLivre.objects.filter(mlb__in=lista[inicio:inicio + MLBS_POR_CONSULTA]).values_list(*CAMPOS_DO_ANUNCIO)
        for mlb, logistica in consulta:
            if logistica:
                saida[mlb] = logistica
    return saida


def aplicar_regra_proposta(vendas, logistica_do_anuncio):
    """Põe em cada linha: 'atual' (regra de hoje da tela), 'proposta' (full / fora / indefinido) e 'origem_conhecida'. Devolve os nós próprios achados."""
    nos_proprios = {l["node_id"] for l in vendas if l["store_id"] and l["node_id"]}
    mlbs_que_ja_venderam_pelo_full = {l["mlb"] for l in vendas if l["node_id"] and not l["store_id"] and l["node_id"] not in nos_proprios}
    for l in vendas:
        l["atual"] = classificar_origem(l["node_id"], l["store_id"])
        l["origem_conhecida"] = bool(l["node_id"] or l["store_id"])
        if l["store_id"]:
            l["proposta"] = "fora"
        elif l["node_id"]:
            l["proposta"] = "fora" if l["node_id"] in nos_proprios else "full"
        else:
            logistica = logistica_do_anuncio.get(l["mlb"])
            decide = logistica is not None and logistica != "fulfillment" and l["mlb"] not in mlbs_que_ja_venderam_pelo_full
            l["proposta"] = "fora" if decide else "indefinido"
    return nos_proprios


# ============================== a escolha dos 60 pedidos ==============================

def espalhar(lista, quantos):
    """`quantos` itens de uma lista já ordenada no tempo, igualmente espaçados (do mais antigo ao mais novo)."""
    if quantos <= 0 or not lista:
        return []
    if quantos >= len(lista):
        return list(lista)
    return [lista[int((i + 0.5) * len(lista) / quantos)] for i in range(quantos)]


def espalhar_por_no(lista, quantos):
    """Como `espalhar`, mas dividindo a cota por igual entre os nós (BRPE01 e BRPR01 entram os dois), cada nó espalhado no tempo."""
    por_no = defaultdict(list)
    for l in lista:
        por_no[l["node_id"]].append(l)
    nos = sorted(por_no, key=lambda x: -len(por_no[x]))
    cotas = {no: 0 for no in nos}
    restante = min(quantos, len(lista))
    while restante > 0:
        for no in nos:
            if restante > 0 and cotas[no] < len(por_no[no]):
                cotas[no] += 1
                restante -= 1
    escolhidos = []
    for no in nos:
        escolhidos += espalhar(por_no[no], cotas[no])
    return sorted(escolhidos, key=lambda x: (x["dia_venda"], x["hora_venda"] or 0, x["order_id"]))


def candidatos_por_grupo(vendas):
    """{grupo: [linhas elegíveis, em ordem de tempo]}: pedido com 1 linha só no banco, com shipping.id, e já classificado pela regra proposta."""
    linhas_por_pedido = Counter(l["order_id"] for l in vendas)
    grupos = {g: [] for g in LADO}
    for l in sorted(vendas, key=lambda x: (x["dia_venda"], x["hora_venda"] or 0, x["order_id"])):
        if not l["shipping_id"] or linhas_por_pedido[l["order_id"]] != 1:
            continue
        if l["proposta"] == "fora":
            grupos[G_FORA_PROPRIO if l["origem_conhecida"] else G_FORA_REGRA_4].append(l)
        elif l["proposta"] == "full":
            grupos[G_FULL_BRP if l["atual"] == "fora" else G_FULL_DEMAIS].append(l)
    return grupos


def quantidades_a_consultar(candidatos):
    """Quanto consultar em cada grupo: o pedido da configuração; se um grupo não tem pedidos suficientes, a sobra passa para o outro do mesmo lado."""
    quantas = {g: min(len(candidatos[g]), PEDIDO_DE_ENVIOS[g]) for g in LADO}
    for a, b in ((G_FORA_PROPRIO, G_FORA_REGRA_4), (G_FULL_BRP, G_FULL_DEMAIS)):
        sobra_a, sobra_b = PEDIDO_DE_ENVIOS[a] - quantas[a], PEDIDO_DE_ENVIOS[b] - quantas[b]
        quantas[b] = min(len(candidatos[b]), quantas[b] + sobra_a)
        quantas[a] = min(len(candidatos[a]), quantas[a] + sobra_b)
    return quantas


def escolher_pedidos(candidatos, quantas):
    escolhidos = []
    for grupo in LADO:
        lista = candidatos[grupo]
        sorteados = espalhar_por_no(lista, quantas[grupo]) if grupo == G_FULL_BRP else espalhar(lista, quantas[grupo])
        escolhidos += [(grupo, l) for l in sorteados]
    return escolhidos


# ============================== a API (só GET) ==============================

def esperar_ate(segundos):
    if ultimo_fim["t"] is None:
        return
    falta = segundos - (time.perf_counter() - ultimo_fim["t"])
    if falta > 0:
        time.sleep(falta)


def erro_curto(resposta):
    """A mensagem curta do erro da API (message/error/status/cause), sem o seller_id."""
    try:
        corpo = resposta.json()
    except ValueError:
        return sem_id(resposta.text[:200])
    if isinstance(corpo, dict):
        return sem_id(json.dumps({k: str(corpo[k])[:200] for k in ("message", "error", "status", "cause") if k in corpo}, ensure_ascii=False))
    return sem_id(str(corpo)[:200])


def chamar_uma_vez(rotulo, caminho, tentativa):
    """1 GET /shipments/{id}, 1 tentativa. Registra em `chamadas`; o corpo da resposta fica só em registro['_corpo'] (nunca vai para o JSON)."""
    registro = {"n": len(chamadas) + 1, "rotulo": rotulo, "tentativa": tentativa, "hora_local": datetime.now().astimezone().isoformat(timespec="seconds"),
                "http": None, "ms": None, "erro": None, "_corpo": None}
    cabecalhos = {"Authorization": f"Bearer {obter_token_valido(CONTA)}", "x-format-new": "true"}
    inicio = time.perf_counter()
    try:
        resposta = _sessao.get(f"{BASE_URL}{caminho}", headers=cabecalhos, timeout=(TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS))
    except requests.exceptions.RequestException as erro:
        registro["erro"] = f"{type(erro).__name__} (sem resposta)"
        resposta = None
    registro["ms"] = round((time.perf_counter() - inicio) * 1000)
    ultimo_fim["t"] = time.perf_counter()
    if resposta is not None:
        registro["http"] = resposta.status_code
        if resposta.status_code == 200:
            try:
                registro["_corpo"] = resposta.json()
            except ValueError:
                registro["erro"] = "200 sem JSON válido"
        else:
            registro["erro"] = erro_curto(resposta)
    chamadas.append(registro)
    cor = "green" if registro["http"] == 200 else "red" if registro["http"] == 429 else "yellow" if registro["http"] == 404 else "magenta"
    console.print(f"    [dim]#{registro['n']:<3} {registro['hora_local'][11:19]} envio t{tentativa}[/] [{cor}]HTTP {registro['http'] if registro['http'] is not None else '---'}[/] "
                  f"{registro['ms']} ms · [dim]{t(rotulo)}[/]" + (f" · {t(registro['erro'][:100])}" if registro["erro"] else ""))
    return registro


def chamar_com_repeticao(rotulo, caminho):
    """Chama e, se der 429 / 5xx / falha de rede, espera PAUSA_APOS_429_S e repete a MESMA chamada (cada tentativa fica registrada)."""
    esperar_ate(PAUSA_ENTRE_CHAMADAS_S)
    tentativa = 1
    registro = chamar_uma_vez(rotulo, caminho, tentativa)
    while (registro["http"] is None or registro["http"] == 429 or registro["http"] >= 500) and tentativa < MAX_TENTATIVAS_POR_CHAMADA:
        time.sleep(PAUSA_APOS_429_S)
        tentativa += 1
        registro = chamar_uma_vez(rotulo, caminho, tentativa)
    if registro["http"] == 401:
        console.print("[bold red]401: o Mercado Livre recusou o token. Exploração interrompida.[/]")
        raise SystemExit(1)
    return registro


def consultar_envios(escolhidos, nos_proprios):
    """Consulta o envio de cada pedido escolhido e compara o logistic.type com o que a regra disse. Devolve 1 dict por pedido."""
    resultados = []
    for numero, (grupo, l) in enumerate(escolhidos, 1):
        r = chamar_com_repeticao(f"{numero}/{len(escolhidos)} {grupo}", f"/shipments/{l['shipping_id']}")
        item = {"grupo": grupo, "lado": LADO[grupo], "order_id": l["order_id"], "mlb": l["mlb"], "dia_venda": l["dia_venda"], "quantidade": l["quantidade"],
                "node_id_do_pedido": mascarar_no(l["node_id"], nos_proprios), "tem_store_id": bool(l["store_id"]), "http": r["http"], "erro": r["erro"],
                "logistic_type": None, "logistic_mode": None, "status_do_envio": None, "origin_node_id": None, "confere": None}
        corpo = r["_corpo"]
        if r["http"] == 200 and isinstance(corpo, dict):
            tipo = dig(corpo, "logistic", "type") or corpo.get("logistic_type")
            item.update({"logistic_type": tipo, "logistic_mode": dig(corpo, "logistic", "mode"), "status_do_envio": corpo.get("status"),
                         "origin_node_id": mascarar_no(dig(corpo, "origin", "node", "node_id"), nos_proprios) if dig(corpo, "origin", "node", "node_id") else None})
            if tipo:
                item["confere"] = (tipo == "fulfillment") if item["lado"] == "full" else (tipo != "fulfillment")
        resultados.append(item)
    return resultados


# ============================== o que mostrar ==============================

def nova_tabela(titulo, *colunas):
    tabela = Table(title=titulo, title_justify="left", box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
    for nome, alinhamento in colunas:
        tabela.add_column(nome, justify=alinhamento, no_wrap=(alinhamento == "right"))
    return tabela


def mostrar_o_que_sera_consultado(candidatos, quantas):
    tabela = nova_tabela("Os 60 envios: de onde saem", ("Grupo", "left"), ("A regra diz", "left"), ("Pedidos elegíveis", "right"), ("Vão ser consultados", "right"),
                         ("De", "right"), ("Até", "right"))
    for grupo in LADO:
        lista = candidatos[grupo]
        tabela.add_row(grupo, "Fora do Full" if LADO[grupo] == "fora" else "Full", n(len(lista)), n(quantas[grupo]),
                       data(lista[0]["dia_venda"]) if lista else "-", data(lista[-1]["dia_venda"]) if lista else "-")
    tabela.add_row("Total", "", n(sum(len(v) for v in candidatos.values())), n(sum(quantas.values())), "", "")
    console.print(tabela)
    console.print("[dim]Elegível = pedido com 1 linha no banco, com shipping.id, e já classificado pela regra proposta.[/]\n")


def resumo_por_grupo(resultados):
    por_grupo = {}
    for grupo in LADO:
        do_grupo = [r for r in resultados if r["grupo"] == grupo]
        com_resposta = [r for r in do_grupo if r["confere"] is not None]
        por_grupo[grupo] = {
            "lado": LADO[grupo], "consultados": len(do_grupo), "com_resposta": len(com_resposta), "sem_resposta": len(do_grupo) - len(com_resposta),
            "confere": sum(1 for r in com_resposta if r["confere"]), "nao_confere": sum(1 for r in com_resposta if not r["confere"]),
            "tipos": dict(Counter(r["logistic_type"] for r in com_resposta)),
        }
    return por_grupo


def mostrar_resultado(resultados, por_grupo):
    tabela = nova_tabela("Resultado: o envio confirma a regra?", ("Grupo", "left"), ("A regra diz", "left"), ("Esperado no envio", "left"), ("Consultados", "right"),
                         ("Confere", "right"), ("NÃO confere", "right"), ("Sem resposta", "right"), ("logistic.type encontrado", "left"))
    for grupo, g in por_grupo.items():
        tipos = " · ".join(f"{tipo} ×{q}" for tipo, q in sorted(g["tipos"].items(), key=lambda x: -x[1])) or "(nenhum envio respondeu)"
        cor = "green" if g["com_resposta"] and not g["nao_confere"] else "bold red" if g["nao_confere"] else "yellow"
        tabela.add_row(grupo, "Fora do Full" if g["lado"] == "fora" else "Full", "qualquer tipo ≠ fulfillment" if g["lado"] == "fora" else "fulfillment",
                       n(g["consultados"]), f"[{cor}]{n(g['confere'])}[/]", f"[{cor}]{n(g['nao_confere'])}[/]" if g["nao_confere"] else "0", n(g["sem_resposta"]), t(tipos))
    total_resp = sum(g["com_resposta"] for g in por_grupo.values())
    total_ok = sum(g["confere"] for g in por_grupo.values())
    tabela.add_row("Total", "", "", n(sum(g["consultados"] for g in por_grupo.values())), n(total_ok), n(total_resp - total_ok), n(sum(g["sem_resposta"] for g in por_grupo.values())), "")
    console.print(tabela)

    divergentes = [r for r in resultados if r["confere"] is False]
    if divergentes:
        div = nova_tabela("Os envios que NÃO confirmam a regra", ("Grupo", "left"), ("Pedido", "right"), ("Data", "right"), ("MLB", "left"), ("Nó do pedido", "left"),
                          ("logistic.type", "left"), ("mode", "left"), ("Nó de origem do envio", "left"))
        for r in divergentes:
            div.add_row(r["grupo"], str(r["order_id"]), data(r["dia_venda"]), r["mlb"], t(r["node_id_do_pedido"]), t(str(r["logistic_type"])), t(str(r["logistic_mode"] or "-")),
                        t(str(r["origin_node_id"] or "-")))
        console.print(div)
    sem_resposta = [r for r in resultados if r["confere"] is None]
    if sem_resposta:
        console.print(f"[yellow]{n(len(sem_resposta))} envio(s) sem resposta útil (HTTP: {', '.join(sorted({str(r['http']) for r in sem_resposta}))}); não entram na conta.[/]")

    origem = defaultdict(Counter)
    for r in resultados:
        if r["confere"] is not None:
            origem[r["grupo"]]["origin.node do envio = nó do pedido" if r["origin_node_id"] and r["origin_node_id"] == r["node_id_do_pedido"]
                                else "envio sem origin.node" if not r["origin_node_id"] else "origin.node diferente do pedido"] += 1
    linha = nova_tabela("O nó de origem que o envio informa", ("Grupo", "left"), ("Leitura", "left"), ("Envios", "right"))
    for grupo in LADO:
        for leitura, q in sorted(origem[grupo].items(), key=lambda x: -x[1]):
            linha.add_row(grupo, leitura, n(q))
    console.print(linha)
    console.print()


def montar_leitura(por_grupo):
    linhas = []
    for grupo, g in por_grupo.items():
        if not g["com_resposta"]:
            linhas.append(f"{grupo}: nenhum envio respondeu; este grupo ficou sem confirmação.")
            continue
        esperado = "fulfillment" if g["lado"] == "full" else "um tipo diferente de fulfillment"
        if g["sem_resposta"]:
            linhas.append(f"{grupo}: {n(g['sem_resposta'])} envio(s) não responderam e ficaram fora da conta abaixo.")
        if not g["nao_confere"]:
            limite = 300 / g["com_resposta"]
            linhas.append(f"{grupo}: {n(g['confere'])} de {n(g['com_resposta'])} envios eram {esperado} — a regra acertou em todos. Com essa amostra, no máximo "
                          f"~{limite:.0f}% das vendas do grupo poderiam divergir (95% de confiança).")
        else:
            tipos = ", ".join(f"{tipo} ×{q}" for tipo, q in sorted(g["tipos"].items(), key=lambda x: -x[1]) if (tipo == "fulfillment") != (g["lado"] == "full"))
            linhas.append(f"[bold red]{grupo}: {n(g['nao_confere'])} de {n(g['com_resposta'])} envios NÃO eram {esperado}[/] (encontrado: {tipos}). Ver a tabela dos divergentes: "
                          f"a regra precisa de ajuste para esse grupo.")
    total_resp = sum(g["com_resposta"] for g in por_grupo.values())
    total_ok = sum(g["confere"] for g in por_grupo.values())
    linhas.append(f"No total, a regra foi confirmada em {n(total_ok)} de {n(total_resp)} envios com resposta.")
    linhas.append("Limites: são 60 pedidos de 1 produto; mostram se a regra erra de forma relevante, não provam que nunca erra. A regra 4 depende da logística de HOJE do anúncio.")
    return linhas


def salvar_json(candidatos, quantas, resultados, por_grupo, leitura):
    saida = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"), "conta": CONTA,
        "config": {"fora_de_no_proprio_ou_loja": FORA_DE_NO_PROPRIO_OU_LOJA, "fora_pela_regra_4": FORA_PELA_REGRA_4, "full_de_no_brp_que_muda": FULL_DE_NO_BRP_QUE_MUDA,
                   "full_dos_demais_nos": FULL_DOS_DEMAIS_NOS, "pausa_entre_chamadas_s": PAUSA_ENTRE_CHAMADAS_S},
        "grupos": {g: {"elegiveis": len(candidatos[g]), "consultados": quantas[g]} for g in LADO},
        "resumo_por_grupo": por_grupo, "envios": resultados, "leitura": [x.replace("[bold red]", "").replace("[/]", "") for x in leitura],
        "chamadas": [{k: v for k, v in c.items() if k != "_corpo"} for c in chamadas],
    }
    texto = json.dumps(saida, ensure_ascii=False, indent=2, default=str)
    if user_id and str(user_id) in texto:          # rede de segurança: o id nunca deveria estar aqui
        texto = texto.replace(str(user_id), "***")
    CAMINHO_SAIDA.write_text(texto, encoding="utf-8")


def mostrar_chamadas():
    if not chamadas:
        return
    http = Counter(c["http"] for c in chamadas)
    console.print("Chamadas à API (cada tentativa conta): " + t(" · ".join(f"HTTP {codigo}: {q}" for codigo, q in sorted(http.items(), key=lambda x: str(x[0])))) + f" · total {n(len(chamadas))}")


def main():
    global user_id
    load_dotenv(dotenv_path=_RAIZ_DO_PROJETO / ".env")
    user_id = (os.getenv(f"{CONTA}_USER_ID") or "").strip() or None    # carregado já aqui para mascarar o seller_id (ele aparece dentro do nó próprio: BRP<seller_id>1)
    console.print(f"\n[bold]Confirmação da regra de origem pelos envios[/] · conta {CONTA} · só leitura (SELECT no banco, GET na API)\n")
    if not user_id:
        console.print(f"[bold red]{CONTA}_USER_ID não encontrado no .env da raiz do repo: sem ele não dá para mascarar o seller_id. Nada foi consultado.[/]")
        return
    vendas = ler_vendas()
    if not vendas:
        console.print("[yellow]Nenhuma venda não cancelada no banco desta conta.[/]")
        return
    nos_proprios = aplicar_regra_proposta(vendas, ler_logistica_dos_anuncios({l["mlb"] for l in vendas}))
    console.print(f"[dim]Lidas {n(len(vendas))} linhas ({data(min(l['dia_venda'] for l in vendas))} a {data(max(l['dia_venda'] for l in vendas))}). "
                  f"Nós próprios achados no banco (nó que veio junto com store_id): {n(len(nos_proprios))}.[/]\n")
    candidatos = candidatos_por_grupo(vendas)
    quantas = quantidades_a_consultar(candidatos)
    mostrar_o_que_sera_consultado(candidatos, quantas)
    escolhidos = escolher_pedidos(candidatos, quantas)
    if not escolhidos:
        console.print("[yellow]Nenhum pedido elegível para consultar.[/]")
        return
    console.rule("[bold]Consultando os envios")
    console.print(f"{len(escolhidos)} chamadas, 1 por segundo (~{len(escolhidos) // 60 + 1} min); cada 429/5xx repete a MESMA chamada (até {MAX_TENTATIVAS_POR_CHAMADA} tentativas) e aparece abaixo.")
    resultados = []
    try:
        resultados = consultar_envios(escolhidos, nos_proprios)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Interrompido (Ctrl+C). Nada foi gravado no banco.[/]")
    finally:
        if resultados:
            console.rule("[bold]Resultado")
            por_grupo = resumo_por_grupo(resultados)
            mostrar_resultado(resultados, por_grupo)
            console.rule("[bold]Leitura")
            leitura = montar_leitura(por_grupo)
            for linha in leitura:
                console.print(f"• {linha}")
            salvar_json(candidatos, quantas, resultados, por_grupo, leitura)
            console.print()
        mostrar_chamadas()
        if resultados:
            console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem seller_id, sem token, sem dado de comprador.")


if __name__ == "__main__":
    main()
