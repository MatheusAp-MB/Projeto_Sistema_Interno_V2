# scripts_exploracao_ML/explorar_orders_search_para_historico_de_vendas.py
#
# Função Objetivo: MEDIR, com dado real e só em leitura (GET), o que o GET /orders/search entrega para montar o histórico e o
# calendário de vendas de MUITOS produtos (mais de mil SKUs) — o caminho que substituiu o endpoint de operações do Full (abandonado
# em 10/10/2026, 20:04: ver as notas em Historico_de_Vendas/ no vault). O script responde as perguntas ainda abertas:
#   1) Que campos o pedido traz (SKU, MLB, quantidade, datas, status, tags, stock.node_id, envio)? Quantas vendas "ontem"?
#   2) Quantos pedidos existem em 7, 30, 90, 180 e 360 dias (paging.total)? Esse número diz quantas páginas de 50 a coleta custaria
#      e se dá para ir a 6 ou 12 meses.
#   3) Até onde o 'offset' vai? (a doc não diz) — por isso 1 ou 2 chamadas em offsets fundos da maior janela.
#   4) O stock.node_id do pedido separa venda do Full de venda fora do Full? Compara, em cerca de 20 pedidos de ontem, o node_id do
#      pedido com o logistic.type do envio (GET /shipments/{id}).
#   5) Pedidos cancelados aparecem na busca como vendedor? (a doc diz que são filtrados) — 1 chamada com order.status=cancelled
#      e a contagem dos status que vêm na busca normal.
#   6) O dia da venda muda conforme se usa date_created ou date_closed? (quantos pedidos trocam de dia, no horário de Brasília)
#
# REGRAS: só leitura (GET). Não toca no banco. O seller_id e o token nunca vão para a tela nem para o JSON; nenhum dado de comprador
# é guardado (só os NOMES dos campos do comprador são contados, nunca os valores). O JSON é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → Por que não usa chamar_api(): ele tenta de novo sozinho quando recebe 429 e grava os params (com o seller_id) no log.
#                  Aqui cada tentativa precisa aparecer (para medir a taxa de 429 deste endpoint) e o seller_id não pode ir para
#                  nenhum arquivo. Por isso o script usa a MESMA sessão HTTP e o MESMO gerenciador de token do cliente, e faz o
#                  seu próprio retry curto (espera PAUSA_APOS_429_S s e repete, até MAX_TENTATIVAS_POR_CHAMADA), registrando CADA
#                  tentativa. Só vale para exploração.

import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.auth.gerenciador_token import obter_token_valido
from api_mercado_livre.core.estrutura_api.cliente_api import BASE_URL, TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS, _sessao

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale)
JANELAS_DE_TOTAL_EM_DIAS = [7, 30, 90, 180, 360]   # 1 chamada cada (só a página 1, para ler paging.total)
LIMITE_POR_PAGINA = 50                # tamanho de página já observado em /orders/search
MAX_PAGINAS_DE_ONTEM = 40             # trava de segurança (40 x 50 = 2000 pedidos)
PEDIDOS_PARA_CONSULTAR_ENVIO = 20     # quantos GET /shipments/{id} (1 por pedido da amostra)
TESTAR_OFFSET_PROFUNDO = True         # 1 ou 2 chamadas em offsets fundos da maior janela (0 chamadas se False)
PAUSA_ENTRE_CHAMADAS_S = 1            # silêncio antes de cada chamada nova (o mesmo ritmo do coletor)
PAUSA_APOS_429_S = 5                  # espera antes de repetir a MESMA chamada depois de 429 / erro 5xx / falha de rede
MAX_TENTATIVAS_POR_CHAMADA = 6        # tentativas por chamada antes de desistir dela e seguir
# ========================================

ENDPOINT_PEDIDOS = "/orders/search"
ROTULO_SEM_NODE = "(sem node_id)"
PADROES_DE_CABECALHO_DE_LIMITE = ("rate", "limit", "retry", "remaining", "reset", "quota", "throttl", "wait")
FUSO = ZoneInfo("America/Sao_Paulo")
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_orders_search_{CONTA}.json"

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(80, 24)).columns - 1, 20))
t = escape
user_id = None
chamadas = []                         # 1 dict por TENTATIVA (vai para o JSON, sem o corpo da resposta)
ultimo_fim = {"t": None}


def sem_id(texto):
    """Troca o seller_id por *** antes de mostrar qualquer texto que veio da API."""
    texto = str(texto)
    return texto.replace(str(user_id), "***") if user_id else texto


def formatar_data_para_filtro(instante):
    """Mesmo formato que já deu 200 OK em /orders/search (ex: 2026-10-10T00:00:00.000-0300)."""
    texto = instante.isoformat(timespec="milliseconds")
    return texto[:-6] + texto[-6:].replace(":", "")


def ler_data(texto):
    """Data da API (ex: 2026-10-10T08:27:04.000-04:00) -> datetime no horário de Brasília."""
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto).astimezone(FUSO)
    except ValueError:
        return None


def janela_de_dias_completos(dias, meia_noite_de_hoje):
    """Os N dias completos (00h a 24h, horário de Brasília) que terminam na meia-noite de hoje."""
    return meia_noite_de_hoje - timedelta(days=dias), meia_noite_de_hoje


def params_de_pedidos(inicio, fim, offset=0, limite=LIMITE_POR_PAGINA, status=None):
    params = {
        "seller": user_id,
        "order.date_created.from": formatar_data_para_filtro(inicio),
        "order.date_created.to": formatar_data_para_filtro(fim),
        "sort": "date_desc",
        "limit": limite,
    }
    if status:
        params["order.status"] = status
    if offset:
        params["offset"] = offset
    return params


def esperar_ate(segundos_desde_a_ultima_chamada):
    """Garante pelo menos N segundos de silêncio desde o fim da chamada anterior."""
    if ultimo_fim["t"] is None:
        return
    falta = segundos_desde_a_ultima_chamada - (time.perf_counter() - ultimo_fim["t"])
    if falta > 0:
        time.sleep(falta)


def cabecalhos_de_interesse(resposta):
    """Só os cabeçalhos que falam de limite/espera. Nunca o resto dos valores."""
    achados = {}
    for nome, valor in resposta.headers.items():
        if any(p in nome.lower() for p in PADROES_DE_CABECALHO_DE_LIMITE):
            achados[nome] = str(valor)[:120]
    return achados


def erro_curto(resposta):
    """A mensagem curta do erro da API (message/error/status/cause), sem o seller_id. Nada além disso."""
    try:
        corpo = resposta.json()
    except ValueError:
        return sem_id(resposta.text[:200])
    if isinstance(corpo, dict):
        partes = {k: str(corpo[k])[:200] for k in ("message", "error", "status", "cause") if k in corpo}
        return sem_id(json.dumps(partes, ensure_ascii=False))
    return sem_id(str(corpo)[:200])


def chamar_uma_vez(tipo, rotulo, caminho, params, tentativa, headers_extra=None):
    """1 GET, 1 tentativa. Registra em `chamadas` e devolve o registro (o corpo da resposta fica só em registro['_corpo'])."""
    desde_a_anterior = None if ultimo_fim["t"] is None else round(time.perf_counter() - ultimo_fim["t"], 1)
    registro = {
        "n": len(chamadas) + 1, "tipo": tipo, "rotulo": rotulo, "tentativa": tentativa,
        "hora_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "segundos_desde_o_fim_da_anterior": desde_a_anterior,
        "http": None, "ms": None, "total": None, "linhas": None, "erro": None, "cabecalhos_de_limite": {}, "_corpo": None,
    }
    cabecalhos = {"Authorization": f"Bearer {obter_token_valido(CONTA)}"}
    cabecalhos.update(headers_extra or {})
    inicio = time.perf_counter()
    try:
        resposta = _sessao.get(
            f"{BASE_URL}{caminho}", params=params, headers=cabecalhos,
            timeout=(TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS),
        )
    except requests.exceptions.RequestException as erro:
        registro["erro"] = f"{type(erro).__name__} (sem resposta)"
        resposta = None
    registro["ms"] = round((time.perf_counter() - inicio) * 1000)
    ultimo_fim["t"] = time.perf_counter()
    if resposta is not None:
        registro["http"] = resposta.status_code
        registro["cabecalhos_de_limite"] = cabecalhos_de_interesse(resposta)
        if resposta.status_code == 200:
            try:
                corpo = resposta.json()
                registro["_corpo"] = corpo
                paging = corpo.get("paging") or {} if isinstance(corpo, dict) else {}
                registro["total"] = paging.get("total")
                registro["linhas"] = len(corpo.get("results") or []) if isinstance(corpo, dict) else None
            except ValueError:
                registro["erro"] = "200 sem JSON válido"
        else:
            registro["erro"] = erro_curto(resposta)
    chamadas.append(registro)
    mostrar_linha(registro)
    return registro


def deve_repetir(registro):
    http = registro["http"]
    return http is None or http == 429 or http >= 500


def chamar_com_repeticao(tipo, rotulo, caminho, params, headers_extra=None):
    """Chama e, se der 429 / 5xx / falha de rede, espera PAUSA_APOS_429_S e repete a MESMA chamada (cada tentativa fica registrada)."""
    esperar_ate(PAUSA_ENTRE_CHAMADAS_S)
    tentativa = 1
    registro = chamar_uma_vez(tipo, rotulo, caminho, params, tentativa, headers_extra)
    while deve_repetir(registro) and tentativa < MAX_TENTATIVAS_POR_CHAMADA:
        time.sleep(PAUSA_APOS_429_S)
        tentativa += 1
        registro = chamar_uma_vez(tipo, rotulo, caminho, params, tentativa, headers_extra)
    if registro["http"] == 401:
        console.print("[bold red]401: o Mercado Livre recusou o token. Exploração interrompida.[/]")
        raise SystemExit(1)
    registro["desistiu"] = deve_repetir(registro)
    return registro


def cor_do_status(http):
    if http == 200:
        return "green"
    if http == 429:
        return "red"
    if http == 404:
        return "yellow"
    return "magenta"


def mostrar_linha(registro):
    """1 linha por tentativa, na hora em que ela acontece."""
    http = registro["http"]
    detalhe = ""
    if http == 200:
        detalhe = f"total={registro['total']} linhas={registro['linhas']}"
    elif registro["erro"]:
        detalhe = t(registro["erro"][:100])
    console.print(
        f"  #{registro['n']:<3} {registro['hora_local'][11:19]}  {registro['tipo']:<17} {t(registro['rotulo'])[:34]:<34} "
        f"t{registro['tentativa']} [{cor_do_status(http)}]HTTP {http if http is not None else '---'}[/]  {registro['ms']} ms  {detalhe}"
    )


# ============================== PARTE 2: análise dos pedidos e passos ==============================

resultado = {}                        # tudo o que vai para o JSON (sem seller_id, sem token, sem dado de comprador)


def dig(obj, *caminho):
    """Entra em dicts aninhados sem estourar: dig(pedido, 'shipping', 'id')."""
    for chave in caminho:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(chave)
    return obj


def nomes_das_chaves(obj):
    """Só os NOMES das chaves de um dict (nunca os valores). Serve até para o comprador."""
    return sorted(obj.keys()) if isinstance(obj, dict) else []


def contar(contador):
    """Counter -> dict ordenado do mais frequente para o menos."""
    return {str(chave): qtd for chave, qtd in contador.most_common()}


def percentil(valores, p):
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(len(ordenados) * p))]


def texto_de_contagem(contagem, limite=12):
    """{'a': 10, 'b': 3} -> 'a=10 · b=3' (corta em `limite` itens)."""
    itens = list(contagem.items())
    texto = " · ".join(f"{chave}={qtd}" for chave, qtd in itens[:limite])
    return texto + (f" · (+{len(itens) - limite})" if len(itens) > limite else "")


def pagina_de_pedidos(inicio, fim, offset, rotulo, status=None, limite=LIMITE_POR_PAGINA):
    return chamar_com_repeticao("pedidos", rotulo, ENDPOINT_PEDIDOS,
                                params_de_pedidos(inicio, fim, offset=offset, limite=limite, status=status))


def analisar_pedidos(pedidos):
    """Mede a FORMA dos pedidos. Guarda só contagens, nomes de campos e valores de produto/data. Nunca valor de comprador."""
    chaves = {nome: Counter() for nome in ("pedido", "item_do_pedido", "item", "stock", "comprador", "envio", "pagamento")}
    status, tags, canal, nodes, lojas, quantidades = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    itens_por_pedido, fusos_das_datas = Counter(), Counter()
    sku_para_mlbs, mlbs, atrasos = defaultdict(set), set(), []
    n = Counter()
    ids = set()
    for pedido in pedidos:
        ids.add(pedido.get("id"))
        chaves["pedido"].update(nomes_das_chaves(pedido))
        chaves["comprador"].update(nomes_das_chaves(pedido.get("buyer")))
        chaves["envio"].update(nomes_das_chaves(pedido.get("shipping")))
        for pagamento in pedido.get("payments") or []:
            chaves["pagamento"].update(nomes_das_chaves(pagamento))
        status[str(pedido.get("status"))] += 1
        tags.update(pedido.get("tags") or [])
        canal[str(dig(pedido, "context", "channel"))] += 1
        n["com_pack_id"] += pedido.get("pack_id") is not None
        n["sem_shipping_id"] += not dig(pedido, "shipping", "id")
        itens = pedido.get("order_items") or []
        itens_por_pedido[len(itens)] += 1
        n["pedidos_com_mais_de_1_item"] += len(itens) > 1
        for item in itens:
            n["itens"] += 1
            chaves["item_do_pedido"].update(nomes_das_chaves(item))
            chaves["item"].update(nomes_das_chaves(item.get("item")))
            quantidades[str(item.get("quantity"))] += 1
            n["itens_quantidade_maior_que_1"] += (item.get("quantity") or 0) > 1
            mlb, sku = dig(item, "item", "id"), dig(item, "item", "seller_sku")
            if mlb:
                mlbs.add(mlb)
            n["itens_com_seller_sku"] += bool(sku)
            n["itens_com_seller_custom_field"] += bool(dig(item, "item", "seller_custom_field"))
            n["itens_com_variation_id"] += dig(item, "item", "variation_id") is not None
            if sku and mlb:
                sku_para_mlbs[sku].add(mlb)
            estoque = item.get("stock")
            if estoque is None:
                n["itens_sem_stock"] += 1
            else:
                chaves["stock"].update(nomes_das_chaves(estoque))
                nodes[str(estoque.get("node_id"))] += 1
                lojas[str(estoque.get("store_id"))] += 1
        criado_txt, fechado_txt = pedido.get("date_created"), pedido.get("date_closed")
        for texto in (criado_txt, fechado_txt):
            if texto and len(texto) > 6:
                fusos_das_datas[texto[-6:]] += 1
        criado, fechado = ler_data(criado_txt), ler_data(fechado_txt)
        if criado and fechado:
            atrasos.append((fechado - criado).total_seconds())
            n["trocam_de_dia_em_brasilia"] += criado.date() != fechado.date()
        else:
            n["sem_date_closed"] += 1
    return {
        "pedidos": len(pedidos), "ids_distintos": len(ids), "contagens": dict(n),
        "campos": {nome: contar(c) for nome, c in chaves.items()},
        "status": contar(status), "tags": contar(tags), "canal": contar(canal),
        "stock_node_id": contar(nodes), "stock_store_id": contar(lojas),
        "quantidade_do_item": contar(quantidades), "itens_por_pedido": contar(itens_por_pedido),
        "sufixo_de_fuso_nas_datas": contar(fusos_das_datas),
        "mlbs_distintos": len(mlbs), "seller_skus_distintos": len(sku_para_mlbs),
        "seller_skus_com_mais_de_1_mlb": sum(1 for v in sku_para_mlbs.values() if len(v) > 1),
        "atraso_closed_menos_created_s": {
            "mediana": median(atrasos) if atrasos else None, "p95": percentil(atrasos, 0.95),
            "max": max(atrasos) if atrasos else None, "pedidos_comparados": len(atrasos),
        },
    }


def amostra_de_pedidos(pedidos, quantos=20):
    """Lista branca: id, status, datas, tags, pack, envio e, por item, mlb/sku/quantidade/node_id/store_id. Nada do comprador."""
    passo = max(1, len(pedidos) // quantos)
    amostra = []
    for pedido in pedidos[::passo][:quantos]:
        amostra.append({
            "order_id": pedido.get("id"), "status": pedido.get("status"),
            "date_created": pedido.get("date_created"), "date_closed": pedido.get("date_closed"),
            "tags": pedido.get("tags") or [], "pack_id": pedido.get("pack_id"), "shipping_id": dig(pedido, "shipping", "id"),
            "itens": [{
                "mlb": dig(it, "item", "id"), "seller_sku": dig(it, "item", "seller_sku"), "quantidade": it.get("quantity"),
                "variation_id": dig(it, "item", "variation_id"),
                "node_id": dig(it, "stock", "node_id"), "store_id": dig(it, "stock", "store_id"),
            } for it in pedido.get("order_items") or []],
        })
    return amostra


def passo_ontem(ontem_ini, hoje_ini):
    """Lê TODAS as páginas de ontem por 'offset' (até o total ou a trava). Devolve os pedidos crus (só na memória)."""
    console.rule("[bold]1) Pedidos de ontem (todas as páginas, por offset)")
    pedidos, total, paginas, parou = [], None, 0, None
    for pagina in range(MAX_PAGINAS_DE_ONTEM):
        offset = pagina * LIMITE_POR_PAGINA
        registro = pagina_de_pedidos(ontem_ini, hoje_ini, offset, f"ontem pág {pagina + 1} (offset {offset})")
        if registro["http"] != 200:
            parou = f"parou na pág {pagina + 1}: HTTP {registro['http']}"
            break
        if total is None:
            total = registro["total"]
        pedidos.extend(registro["_corpo"].get("results") or [])
        paginas += 1
        if not registro["linhas"] or total is None or offset + LIMITE_POR_PAGINA >= total:
            break
    else:
        parou = f"trava MAX_PAGINAS_DE_ONTEM={MAX_PAGINAS_DE_ONTEM} atingida"
    ids_distintos = len({p.get("id") for p in pedidos})
    resultado["ontem"] = {
        "de": ontem_ini.isoformat(timespec="seconds"), "ate_exclusivo": hoje_ini.isoformat(timespec="seconds"),
        "total_informado_pela_api": total, "paginas_lidas": paginas, "pedidos_lidos": len(pedidos),
        "ids_distintos": ids_distintos, "leitura_completa": total is not None and ids_distintos == total, "parou": parou,
        "analise": analisar_pedidos(pedidos) if pedidos else None,
        "amostra_de_pedidos": amostra_de_pedidos(pedidos),
    }
    return pedidos


def passo_totais(hoje_ini):
    """Página 1 de cada janela, só para ler paging.total (quantas páginas de 50 a coleta custaria)."""
    console.rule("[bold]2) Total de pedidos por janela (página 1 de cada)")
    saida = []
    for dias in JANELAS_DE_TOTAL_EM_DIAS:
        inicio, fim = janela_de_dias_completos(dias, hoje_ini)
        registro = pagina_de_pedidos(inicio, fim, 0, f"total {dias} dias")
        status = Counter(str(p.get("status")) for p in (registro["_corpo"] or {}).get("results", [])) if registro["http"] == 200 else {}
        saida.append({
            "dias": dias, "de": inicio.date().isoformat(), "ate_exclusivo": fim.date().isoformat(), "http": registro["http"],
            "total": registro["total"], "tentativas": registro["tentativa"], "status_na_pagina_1": contar(Counter(status)),
        })
    resultado["totais_por_janela"] = saida
    return saida


def passo_offset_profundo(totais, hoje_ini):
    """Onde o 'offset' para de funcionar? 1 chamada na última página da maior janela; se falhar e total > 10000, 1 chamada em 9950."""
    console.rule("[bold]3) Offset fundo da maior janela")
    resultado["offset_profundo"] = []
    validas = [x for x in totais if x["http"] == 200 and x["total"]]
    if not validas:
        return
    maior = max(validas, key=lambda x: x["dias"])
    total = maior["total"]
    inicio, fim = janela_de_dias_completos(maior["dias"], hoje_ini)
    ultimo_offset = ((total - 1) // LIMITE_POR_PAGINA) * LIMITE_POR_PAGINA
    if ultimo_offset == 0:
        console.print("  (o total cabe na página 1; nada para sondar)")
        return
    alvos = [ultimo_offset]
    for offset in alvos:
        registro = pagina_de_pedidos(inicio, fim, offset, f"offset {offset} ({maior['dias']} dias)")
        resultado["offset_profundo"].append({
            "janela_dias": maior["dias"], "total_da_janela": total, "offset": offset, "http": registro["http"],
            "linhas": registro["linhas"], "linhas_esperadas": total - offset, "erro": registro["erro"],
        })
        if registro["http"] != 200 and total > 10000 and 9950 not in alvos:
            alvos.append(9950)


def escolher_pedidos_para_envio(pedidos, quantos):
    """~N pedidos com envio, em rodízio entre os node_id (para pegar Full e não-Full, se existirem)."""
    grupos = defaultdict(list)
    for pedido in pedidos:
        if not dig(pedido, "shipping", "id"):
            continue
        nodes = sorted({str(dig(it, "stock", "node_id") or ROTULO_SEM_NODE) for it in pedido.get("order_items") or []})
        grupos[",".join(nodes) if nodes else "(sem itens)"].append(pedido)
    filas = [grupos[chave] for chave in sorted(grupos)]
    escolhidos, rodada = [], 0
    while len(escolhidos) < quantos and any(rodada < len(f) for f in filas):
        for chave, fila in zip(sorted(grupos), filas):
            if rodada < len(fila) and len(escolhidos) < quantos:
                escolhidos.append((chave, fila[rodada]))
        rodada += 1
    return escolhidos


def passo_envios(pedidos):
    """GET /shipments/{id} (header x-format-new: true) em ~20 pedidos: node_id do pedido x logistic.type do envio."""
    console.rule("[bold]4) Envios da amostra (node_id do pedido x logistic.type)")
    escolhidos = escolher_pedidos_para_envio(pedidos, PEDIDOS_PARA_CONSULTAR_ENVIO)
    cruzamento, origem_bate, amostra = Counter(), Counter(), []
    chaves = {"envio": set(), "logistic": set(), "origin": set(), "origin.node": set()}
    for indice, (node_pedido, pedido) in enumerate(escolhidos, 1):
        registro = chamar_com_repeticao("envio", f"envio {indice}/{len(escolhidos)} (node {node_pedido})",
                                        f"/shipments/{dig(pedido, 'shipping', 'id')}", None, {"x-format-new": "true"})
        item = {"order_id": pedido.get("id"), "node_id_do_pedido": node_pedido, "http": registro["http"]}
        corpo = registro["_corpo"] if registro["http"] == 200 else None
        if isinstance(corpo, dict):
            tipo = dig(corpo, "logistic", "type") or corpo.get("logistic_type")
            origem = dig(corpo, "origin", "node", "node_id")
            item.update({
                "logistic_type": tipo, "logistic_mode": dig(corpo, "logistic", "mode"),
                "status": corpo.get("status"), "substatus": corpo.get("substatus"), "origin_node_id": origem,
            })
            cruzamento[(node_pedido, str(tipo))] += 1
            if origem is not None and "," not in node_pedido and node_pedido != ROTULO_SEM_NODE:
                origem_bate[f"origin.node_id {'=' if str(origem) == node_pedido else '≠'} node_id do pedido"] += 1
            chaves["envio"].update(nomes_das_chaves(corpo))
            chaves["logistic"].update(nomes_das_chaves(corpo.get("logistic")))
            chaves["origin"].update(nomes_das_chaves(corpo.get("origin")))
            chaves["origin.node"].update(nomes_das_chaves(dig(corpo, "origin", "node")))
        else:
            item["erro"] = registro["erro"]
        amostra.append(item)
    resultado["envios"] = {
        "consultados": len(escolhidos),
        "cruzamento_node_id_x_logistic_type": [{"node_id_do_pedido": k[0], "logistic_type": k[1], "qtd": v} for k, v in sorted(cruzamento.items())],
        "origin_node_id_confere": contar(origem_bate),
        "nomes_de_campos": {k: sorted(v) for k, v in chaves.items()},
        "amostra": amostra,
    }


def passo_cancelados(ontem_ini, hoje_ini):
    """1 chamada pedindo só order.status=cancelled de ontem. A doc diz que a busca de vendedor filtra cancelados; aqui se mede."""
    console.rule("[bold]5) Pedidos cancelados (order.status=cancelled)")
    registro = pagina_de_pedidos(ontem_ini, hoje_ini, 0, "ontem order.status=cancelled", status="cancelled")
    resultados = (registro["_corpo"] or {}).get("results", []) if registro["http"] == 200 else []
    resultado["cancelados"] = {
        "http": registro["http"], "total": registro["total"], "linhas": registro["linhas"], "erro": registro["erro"],
        "status_dos_resultados": contar(Counter(str(p.get("status")) for p in resultados)),
        "tags_dos_resultados": contar(Counter(tag for p in resultados for tag in (p.get("tags") or []))),
    }


# ============================== PARTE 3: resumo na tela, JSON e main ==============================

def mostrar_chamadas():
    tabela = Table(title="Chamadas por tipo (cada tentativa conta)", box=box.SIMPLE_HEAD, title_justify="left")
    for coluna in ("tipo", "chamadas", "tent.", "200", "429", "404", "outros", "% 429", "desistiu"):
        tabela.add_column(coluna, justify="right" if coluna != "tipo" else "left")
    for tipo in sorted({c["tipo"] for c in chamadas}):
        tentativas = [c for c in chamadas if c["tipo"] == tipo]
        http = Counter(c["http"] for c in tentativas)
        outros = len(tentativas) - http[200] - http[429] - http[404]
        tabela.add_row(
            tipo, str(sum(1 for c in tentativas if c["tentativa"] == 1)), str(len(tentativas)), str(http[200]), str(http[429]),
            str(http[404]), str(outros), f"{100 * http[429] / len(tentativas):.0f}%", str(sum(1 for c in tentativas if c.get("desistiu"))),
        )
    console.print(tabela)


def mostrar_totais():
    saida = resultado.get("totais_por_janela") or []
    if not saida:
        return
    tabela = Table(title="Pedidos por janela (paging.total)", box=box.SIMPLE_HEAD, title_justify="left")
    for coluna in ("dias", "de → até (exclusivo)", "HTTP", "total", "pedidos/dia", "páginas de 50"):
        tabela.add_column(coluna, justify="left" if coluna.startswith("de") else "right")
    for x in saida:
        total = x["total"]
        tabela.add_row(
            str(x["dias"]), f"{x['de']} → {x['ate_exclusivo']}", str(x["http"]), "-" if total is None else str(total),
            "-" if total is None else f"{total / x['dias']:.1f}", "-" if total is None else str(-(-total // LIMITE_POR_PAGINA)),
        )
    console.print(tabela)
    for sonda in resultado.get("offset_profundo") or []:
        console.print(
            f"  offset {sonda['offset']} na janela de {sonda['janela_dias']} dias (total {sonda['total_da_janela']}): "
            f"[{cor_do_status(sonda['http'])}]HTTP {sonda['http']}[/] · linhas {sonda['linhas']} (esperado {sonda['linhas_esperadas']})"
            + (f" · {t(sonda['erro'][:120])}" if sonda["erro"] else "")
        )


def mostrar_ontem():
    ontem = resultado.get("ontem")
    if not ontem:
        return
    console.print(
        f"\n[bold]Ontem[/]: total da API {ontem['total_informado_pela_api']} · lidos {ontem['pedidos_lidos']} em {ontem['paginas_lidas']} pág. · "
        f"ids distintos {ontem['ids_distintos']} · leitura completa: {'sim' if ontem['leitura_completa'] else 'NÃO'}"
        + (f" · {t(ontem['parou'])}" if ontem["parou"] else "")
    )
    a = ontem.get("analise")
    if not a:
        return
    n = a["contagens"]
    for titulo, nomes in (("campos do pedido", a["campos"]["pedido"]), ("campos de order_items[]", a["campos"]["item_do_pedido"]),
                          ("campos de order_items[].item", a["campos"]["item"]), ("campos de order_items[].stock", a["campos"]["stock"]),
                          ("campos de shipping", a["campos"]["envio"]), ("campos de payments[]", a["campos"]["pagamento"]),
                          ("campos de buyer (só nomes)", a["campos"]["comprador"])):
        console.print(f"  [dim]{titulo}:[/] {t(', '.join(nomes))}")
    console.print(f"  status: {t(texto_de_contagem(a['status']))}")
    console.print(f"  tags: {t(texto_de_contagem(a['tags'], 20))}")
    console.print(f"  context.channel: {t(texto_de_contagem(a['canal']))}")
    console.print(f"  stock.node_id: {t(texto_de_contagem(a['stock_node_id']))} · itens sem stock: {n.get('itens_sem_stock', 0)}")
    console.print(f"  stock.store_id: {t(texto_de_contagem(a['stock_store_id']))}")
    console.print(f"  itens/pedido: {t(texto_de_contagem(a['itens_por_pedido']))} · quantidade do item: {t(texto_de_contagem(a['quantidade_do_item']))}")
    console.print(
        f"  com pack_id: {n.get('com_pack_id', 0)} · sem shipping.id: {n.get('sem_shipping_id', 0)} · "
        f"itens com seller_sku: {n.get('itens_com_seller_sku', 0)}/{n.get('itens', 0)} · com seller_custom_field: {n.get('itens_com_seller_custom_field', 0)} · "
        f"com variation_id: {n.get('itens_com_variation_id', 0)}"
    )
    console.print(
        f"  MLBs distintos: {a['mlbs_distintos']} · seller_skus distintos: {a['seller_skus_distintos']} · "
        f"seller_skus com mais de 1 MLB: {a['seller_skus_com_mais_de_1_mlb']}"
    )
    atraso = a["atraso_closed_menos_created_s"]
    console.print(
        f"  datas: sufixo de fuso {t(texto_de_contagem(a['sufixo_de_fuso_nas_datas']))} · date_closed − date_created: mediana {atraso['mediana']} s, "
        f"p95 {atraso['p95']} s, máx {atraso['max']} s ({atraso['pedidos_comparados']} pedidos) · "
        f"trocam de dia (Brasília): {n.get('trocam_de_dia_em_brasilia', 0)} · sem date_closed: {n.get('sem_date_closed', 0)}"
    )


def mostrar_envios():
    envios = resultado.get("envios")
    if not envios or not envios["consultados"]:
        return
    tabela = Table(title=f"node_id do pedido x logistic.type do envio ({envios['consultados']} envios)", box=box.SIMPLE_HEAD, title_justify="left")
    for coluna in ("node_id do pedido", "logistic.type", "qtd"):
        tabela.add_column(coluna, justify="right" if coluna == "qtd" else "left")
    for linha in envios["cruzamento_node_id_x_logistic_type"]:
        tabela.add_row(t(linha["node_id_do_pedido"]), t(linha["logistic_type"]), str(linha["qtd"]))
    console.print(tabela)
    console.print(f"  origin.node.node_id x node_id do pedido: {t(texto_de_contagem(envios['origin_node_id_confere']) or '-')}")
    for nome, campos in envios["nomes_de_campos"].items():
        console.print(f"  [dim]campos de {nome}:[/] {t(', '.join(campos))}")
    sem_resposta = [e for e in envios["amostra"] if e["http"] != 200]
    if sem_resposta:
        console.print(f"  envios sem 200: {t(texto_de_contagem(Counter(str(e['http']) for e in sem_resposta)))}")


def mostrar_cancelados():
    c = resultado.get("cancelados")
    if not c:
        return
    console.print(
        f"\n[bold]Cancelados (ontem)[/]: HTTP {c['http']} · total {c['total']} · linhas {c['linhas']} · "
        f"status dos resultados: {t(texto_de_contagem(c['status_dos_resultados']) or '-')}"
        + (f" · {t(c['erro'][:120])}" if c["erro"] else "")
    )


def mostrar_resumo():
    console.rule("[bold]RESUMO")
    mostrar_chamadas()
    mostrar_totais()
    mostrar_ontem()
    mostrar_envios()
    mostrar_cancelados()


def salvar_json():
    saida = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"), "conta": CONTA,
        "config": {
            "janelas_de_total_em_dias": JANELAS_DE_TOTAL_EM_DIAS, "limite_por_pagina": LIMITE_POR_PAGINA,
            "max_paginas_de_ontem": MAX_PAGINAS_DE_ONTEM, "pedidos_para_consultar_envio": PEDIDOS_PARA_CONSULTAR_ENVIO,
            "testar_offset_profundo": TESTAR_OFFSET_PROFUNDO, "pausa_entre_chamadas_s": PAUSA_ENTRE_CHAMADAS_S,
            "pausa_apos_429_s": PAUSA_APOS_429_S, "max_tentativas_por_chamada": MAX_TENTATIVAS_POR_CHAMADA,
        },
        **resultado,
        "chamadas": [{k: v for k, v in c.items() if k != "_corpo"} for c in chamadas],
    }
    texto = json.dumps(saida, ensure_ascii=False, indent=2)
    if user_id and str(user_id) in texto:          # rede de segurança: o id nunca deveria estar aqui
        texto = texto.replace(str(user_id), "***")
    CAMINHO_SAIDA.write_text(texto, encoding="utf-8")


def mostrar_plano(ontem_ini):
    console.print(f"[bold]Exploração do GET {ENDPOINT_PEDIDOS}[/] · conta {CONTA} · só leitura (GET) · ontem = {ontem_ini.strftime('%d/%m/%Y')} (Brasília)")
    console.print("Chamadas previstas (cada 429 / 5xx repete a MESMA chamada, até "
                  f"{MAX_TENTATIVAS_POR_CHAMADA} tentativas, e cada tentativa aparece abaixo):")
    console.print(f"  1) pedidos de ontem: página 1 + as demais por offset (até {MAX_PAGINAS_DE_ONTEM} páginas de {LIMITE_POR_PAGINA})")
    console.print(f"  2) total (página 1) das janelas de {', '.join(str(d) for d in JANELAS_DE_TOTAL_EM_DIAS)} dias → {len(JANELAS_DE_TOTAL_EM_DIAS)} chamadas")
    console.print("  3) offset fundo da maior janela → " + ("1 chamada (2 só se a 1ª falhar e o total passar de 10000)" if TESTAR_OFFSET_PROFUNDO else "desligado"))
    console.print(f"  4) GET /shipments/{{id}} → até {PEDIDOS_PARA_CONSULTAR_ENVIO} chamadas (1 por pedido da amostra)")
    console.print("  5) pedidos de ontem com order.status=cancelled → 1 chamada\n")


def main():
    global user_id
    load_dotenv(dotenv_path=_RAIZ_DO_PROJETO / ".env")
    user_id = os.getenv(f"{CONTA}_USER_ID")
    if not user_id:
        console.print(f"[bold red]{CONTA}_USER_ID não encontrado no .env da raiz do repo.[/]")
        return
    user_id = str(user_id).strip()
    hoje_ini = datetime.now(FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    ontem_ini, _ = janela_de_dias_completos(1, hoje_ini)
    mostrar_plano(ontem_ini)
    try:
        pedidos = passo_ontem(ontem_ini, hoje_ini)
        totais = passo_totais(hoje_ini)
        if TESTAR_OFFSET_PROFUNDO:
            passo_offset_profundo(totais, hoje_ini)
        if PEDIDOS_PARA_CONSULTAR_ENVIO > 0:
            passo_envios(pedidos)
        passo_cancelados(ontem_ini, hoje_ini)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Interrompido (Ctrl+C). Mostrando e salvando o que já foi medido.[/]")
    finally:
        if chamadas:
            mostrar_resumo()
            salvar_json()
            console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name} ({len(chamadas)} tentativas). Sem seller_id, sem token, sem dado de comprador.")


if __name__ == "__main__":
    main()
