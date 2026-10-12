# scripts_exploracao_ML/investigar_vendas_sem_origem_informada.py
#
# Função Objetivo: ENTENDER, com dado real e só em leitura, por que algumas vendas do histórico ficam como "Sem origem informada" na tela
# de Vendas: são as linhas de VendaItemMercadoLivre com node_id E store_id vazios (classificar_origem = 'indefinido'). Elas contam no
# Produto, mas NÃO entram em "No Full" nem em "Fora do Full". Em 09/10/2026 os 160 pedidos medidos tinham todos o stock.node_id, então a
# causa ainda é desconhecida (a doc do ML não diz quando o bloco order_items[].stock falta). O script responde, em 3 partes:
#
#   PARTE 1 (banco, só leitura): quantas são, desde quando, em que meses/dias, e com que característica elas andam juntas (catálogo,
#            desconto, pack, envio, variação, tipo de anúncio, status, horário, tempo até a coleta, anúncio). Separa as 3 hipóteses:
#            é do TEMPO (pedido antigo ou ainda em formação), do TIPO de venda, ou de um ANÚNCIO específico?
#   PARTE 2 (API, só GET): re-busca uma amostra (as mais recentes, as mais antigas e outras espalhadas no tempo, mais poucas vendas COM
#            origem para comparar) de 3 jeitos:
#              a) GET /orders/{id}            → o pedido como o ML entrega HOJE;
#              b) GET /orders/search          → numa janela de 2 minutos em volta da venda: é o MESMO caminho do coletor;
#              c) GET /shipments/{id}         → o envio (header x-format-new: true): origin.node.node_id e logistic.type.
#            Mostra o bloco order_items[].stock CRU (todas as chaves; vem como dict ou como lista?), varre o pedido INTEIRO atrás de
#            qualquer campo com cara de origem de estoque (node, network, store, inventory, origin...) e compara com o envio.
#   PARTE 3: um DIAGNÓSTICO por item (com a leitura de cada um), a contagem geral e um JSON para guardar.
#   PARTE 2A / 4 (chamada extra, achada na doc "Estoque multi-origem"): GET /users/{id}/stores/search?tags=stock_location lista os DEPÓSITOS do
#            próprio vendedor (id da loja = store_id do pedido; network_node_id = node_id do pedido). A PARTE 4 mostra TODOS os campos que a API
#            devolveu e cruza essa lista com os nós e store_id que o banco tem, para responder: o prefixo "BRP" é mesmo um bom critério de
#            "Fora do Full"? Quantas unidades mudariam de Fora do Full para Full (ou o contrário) se a regra usasse a lista de depósitos?
#            Opcional (ENVIOS_DE_PEDIDOS_FORA_DO_FULL): consulta o envio de alguns pedidos "fora do Full" para ver o logistic.type de cada grupo.
#
# REGRAS: só leitura (GET) e só SELECT no banco. Nada é gravado no banco. O seller_id e o token nunca vão para a tela nem para o JSON;
# nenhum dado de comprador é guardado (o bloco buyer e os endereços do envio nem entram na varredura). O JSON é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → Por que não usa chamar_api(): ele repete o 429 sozinho e grava os params (com o seller_id) no log. Aqui cada tentativa
#                  precisa aparecer e o seller_id não pode ir para nenhum arquivo. Por isso o script usa a MESMA sessão HTTP e o MESMO
#                  gerenciador de token do cliente, com um retry curto próprio (mesmo padrão de explorar_orders_search_para_historico_de_vendas).
# * [EXPLICAÇÃO] → A PARTE 1 lê a tabela inteira numa passada só (values_list, em blocos de 5000) e conta em Python. São dezenas de
#                  milhares de linhas: cabe folgado na memória e deixa o critério de "sem origem" em UM lugar só (classificar_origem, a
#                  mesma função da tela), em vez de repetir a regra num filtro SQL.

import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
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

import requests
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from api_mercado_livre.core.auth.gerenciador_token import obter_token_valido
from api_mercado_livre.core.estrutura_api.cliente_api import BASE_URL, TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS, _sessao
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from gestao_vendas.funcoes_auxiliares.vendas_ml import classificar_origem
from mercado_livre.models import VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale): decide o banco E a conta da API
CONSULTAR_API = True                  # False = roda só a PARTE 1 (banco), 0 chamadas à API
RECENTES = 5                          # vendas sem origem MAIS RECENTES para re-buscar na API
ANTIGAS = 5                           # vendas sem origem MAIS ANTIGAS
ESPALHADAS = 10                       # outras, espalhadas em intervalos iguais entre a mais antiga e a mais recente
COM_ORIGEM_PARA_COMPARAR = 3          # vendas COM origem (controle): mostram como é o bloco stock "normal" na mesma API
COMPARAR_COM_A_BUSCA = True           # b) GET /orders/search em volta da venda (o caminho do coletor)
CONSULTAR_ENVIO = True                # c) GET /shipments/{id}
TOPO_DE_ANUNCIOS = 10                 # quantos anúncios (MLB) mostrar no ranking de "sem origem"
CONSULTAR_DEPOSITOS = True            # GET /users/{id}/stores/search?tags=stock_location (1 chamada por página de 50 depósitos)
CONSULTAR_AMOSTRA_DE_PEDIDOS = False   # False = pula a re-busca dos pedidos (PARTE 2B): útil para rodar só os depósitos, em segundos
ENVIOS_DE_PEDIDOS_FORA_DO_FULL = 0    # opcional: quantos envios (GET /shipments/{id}) consultar de pedidos "fora do Full" (0 = desligado; 10 a 15 é um bom teste)
MAX_PAGINAS_DE_DEPOSITOS = 10         # trava de segurança (10 páginas de 50)
PAUSA_ENTRE_CHAMADAS_S = 1            # silêncio antes de cada chamada nova (o mesmo ritmo do coletor)
PAUSA_APOS_429_S = 5                  # espera antes de repetir a MESMA chamada depois de 429 / 5xx / falha de rede
MAX_TENTATIVAS_POR_CHAMADA = 6        # tentativas por chamada antes de desistir dela e seguir
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

FUSO = ZoneInfo("America/Sao_Paulo")
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_vendas_sem_origem_{CONTA}.json"
JANELA_DA_BUSCA = timedelta(minutes=1)    # a busca pede [venda − 1 min, venda + 1 min]
PALAVRAS_DE_ORIGEM = ("node", "stock", "store", "network", "warehouse", "fulfil", "origin", "inventory", "logistic", "facility", "depot", "center")
IGNORAR_NA_VARREDURA = {                  # nada de comprador, endereço, pagamento nem rastreio entra na varredura
    "buyer", "seller", "receiver", "receiver_address", "receiver_id", "destination", "sender", "sender_address", "sender_id",
    "payments", "shipping_address", "tracking_number", "tracking_url",
}
CAMPOS_DO_DEPOSITO_COM_VALOR_LIBERADO = {   # só estes campos do depósito têm o VALOR gravado/mostrado; dos demais vai só o nome e o tipo (ex.: location = endereço)
    "id", "description", "status", "tags", "network_node_id", "services", "type", "name", "date_created", "last_updated", "user_id", "external_id",
}
FAIXAS_DO_DIA = [(6, "madrugada (0h-5h)"), (12, "manhã (6h-11h)"), (18, "tarde (12h-17h)"), (24, "noite (18h-23h)")]
FAIXAS_DE_ATRASO_H = [(1, "menos de 1 h"), (6, "1 a 6 h"), (24, "6 a 24 h"), (72, "1 a 3 dias"), (720, "3 a 30 dias"), (None, "mais de 30 dias")]
CAMPOS_DO_BANCO = (
    "order_id", "posicao", "mlb", "seller_sku", "variation_id", "quantidade", "status", "criado_em_ml", "fechado_em_ml", "dia_venda",
    "hora_venda", "node_id", "store_id", "pack_id", "shipping_id", "catalogo", "com_desconto", "tipo_anuncio", "atualizado_em",
)

LEITURA_DO_STOCK = {
    "COM_NODE_ID": "o ML entrega o node_id nesta fonte. Se a linha está SEM origem no banco: ou ela foi gravada antes de o ML preencher (recoletar resolve), ou "
                   "o coletor não leu. Compare a coluna do pedido com a da BUSCA: se SÓ o GET do pedido traz, a busca é incompleta.",
    "SO_NETWORK_NODE_ID": "o bloco stock vem só com network_node_id (o coletor lê só node_id). Correção provável: ler também network_node_id e descobrir o que ele representa.",
    "SO_STORE_ID": "o bloco stock vem só com store_id (estoque próprio sem node_id). O coletor já guarda o store_id: conferir se a linha do banco realmente perdeu o store_id.",
    "STOCK_SEM_NODE_ID": "o bloco stock existe mas sem node_id/network_node_id/store_id. Ver as chaves e valores crus (linha 'stock =') para achar onde está a origem.",
    "SEM_STOCK_MAS_HA_OUTRO_CAMPO": "o item não tem stock, mas existe outro campo de origem no pedido (ver a tabela de caminhos). Candidato a nova fonte de leitura.",
    "SEM_STOCK": "o ML não informa estoque neste item. Origem só dá para tentar pelo ENVIO (origin.node.node_id), quando houver shipping.id.",
}
LEITURA_DO_ENVIO = {
    "SEM_ENVIO": "o pedido não tem shipping.id (retirada, acordo com o comprador ou venda sem envio pelo ML): não há envio para consultar.",
    "ORIGEM_FULL": "o envio diz que saiu de um centro do Full (origin.node.node_id sem prefixo BRP).",
    "ORIGEM_FORA": "o envio diz que saiu do estoque próprio (origin.node.node_id com prefixo BRP).",
    "ENVIO_SEM_ORIGEM": "o envio existe mas não traz origin.node.node_id.",
}

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(100, 24)).columns - 1, 40))
t = escape
user_id = None
chamadas = []                         # 1 dict por TENTATIVA (vai para o JSON, sem o corpo da resposta)
ultimo_fim = {"t": None}
resultado = {}                        # tudo o que vai para o JSON


# ============================== utilitários ==============================

def sem_id(texto):
    """Troca o seller_id por *** antes de mostrar qualquer texto que veio da API."""
    texto = str(texto)
    return texto.replace(str(user_id), "***") if user_id else texto


def dig(obj, *caminho):
    """Entra em dicts aninhados sem estourar: dig(pedido, 'shipping', 'id')."""
    for chave in caminho:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(chave)
    return obj


def pct(parte, total):
    return 100 * parte / total if total else 0.0


def texto_pct(parte, total):
    return f"{pct(parte, total):.1f}%" if total else "-"


def unidades(linhas):
    return sum(l["quantidade"] for l in linhas)


def origem_da_linha(l):
    return classificar_origem(l["node_id"], l["store_id"])


def sem_origem(l):
    return origem_da_linha(l) == "indefinido"


def instante_em_brasilia(valor):
    """datetime do banco (com ou sem fuso) -> datetime no horário de Brasília."""
    if valor is None:
        return None
    return valor.replace(tzinfo=FUSO) if valor.tzinfo is None else valor.astimezone(FUSO)


def formatar_data_para_filtro(instante):
    """Mesmo formato que já deu 200 OK em /orders/search (ex: 2026-10-10T00:00:00.000-0300)."""
    texto = instante.isoformat(timespec="milliseconds")
    return texto[:-6] + texto[-6:].replace(":", "")


def json_compacto(valor, limite=170):
    texto = sem_id(json.dumps(valor, ensure_ascii=False, default=str))
    return texto if len(texto) <= limite else texto[:limite] + "…"


# ============================== PARTE 1: banco ==============================

def ler_linhas_do_banco():
    """Todas as linhas da tabela como dicts (1 passada, em blocos de 5000). Só SELECT."""
    consulta = VendaItemMercadoLivre.objects.values_list(*CAMPOS_DO_BANCO).iterator(chunk_size=5000)
    return [dict(zip(CAMPOS_DO_BANCO, linha)) for linha in consulta]


def taxa_por_grupo(vivas, chave, ordem=None):
    """[{grupo, un, sem_origem, pct}] — unidades (não pedidos) por valor da característica, nas vendas não canceladas.
    `ordem` = lista com a ordem natural dos grupos (manhã → noite, menos de 1 h → mais de 30 dias); sem ela, ordem alfabética."""
    total, sem = Counter(), Counter()
    for l in vivas:
        grupo = chave(l)
        total[grupo] += l["quantidade"]
        if sem_origem(l):
            sem[grupo] += l["quantidade"]
    ordenados = sorted(total, key=lambda g: ordem.index(g) if ordem and g in ordem else len(ordem or ())) if ordem else sorted(total, key=str)
    return [{"grupo": g, "un": total[g], "sem_origem": sem[g], "pct": pct(sem[g], total[g])} for g in ordenados]


def faixa_do_dia(l):
    return next(nome for limite, nome in FAIXAS_DO_DIA if l["hora_venda"] < limite)


def faixa_de_atraso(l):
    """Tempo entre a venda e a ÚLTIMA gravação da linha (atualizado_em muda a cada recoleta)."""
    try:
        horas = (l["atualizado_em"] - l["criado_em_ml"]).total_seconds() / 3600
    except (TypeError, ValueError):
        return "(não deu para calcular)"
    return next(nome for limite, nome in FAIXAS_DE_ATRASO_H if limite is None or horas < limite)


# (nome, como separar a linha em grupos, ordem natural dos grupos ou None)
CARACTERISTICAS = [
    ("catálogo (tag catalog)", lambda l: "sim" if l["catalogo"] else "não", None),
    ("pedido com desconto (tag)", lambda l: "sim" if l["com_desconto"] else "não", None),
    ("pack_id (carrinho)", lambda l: "com pack" if l["pack_id"] else "sem pack", None),
    ("shipping_id (envio)", lambda l: "com envio" if l["shipping_id"] else "sem envio", None),
    ("variação no pedido", lambda l: "com variation_id" if l["variation_id"] else "sem variação", None),
    ("tipo de anúncio", lambda l: l["tipo_anuncio"] or "(vazio)", None),
    ("quantidade do item", lambda l: "1 un" if l["quantidade"] == 1 else "2 ou mais un", None),
    ("pedido já fechado (date_closed)", lambda l: "fechado" if l["fechado_em_ml"] else "sem date_closed", None),
    ("faixa do dia (hora da venda)", faixa_do_dia, [nome for _, nome in FAIXAS_DO_DIA]),
    ("tempo até a última gravação", faixa_de_atraso, [nome for _, nome in FAIXAS_DE_ATRASO_H]),
]


def analisar_banco(linhas):
    vivas = [l for l in linhas if l["status"] != "cancelled"]
    sem = [l for l in vivas if sem_origem(l)]
    un_vivas, un_sem = unidades(vivas), unidades(sem)

    por_status = []
    for status in sorted({l["status"] for l in linhas}):
        do_status = [l for l in linhas if l["status"] == status]
        por_status.append({"status": status, "un": unidades(do_status), "sem_origem": unidades([l for l in do_status if sem_origem(l)])})

    por_mes = []
    meses = sorted({l["dia_venda"].strftime("%Y-%m") for l in vivas})
    for mes in meses:
        do_mes = [l for l in vivas if l["dia_venda"].strftime("%Y-%m") == mes]
        por_mes.append({"mes": mes, "un": unidades(do_mes), "sem_origem": unidades([l for l in do_mes if sem_origem(l)])})

    ultimo_dia = max((l["dia_venda"] for l in vivas), default=None)
    ultimos_dias = []
    if ultimo_dia:
        for deslocamento in range(13, -1, -1):
            dia = ultimo_dia - timedelta(days=deslocamento)
            do_dia = [l for l in vivas if l["dia_venda"] == dia]
            ultimos_dias.append({"dia": dia.isoformat(), "un": unidades(do_dia), "sem_origem": unidades([l for l in do_dia if sem_origem(l)])})

    por_mlb = defaultdict(lambda: {"un": 0, "sem_origem": 0, "skus": set(), "dias_sem_origem": []})
    for l in vivas:
        a = por_mlb[l["mlb"]]
        a["un"] += l["quantidade"]
        a["skus"].add(l["seller_sku"] or "(sem SKU)")
        if sem_origem(l):
            a["sem_origem"] += l["quantidade"]
            a["dias_sem_origem"].append(l["dia_venda"])
    anuncios_com_sem_origem = [m for m, a in por_mlb.items() if a["sem_origem"]]
    ranking = sorted(anuncios_com_sem_origem, key=lambda m: -por_mlb[m]["sem_origem"])[:TOPO_DE_ANUNCIOS]

    itens_do_pedido = defaultdict(list)
    for l in vivas:
        itens_do_pedido[l["order_id"]].append(l)
    pedidos_com_varios_itens = [p for p in itens_do_pedido.values() if len(p) > 1]
    pedidos_mistos = [p for p in pedidos_com_varios_itens if len({sem_origem(l) for l in p}) > 1]

    # Origem (regra ATUAL da tela) por mês, por nó e por store_id: base da PARTE 4 (cruzamento com a lista de depósitos do vendedor).
    origem_por_mes = defaultdict(Counter)
    primeiro_dia_por_origem, primeiro_dia_com_store_id = {}, None
    por_no = defaultdict(lambda: {"un": 0, "linhas": 0, "origem_atual": Counter(), "store_ids": Counter(), "primeiro_dia": None, "ultimo_dia": None})
    por_store = defaultdict(lambda: {"un": 0, "linhas": 0, "nos": Counter(), "primeiro_dia": None, "ultimo_dia": None})
    for l in vivas:
        origem, dia, q = origem_da_linha(l), l["dia_venda"], l["quantidade"]
        origem_por_mes[dia.strftime("%Y-%m")][origem] += q
        if origem not in primeiro_dia_por_origem or dia < primeiro_dia_por_origem[origem]:
            primeiro_dia_por_origem[origem] = dia
        if l["store_id"] and (primeiro_dia_com_store_id is None or dia < primeiro_dia_com_store_id):
            primeiro_dia_com_store_id = dia
        blocos = [por_no[l["node_id"] or "(sem node_id)"]] + ([por_store[l["store_id"]]] if l["store_id"] else [])
        for bloco in blocos:
            bloco["un"] += q
            bloco["linhas"] += 1
            bloco["primeiro_dia"] = dia if bloco["primeiro_dia"] is None or dia < bloco["primeiro_dia"] else bloco["primeiro_dia"]
            bloco["ultimo_dia"] = dia if bloco["ultimo_dia"] is None or dia > bloco["ultimo_dia"] else bloco["ultimo_dia"]
        no = blocos[0]
        no["origem_atual"][origem] += q
        if l["store_id"]:
            no["store_ids"][l["store_id"]] += q
            blocos[1]["nos"][l["node_id"] or "(sem node_id)"] += q

    return {
        "linhas_na_tabela": len(linhas), "primeiro_dia": min((l["dia_venda"] for l in linhas), default=None),
        "ultimo_dia": max((l["dia_venda"] for l in linhas), default=None),
        "un_nao_canceladas": un_vivas, "un_sem_origem": un_sem, "linhas_sem_origem": len(sem),
        "pedidos_sem_origem": len({l["order_id"] for l in sem}),
        "primeiro_dia_sem_origem": min((l["dia_venda"] for l in sem), default=None),
        "ultimo_dia_sem_origem": max((l["dia_venda"] for l in sem), default=None),
        "dias_com_sem_origem": len({l["dia_venda"] for l in sem}),
        "dias_com_venda": len({l["dia_venda"] for l in vivas}),
        "origem_das_demais_un": dict(Counter({o: unidades([l for l in vivas if origem_da_linha(l) == o]) for o in ("full", "fora", "indefinido")})),
        "canceladas_sem_origem_linhas": sum(1 for l in linhas if l["status"] == "cancelled" and sem_origem(l)),
        "por_status": por_status, "por_mes": por_mes, "ultimos_14_dias": ultimos_dias,
        "por_caracteristica": {nome: taxa_por_grupo(vivas, chave, ordem) for nome, chave, ordem in CARACTERISTICAS},
        "anuncios": {
            "mlbs_com_venda": len(por_mlb), "mlbs_com_algum_sem_origem": len(anuncios_com_sem_origem),
            "mlbs_100_por_cento_sem_origem": sum(1 for m in anuncios_com_sem_origem if por_mlb[m]["sem_origem"] == por_mlb[m]["un"]),
            "ranking": [{
                "mlb": m, "skus": sorted(por_mlb[m]["skus"])[:3], "un": por_mlb[m]["un"], "sem_origem": por_mlb[m]["sem_origem"],
                "primeiro_dia": min(por_mlb[m]["dias_sem_origem"]).isoformat(), "ultimo_dia": max(por_mlb[m]["dias_sem_origem"]).isoformat(),
            } for m in ranking],
        },
        "pedidos_com_varios_itens": len(pedidos_com_varios_itens), "pedidos_mistos_com_e_sem_origem": len(pedidos_mistos),
        "origem_por_mes": [{"mes": mes, **{o: origem_por_mes[mes][o] for o in ("full", "fora", "indefinido")}} for mes in sorted(origem_por_mes)],
        "primeiro_dia_por_origem": dict(primeiro_dia_por_origem), "primeiro_dia_com_store_id": primeiro_dia_com_store_id,
        "nos": [{"node_id": nome, "un": n["un"], "linhas": n["linhas"], "origem_atual": dict(n["origem_atual"]), "store_ids": dict(n["store_ids"]),
                 "primeiro_dia": n["primeiro_dia"], "ultimo_dia": n["ultimo_dia"]} for nome, n in sorted(por_no.items(), key=lambda x: -x[1]["un"])],
        "store_ids": [{"store_id": nome, "un": s["un"], "linhas": s["linhas"], "nos": dict(s["nos"]), "primeiro_dia": s["primeiro_dia"], "ultimo_dia": s["ultimo_dia"]}
                      for nome, s in sorted(por_store.items(), key=lambda x: -x[1]["un"])],
    }


def cor_da_razao(razao, un):
    if un < 20:
        return ""
    return "yellow" if razao >= 2 else "cyan" if razao <= 0.5 else ""


def tabela_de_taxas(titulo, grupos, pct_geral, rotulo_da_coluna):
    tabela = Table(title=titulo, box=box.SIMPLE_HEAD, title_justify="left")
    tabela.add_column(rotulo_da_coluna)
    for coluna in ("un", "sem origem", "% sem origem", "× a média"):
        tabela.add_column(coluna, justify="right")
    for g in grupos:
        razao = g["pct"] / pct_geral if pct_geral else 0
        cor = cor_da_razao(razao, g["un"])
        estilo = (lambda x: f"[{cor}]{x}[/]") if cor else (lambda x: x)
        tabela.add_row(t(str(g["grupo"])), str(g["un"]), str(g["sem_origem"]), estilo(f"{g['pct']:.1f}%"), estilo(f"{razao:.1f}×"))
    console.print(tabela)


def texto_de_origem(contagem):
    """{'full': 10, 'fora': 3} -> 'full 10 · fora 3' (só o que tem unidade)."""
    return " · ".join(f"{o} {q}" for o, q in sorted(contagem.items(), key=lambda x: -x[1]) if q) or "-"


def mostrar_origem_do_banco(b):
    """Origem pela regra ATUAL da tela (classificar_origem): por mês, por nó (node_id) e por store_id. Base para a PARTE 4."""
    tabela = Table(title="Unidades por origem em cada mês (regra atual da tela)", box=box.SIMPLE_HEAD, title_justify="left")
    tabela.add_column("mês")
    for coluna in ("full", "fora", "sem origem", "% fora", "% sem origem"):
        tabela.add_column(coluna, justify="right")
    for m in b["origem_por_mes"]:
        total = m["full"] + m["fora"] + m["indefinido"]
        tabela.add_row(m["mes"], str(m["full"]), str(m["fora"]), str(m["indefinido"]), texto_pct(m["fora"], total), texto_pct(m["indefinido"], total))
    console.print(tabela)
    primeiros = b["primeiro_dia_por_origem"]
    console.print("  primeiro dia com cada origem: " + " · ".join(f"{nome} {primeiros[o]:%d/%m/%Y}" for o, nome in (("full", "full"), ("fora", "fora"), ("indefinido", "sem origem")) if o in primeiros)
                  + (f" · primeiro dia com store_id preenchido: {b['primeiro_dia_com_store_id']:%d/%m/%Y}" if b["primeiro_dia_com_store_id"] else " · nenhuma venda com store_id preenchido"))

    tabela = Table(title="Nós (node_id) que existem no banco", box=box.SIMPLE_HEAD, title_justify="left")
    tabela.add_column("node_id")
    for coluna in ("un", "% das un", "linhas"):
        tabela.add_column(coluna, justify="right")
    for coluna in ("regra atual (un)", "store_id (un)", "primeira venda", "última venda", "obs."):
        tabela.add_column(coluna)
    total_un = sum(n["un"] for n in b["nos"])
    for n in b["nos"]:
        obs = "começa com BRP e NÃO tem store_id" if n["node_id"].upper().startswith("BRP") and not n["store_ids"] else ""
        tabela.add_row(t(sem_id(n["node_id"])), str(n["un"]), texto_pct(n["un"], total_un), str(n["linhas"]), texto_de_origem(n["origem_atual"]),
                       t(sem_id(texto_de_origem(n["store_ids"]))), f"{n['primeiro_dia']:%d/%m/%Y}", f"{n['ultimo_dia']:%d/%m/%Y}", f"[yellow]{obs}[/]" if obs else "")
    console.print(tabela)

    if b["store_ids"]:
        tabela = Table(title="store_id que existem no banco", box=box.SIMPLE_HEAD, title_justify="left")
        tabela.add_column("store_id")
        for coluna in ("un", "linhas"):
            tabela.add_column(coluna, justify="right")
        for coluna in ("nó(s) (un)", "primeira venda", "última venda"):
            tabela.add_column(coluna)
        for s in b["store_ids"]:
            tabela.add_row(t(sem_id(s["store_id"])), str(s["un"]), str(s["linhas"]), t(sem_id(texto_de_origem(s["nos"]))), f"{s['primeiro_dia']:%d/%m/%Y}", f"{s['ultimo_dia']:%d/%m/%Y}")
        console.print(tabela)


def mostrar_banco(b):
    console.rule("[bold]PARTE 1 · O que o banco mostra")
    if not b["linhas_na_tabela"]:
        console.print("[yellow]A tabela de vendas está vazia nesta empresa. Nada a analisar.[/]")
        return
    pct_geral = pct(b["un_sem_origem"], b["un_nao_canceladas"])
    console.print(
        f"Tabela: {b['linhas_na_tabela']} linhas · vendas de {b['primeiro_dia']:%d/%m/%Y} a {b['ultimo_dia']:%d/%m/%Y} · "
        f"{b['dias_com_venda']} dias com venda (canceladas fora das contas)."
    )
    console.print(
        f"[bold]Sem origem informada[/]: {b['un_sem_origem']} un de {b['un_nao_canceladas']} ([bold]{pct_geral:.1f}%[/]) · {b['linhas_sem_origem']} linhas · "
        f"{b['pedidos_sem_origem']} pedidos · em {b['dias_com_sem_origem']} dos {b['dias_com_venda']} dias com venda."
    )
    if b["primeiro_dia_sem_origem"]:
        console.print(f"  primeira: {b['primeiro_dia_sem_origem']:%d/%m/%Y} · última: {b['ultimo_dia_sem_origem']:%d/%m/%Y} · "
                      f"unidades por origem (full / fora / indefinido): {b['origem_das_demais_un'].get('full', 0)} / {b['origem_das_demais_un'].get('fora', 0)} / {b['origem_das_demais_un'].get('indefinido', 0)}")
    console.print(f"  canceladas sem origem (fora das contas): {b['canceladas_sem_origem_linhas']} linhas · "
                  f"pedidos com mais de 1 item: {b['pedidos_com_varios_itens']} (destes, com itens COM e SEM origem juntos: {b['pedidos_mistos_com_e_sem_origem']})")
    mostrar_origem_do_banco(b)
    if not b["un_sem_origem"]:
        console.print("[green]Nenhuma venda sem origem nesta empresa. Nada mais a investigar.[/]")
        return
    console.print("[dim]'× a média' = quantas vezes o grupo tem mais (ou menos) 'sem origem' do que a média geral. Amarelo: 2× ou mais; ciano: metade ou menos (só com 20+ un).[/]\n")

    tabela_de_taxas("Por mês da venda", [{"grupo": m["mes"], "un": m["un"], "sem_origem": m["sem_origem"], "pct": pct(m["sem_origem"], m["un"])} for m in b["por_mes"]], pct_geral, "mês")
    tabela_de_taxas("Últimos 14 dias com dados", [{"grupo": d["dia"], "un": d["un"], "sem_origem": d["sem_origem"], "pct": pct(d["sem_origem"], d["un"])} for d in b["ultimos_14_dias"]], pct_geral, "dia")
    tabela_de_taxas("Por status do pedido (inclui cancelados)", [{"grupo": s["status"], "un": s["un"], "sem_origem": s["sem_origem"], "pct": pct(s["sem_origem"], s["un"])} for s in b["por_status"]], pct_geral, "status")
    for nome, grupos in b["por_caracteristica"].items():
        tabela_de_taxas(f"Por {nome}", grupos, pct_geral, "grupo")

    a = b["anuncios"]
    console.print(
        f"[bold]Anúncios[/]: {a['mlbs_com_venda']} MLBs com venda · {a['mlbs_com_algum_sem_origem']} têm alguma venda sem origem · "
        f"{a['mlbs_100_por_cento_sem_origem']} têm TODAS as vendas sem origem. "
        "[dim](anúncio com vendas COM e SEM origem = o problema é da venda, não do anúncio)[/]"
    )
    tabela = Table(title=f"Os {len(a['ranking'])} anúncios com mais unidades sem origem", box=box.SIMPLE_HEAD, title_justify="left")
    for coluna in ("MLB", "SKU", "un", "sem origem", "% do anúncio", "primeira", "última"):
        tabela.add_column(coluna, justify="left" if coluna in ("MLB", "SKU") else "right")
    for r in a["ranking"]:
        tabela.add_row(r["mlb"], t(", ".join(r["skus"])), str(r["un"]), str(r["sem_origem"]), texto_pct(r["sem_origem"], r["un"]), r["primeiro_dia"], r["ultimo_dia"])
    console.print(tabela)


# ============================== PARTE 2: API (só GET) ==============================

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


def chamar_uma_vez(tipo, rotulo, caminho, params, tentativa, headers_extra=None):
    """1 GET, 1 tentativa. Registra em `chamadas`; o corpo da resposta fica só em registro['_corpo'] (nunca vai para o JSON)."""
    registro = {
        "n": len(chamadas) + 1, "tipo": tipo, "rotulo": rotulo, "tentativa": tentativa,
        "hora_local": datetime.now().astimezone().isoformat(timespec="seconds"), "http": None, "ms": None, "erro": None, "_corpo": None,
    }
    cabecalhos = {"Authorization": f"Bearer {obter_token_valido(CONTA)}"}
    cabecalhos.update(headers_extra or {})
    inicio = time.perf_counter()
    try:
        resposta = _sessao.get(f"{BASE_URL}{caminho}", params=params, headers=cabecalhos, timeout=(TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS))
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
    console.print(f"    [dim]#{registro['n']:<3} {registro['hora_local'][11:19]} {registro['tipo']:<7} t{tentativa}[/] [{cor}]HTTP {registro['http'] if registro['http'] is not None else '---'}[/] "
                  f"{registro['ms']} ms" + (f" · {t(registro['erro'][:100])}" if registro["erro"] else ""))
    return registro


def chamar_com_repeticao(tipo, rotulo, caminho, params, headers_extra=None):
    """Chama e, se der 429 / 5xx / falha de rede, espera PAUSA_APOS_429_S e repete a MESMA chamada (cada tentativa fica registrada)."""
    esperar_ate(PAUSA_ENTRE_CHAMADAS_S)
    tentativa = 1
    registro = chamar_uma_vez(tipo, rotulo, caminho, params, tentativa, headers_extra)
    while (registro["http"] is None or registro["http"] == 429 or registro["http"] >= 500) and tentativa < MAX_TENTATIVAS_POR_CHAMADA:
        time.sleep(PAUSA_APOS_429_S)
        tentativa += 1
        registro = chamar_uma_vez(tipo, rotulo, caminho, params, tentativa, headers_extra)
    if registro["http"] == 401:
        console.print("[bold red]401: o Mercado Livre recusou o token. Exploração interrompida.[/]")
        raise SystemExit(1)
    return registro


def valor_curto(valor):
    if isinstance(valor, dict):
        return "dict[" + ",".join(list(valor)[:12]) + "]"
    if isinstance(valor, list):
        return f"lista[{len(valor)}]"
    return str(valor)[:60]


def varrer_origem(obj):
    """{caminho: [até 3 valores distintos]} de TODO campo cujo NOME lembra origem de estoque. Só olha nomes de chave; comprador/endereço/pagamento ficam de fora."""
    achados = {}

    def andar(no, caminho):
        if isinstance(no, dict):
            for chave, valor in no.items():
                if chave in IGNORAR_NA_VARREDURA:
                    continue
                novo = f"{caminho}.{chave}" if caminho else chave
                if any(p in str(chave).lower() for p in PALAVRAS_DE_ORIGEM):
                    visto = achados.setdefault(novo, [])
                    texto = sem_id(valor_curto(valor))
                    if texto not in visto and len(visto) < 3:
                        visto.append(texto)
                andar(valor, novo)
        elif isinstance(no, list):
            for elemento in no:
                andar(elemento, caminho + "[]")

    andar(obj, "")
    return achados


def valores_de(stock, chave):
    """O valor de `chave` no bloco stock (dict) ou nos blocos (lista de dicts), como texto; vazio se não houver."""
    blocos = [stock] if isinstance(stock, dict) else [b for b in stock if isinstance(b, dict)] if isinstance(stock, list) else []
    achados = [str(b.get(chave)).strip() for b in blocos if b.get(chave) not in (None, "")]
    return ",".join(dict.fromkeys(achados))


def extrair_stock(item_da_api):
    """Como o stock de 1 item do pedido aparece: tipo (dict/lista/ausente/null/vazio), chaves, bloco cru e os 3 campos de origem."""
    if "stock" not in item_da_api:
        tipo, stock = "ausente (o item nem tem a chave stock)", None
    else:
        stock = item_da_api["stock"]
        if stock is None:
            tipo = "null"
        elif isinstance(stock, dict):
            tipo = "dict" if stock else "dict vazio"
        elif isinstance(stock, list):
            tipo = f"lista de {len(stock)}" if stock else "lista vazia"
        else:
            tipo = f"outro tipo ({type(stock).__name__})"
    chaves = sorted(stock.keys()) if isinstance(stock, dict) else sorted({k for b in stock if isinstance(b, dict) for k in b}) if isinstance(stock, list) else []
    return {
        "tipo": tipo, "chaves": chaves, "cru": stock,
        "node_id": valores_de(stock, "node_id"), "network_node_id": valores_de(stock, "network_node_id"), "store_id": valores_de(stock, "store_id"),
    }


def diagnosticar_stock(info, outros_campos_de_origem):
    if info["node_id"]:
        return "COM_NODE_ID"
    if info["network_node_id"]:
        return "SO_NETWORK_NODE_ID"
    if info["store_id"]:
        return "SO_STORE_ID"
    if info["chaves"]:
        return "STOCK_SEM_NODE_ID"
    return "SEM_STOCK_MAS_HA_OUTRO_CAMPO" if outros_campos_de_origem else "SEM_STOCK"


def analisar_pedido_da_api(pedido):
    """Lista branca do pedido: nada de comprador. Por item: o stock cru + diagnóstico. Mais a varredura do pedido inteiro."""
    caminhos = varrer_origem(pedido)
    fora_do_stock = {c: v for c, v in caminhos.items()
                     if not c.startswith("order_items[].stock") and any(p in c.rsplit(".", 1)[-1].lower() for p in ("node", "network"))}
    itens = []
    for indice, item in enumerate(pedido.get("order_items") or []):
        stock = extrair_stock(item)
        stock["diagnostico"] = diagnosticar_stock(stock, fora_do_stock)
        itens.append({
            "indice": indice, "mlb": dig(item, "item", "id"), "seller_sku": dig(item, "item", "seller_sku"), "quantidade": item.get("quantity"),
            "variation_id": dig(item, "item", "variation_id"), "chaves_do_item": sorted(item.keys()), "stock": stock,
        })
    return {
        "status": pedido.get("status"), "date_created": pedido.get("date_created"), "tags": pedido.get("tags") or [], "pack_id": pedido.get("pack_id"),
        "shipping_id": dig(pedido, "shipping", "id"), "canal": dig(pedido, "context", "channel"), "fluxos": dig(pedido, "context", "flows"),
        "itens": itens, "caminhos_de_origem": caminhos,
    }


def resumo_do_envio(corpo):
    origem = dig(corpo, "origin", "node", "node_id")
    return {
        "logistic_type": dig(corpo, "logistic", "type") or corpo.get("logistic_type"), "logistic_mode": dig(corpo, "logistic", "mode"),
        "status": corpo.get("status"), "substatus": corpo.get("substatus"), "origin_node_id": origem,
        "diagnostico": ("ORIGEM_" + ("FORA" if classificar_origem(origem, "") == "fora" else "FULL")) if origem else "ENVIO_SEM_ORIGEM",
        "caminhos_de_origem": varrer_origem(corpo),
    }


def escolher_amostra(linhas):
    """-> lista de alvos {grupo, order_id, criado_em, shipping_id, linhas}. Sem origem: recentes + antigas + espalhadas. Controle: com origem (Full e fora)."""
    vivas = [l for l in linhas if l["status"] != "cancelled"]
    por_pedido = defaultdict(list)
    for l in vivas:
        por_pedido[l["order_id"]].append(l)

    def alvo(grupo, order_id):
        itens = sorted(por_pedido[order_id], key=lambda l: l["posicao"])
        return {"grupo": grupo, "order_id": order_id, "criado_em": min(l["criado_em_ml"] for l in itens), "linhas": itens,
                "shipping_id": next((l["shipping_id"] for l in itens if l["shipping_id"]), None)}

    def instante(order_id):
        return min(l["criado_em_ml"] for l in por_pedido[order_id])

    sem = sorted((o for o, itens in por_pedido.items() if any(sem_origem(l) for l in itens)), key=instante)
    escolhidos = {}
    for o in sem[-RECENTES:][::-1] if RECENTES else []:
        escolhidos.setdefault(o, "recente")
    for o in sem[:ANTIGAS]:
        escolhidos.setdefault(o, "antiga")
    resto = [o for o in sem if o not in escolhidos]
    if ESPALHADAS and resto:
        quantos = min(ESPALHADAS, len(resto))
        for i in range(quantos):
            escolhidos.setdefault(resto[int(i * len(resto) / quantos)], "espalhada")
    alvos = [alvo(g, o) for o, g in escolhidos.items()]
    alvos.sort(key=lambda a: a["criado_em"], reverse=True)

    com_origem = sorted((o for o, itens in por_pedido.items() if all(not sem_origem(l) for l in itens)), key=instante)
    fora = [o for o in com_origem if any(origem_da_linha(l) == "fora" for l in por_pedido[o])]
    full = [o for o in com_origem if o not in fora]
    desejados = [("controle Full (recente)", full[-1:]), ("controle Full (antigo)", full[:1]), ("controle fora do Full (recente)", fora[-1:]), ("controle Full (recente 2)", full[-2:-1])]
    controles = {}
    for grupo, ids in desejados:
        for o in ids:
            if o not in escolhidos and o not in controles and len(controles) < COM_ORIGEM_PARA_COMPARAR:
                controles[o] = grupo
    return alvos + [alvo(g, o) for o, g in controles.items()]


def linha_de_stock(rotulo_da_fonte, resumo_do_pedido, posicoes_sem_origem):
    """Mostra, para cada item da resposta, o bloco stock cru e o diagnóstico."""
    for item in resumo_do_pedido["itens"]:
        s = item["stock"]
        marca = " [yellow](sem origem no banco)[/]" if item["indice"] in posicoes_sem_origem else ""
        console.print(f"    {rotulo_da_fonte} item {item['indice']}{marca}: stock {t(s['tipo'])} = {t(json_compacto(s['cru']))}")
        console.print(f"        node_id={t(s['node_id'] or '-')} · network_node_id={t(s['network_node_id'] or '-')} · store_id={t(s['store_id'] or '-')} → [bold]{s['diagnostico']}[/]")
    if not resumo_do_pedido["itens"]:
        console.print(f"    {rotulo_da_fonte}: o pedido veio sem order_items")


def consultar_alvo(alvo, numero, total):
    order_id = alvo["order_id"]
    posicoes_sem_origem = {l["posicao"] for l in alvo["linhas"] if sem_origem(l)}
    saida = {
        "grupo": alvo["grupo"], "order_id": order_id, "criado_em": instante_em_brasilia(alvo["criado_em"]).isoformat(timespec="seconds"),
        "banco": [{"posicao": l["posicao"], "mlb": l["mlb"], "seller_sku": l["seller_sku"], "quantidade": l["quantidade"], "node_id": l["node_id"],
                   "store_id": l["store_id"], "status": l["status"], "catalogo": l["catalogo"], "com_desconto": l["com_desconto"], "pack_id": l["pack_id"],
                   "shipping_id": l["shipping_id"], "atualizado_em": str(l["atualizado_em"])} for l in alvo["linhas"]],
        "api_pedido": None, "api_busca": None, "envio": None,
    }
    un = unidades(alvo["linhas"])
    console.print(f"\n[bold]#{numero}/{total} · {alvo['grupo']}[/] · pedido {order_id} · {instante_em_brasilia(alvo['criado_em']):%d/%m/%Y %H:%M:%S} · {un} un · {len(alvo['linhas'])} item(ns)")
    for l in alvo["linhas"]:
        console.print(f"    banco: posição {l['posicao']} · {l['mlb']} · node_id={t(repr(l['node_id']))} store_id={t(repr(l['store_id']))} → {origem_da_linha(l)}")

    # a) o pedido, hoje
    r = chamar_com_repeticao("pedido", f"pedido {order_id}", f"/orders/{order_id}", None)
    if r["http"] == 200 and isinstance(r["_corpo"], dict):
        saida["api_pedido"] = {"http": 200, "resumo": analisar_pedido_da_api(r["_corpo"])}
        linha_de_stock("GET /orders/{id}    ", saida["api_pedido"]["resumo"], posicoes_sem_origem)
    else:
        saida["api_pedido"] = {"http": r["http"], "erro": r["erro"]}
        console.print(f"    GET /orders/{{id}}: sem resposta útil (HTTP {r['http']})")

    # b) a busca, no caminho do coletor
    if COMPARAR_COM_A_BUSCA:
        criado = instante_em_brasilia(alvo["criado_em"])
        params = {
            "seller": user_id, "order.date_created.from": formatar_data_para_filtro(criado - JANELA_DA_BUSCA),
            "order.date_created.to": formatar_data_para_filtro(criado + JANELA_DA_BUSCA), "sort": "date_desc", "limit": 50,
        }
        r = chamar_com_repeticao("busca", f"busca em volta de {order_id}", "/orders/search", params)
        if r["http"] == 200 and isinstance(r["_corpo"], dict):
            resultados = r["_corpo"].get("results") or []
            achado = next((p for p in resultados if str(p.get("id")) == str(order_id)), None)
            if achado:
                saida["api_busca"] = {"http": 200, "pedidos_na_janela": len(resultados), "resumo": analisar_pedido_da_api(achado)}
                linha_de_stock("GET /orders/search ", saida["api_busca"]["resumo"], posicoes_sem_origem)
            else:
                saida["api_busca"] = {"http": 200, "pedidos_na_janela": len(resultados), "resumo": None}
                console.print(f"    GET /orders/search: o pedido NÃO veio na janela ({len(resultados)} pedidos na janela)")
        else:
            saida["api_busca"] = {"http": r["http"], "erro": r["erro"]}
            console.print(f"    GET /orders/search: sem resposta útil (HTTP {r['http']})")

    # c) o envio
    shipping_id = dig(saida["api_pedido"], "resumo", "shipping_id") or alvo["shipping_id"]
    if CONSULTAR_ENVIO:
        if not shipping_id:
            saida["envio"] = {"http": None, "resumo": {"diagnostico": "SEM_ENVIO"}}
            console.print("    GET /shipments/{id}: o pedido não tem shipping.id → SEM_ENVIO")
        else:
            r = chamar_com_repeticao("envio", f"envio do pedido {order_id}", f"/shipments/{shipping_id}", None, {"x-format-new": "true"})
            if r["http"] == 200 and isinstance(r["_corpo"], dict):
                resumo = resumo_do_envio(r["_corpo"])
                saida["envio"] = {"http": 200, "resumo": resumo}
                console.print(f"    GET /shipments/{{id}}: logistic.type={t(str(resumo['logistic_type']))} · origin.node.node_id={t(str(resumo['origin_node_id'] or '-'))} "
                              f"· status={t(str(resumo['status']))}/{t(str(resumo['substatus']))} → [bold]{resumo['diagnostico']}[/]")
            else:
                saida["envio"] = {"http": r["http"], "erro": r["erro"], "resumo": {"diagnostico": f"ERRO_{r['http']}"}}
                console.print(f"    GET /shipments/{{id}}: sem resposta útil (HTTP {r['http']})")
    return saida


# ============================== PARTE 3: resumo, leitura e JSON ==============================

def diagnostico_do_item(saida, fonte, indice):
    """Diagnóstico do item `indice` na fonte ('api_pedido' ou 'api_busca'); texto curto quando não há resposta."""
    bloco = saida.get(fonte)
    if not bloco:
        return "(não consultado)"
    resumo = bloco.get("resumo")
    if not resumo:
        return f"(sem resposta: HTTP {bloco.get('http')})" if bloco.get("http") != 200 else "(pedido fora da janela)"
    item = next((i for i in resumo["itens"] if i["indice"] == indice), None)
    return item["stock"]["diagnostico"] if item else "(item não veio)"


def mostrar_resumo_da_api(amostra):
    console.rule("[bold]PARTE 3 · Diagnóstico da amostra")
    if not amostra:
        console.print("Nenhum pedido foi consultado na API.")
        return
    combinacoes = Counter()
    for s in amostra:
        eh_sem_origem = s["grupo"] in ("recente", "antiga", "espalhada")
        rotulo = f"sem origem · {s['grupo']}" if eh_sem_origem else "controle (com origem)"
        for l in s["banco"]:
            if eh_sem_origem and (l["node_id"] or l["store_id"]):
                continue
            envio = dig(s, "envio", "resumo", "diagnostico") or "(não consultado)"
            combinacoes[(rotulo, diagnostico_do_item(s, "api_pedido", l["posicao"]), diagnostico_do_item(s, "api_busca", l["posicao"]), envio)] += 1
    tabela = Table(title="Itens da amostra: o que cada fonte da API devolve", box=box.SIMPLE_HEAD, title_justify="left")
    for coluna in ("grupo (no banco)", "stock no GET do pedido", "stock na BUSCA (coletor)", "envio", "itens"):
        tabela.add_column(coluna, justify="right" if coluna == "itens" else "left")
    for (grupo, pedido, busca, envio), qtd in sorted(combinacoes.items()):
        tabela.add_row(grupo, pedido, busca, envio, str(qtd))
    console.print(tabela)
    if any(c[1].startswith("(sem resposta") or c[2].startswith("(sem resposta") for c in combinacoes):
        console.print("  [dim](sem resposta: HTTP 404 ou 403 no GET do pedido = o ML não devolveu esse pedido hoje; vale olhar a idade desses pedidos na tela acima.)[/]")

    por_tipo_de_logistica = Counter((dig(s, "envio", "resumo", "logistic_type") or "-", dig(s, "envio", "resumo", "origin_node_id") or "-") for s in amostra if s["grupo"] in ("recente", "antiga", "espalhada") and dig(s, "envio", "resumo", "diagnostico") not in (None, "SEM_ENVIO"))
    if por_tipo_de_logistica:
        console.print("Envios das vendas SEM origem: " + t(" · ".join(f"{tipo} @ {no} ×{q}" for (tipo, no), q in por_tipo_de_logistica.most_common())))

    # caminhos com cara de origem: grupo sem origem x controle
    grupos = {"sem origem": [s for s in amostra if s["grupo"] in ("recente", "antiga", "espalhada")], "controle": [s for s in amostra if s["grupo"].startswith("controle")]}
    caminhos = defaultdict(lambda: {"sem origem": 0, "controle": 0, "valores": Counter()})
    for nome, lista in grupos.items():
        for s in lista:
            vistos = {}
            for fonte in ("api_pedido", "api_busca"):
                for c, v in (dig(s, fonte, "resumo", "caminhos_de_origem") or {}).items():
                    vistos.setdefault(c, set()).update(v)
            for c, v in vistos.items():
                caminhos[c][nome] += 1
                caminhos[c]["valores"].update(v)
    if caminhos:
        tabela = Table(title="Campos do pedido com cara de origem de estoque (nº de pedidos em que aparecem)", box=box.SIMPLE_HEAD, title_justify="left")
        tabela.add_column("caminho")
        tabela.add_column(f"sem origem (de {len(grupos['sem origem'])})", justify="right")
        tabela.add_column(f"controle (de {len(grupos['controle'])})", justify="right")
        tabela.add_column("valores mais comuns")
        for c, d in sorted(caminhos.items()):
            tabela.add_row(t(c), str(d["sem origem"]), str(d["controle"]), t(" | ".join(v for v, _ in d["valores"].most_common(3))))
        console.print(tabela)
    resultado["caminhos_de_origem_agregados"] = {c: {"sem_origem": d["sem origem"], "controle": d["controle"], "valores": dict(d["valores"].most_common(5))} for c, d in caminhos.items()}
    resultado["combinacoes_de_diagnostico"] = [{"grupo": g, "stock_no_pedido": p, "stock_na_busca": b, "envio": e, "itens": q} for (g, p, b, e), q in sorted(combinacoes.items())]

    usados = {c[1] for c in combinacoes} | {c[2] for c in combinacoes}
    console.print("\n[bold]Como ler cada diagnóstico[/]")
    for codigo, texto in LEITURA_DO_STOCK.items():
        if codigo in usados:
            console.print(f"  [bold]{codigo}[/]: {t(texto)}")
    for codigo, texto in LEITURA_DO_ENVIO.items():
        if codigo in {c[3] for c in combinacoes}:
            console.print(f"  [bold]{codigo}[/]: {t(texto)}")
    console.print("  [dim]Diferença entre o GET do pedido e a BUSCA, ou entre pedidos recentes e antigos, é a pista principal. Mande o JSON (ou esta tela) e decidimos a correção no Ciclo 3.[/]")


# ============================== PARTE 2A e 4: depósitos do vendedor (GET /users/{id}/stores/search) ==============================

def tipo_do_valor(valor):
    """Só a FORMA do valor (dict com tais chaves, lista de N, str, int...), nunca o conteúdo."""
    if isinstance(valor, dict):
        return "dict[" + ",".join(sorted(str(k) for k in valor)[:14]) + "]"
    if isinstance(valor, list):
        return f"lista[{len(valor)}]"
    return type(valor).__name__


def valor_liberado(chave, valor):
    """O VALOR só é guardado para os campos da lista branca; dos outros (ex.: location = endereço) vai só o nome das chaves e o tipo."""
    if chave in CAMPOS_DO_DEPOSITO_COM_VALOR_LIBERADO:
        return sem_id(json_compacto(valor, 120))
    return "(valor não gravado)"


def consultar_depositos():
    """GET /users/{id}/stores/search?tags=stock_location (doc 'Estoque multi-origem'): os depósitos do próprio vendedor. Pagina de 50 em 50."""
    console.rule("[bold]PARTE 2A · Chamada extra: depósitos do vendedor")
    console.print("GET /users/{id}/stores/search?tags=stock_location (documentada em 'Estoque multi-origem'). Guarda só: id, descrição, status, tags, "
                  "network_node_id e services; do endereço (location) guarda só o NOME dos campos.")
    lojas, total, paginas, erro, http = [], None, 0, None, None
    for pagina in range(MAX_PAGINAS_DE_DEPOSITOS):
        offset = pagina * 50
        params = {"tags": "stock_location"}
        if offset:
            params["offset"] = offset
        r = chamar_com_repeticao("depositos", f"depósitos pág {pagina + 1}", f"/users/{user_id}/stores/search", params)
        http, corpo = r["http"], r["_corpo"]
        if http != 200 or not isinstance(corpo, dict):
            erro = r["erro"] or f"HTTP {http}"
            break
        resultados = corpo.get("results") or []
        total = (corpo.get("paging") or {}).get("total", total)
        lojas.extend(l for l in resultados if isinstance(l, dict))
        paginas += 1
        if not resultados or total is None or len(lojas) >= total:
            break
    analisadas = [{
        "id": str(l.get("id") or ""), "network_node_id": str(l.get("network_node_id") or ""), "descricao": l.get("description"), "status": l.get("status"),
        "tags": l.get("tags"), "servicos": l.get("services"),
        "campos": {k: valor_liberado(k, v) for k, v in sorted(l.items())}, "tipos": {k: tipo_do_valor(v) for k, v in sorted(l.items())},
    } for l in lojas]
    dep = {
        "http": http, "total_informado_pela_api": total, "paginas_lidas": paginas, "erro": erro, "lojas": analisadas,
        "ids": sorted({x["id"] for x in analisadas if x["id"]}), "nos": sorted({x["network_node_id"] for x in analisadas if x["network_node_id"]}),
    }
    resultado["depositos"] = dep
    console.print(f"  → {len(analisadas)} depósito(s) lido(s) (total informado pela API: {total}) em {paginas} página(s)" + (f" · [red]erro: {t(str(erro)[:120])}[/]" if erro else ""))
    return dep


def origem_com_depositos(l, ids, nos):
    """A regra PROPOSTA: store_id preenchido OU nó que é depósito do vendedor = fora; outro nó = Full; sem nó = indefinido. Sem lista (nos vazio) vale 'só store_id'."""
    if l["store_id"]:
        return "fora"
    if l["node_id"] and l["node_id"] in nos:
        return "fora"
    if l["node_id"]:
        return "full"
    return "indefinido"


def cruzar_banco_com_depositos(linhas, dep):
    """Compara, linha a linha (vendas não canceladas), a regra ATUAL da tela com a regra que usa a lista de depósitos."""
    ids, nos = set(dep["ids"]), set(dep["nos"])
    matriz = defaultdict(lambda: {"un": 0, "linhas": 0})
    por_no, por_store = {}, {}
    for l in linhas:
        if l["status"] == "cancelled":
            continue
        atual, nova, q, dia = origem_da_linha(l), origem_com_depositos(l, ids, nos), l["quantidade"], l["dia_venda"]
        matriz[(atual, nova)]["un"] += q
        matriz[(atual, nova)]["linhas"] += 1
        n = por_no.setdefault(l["node_id"] or "(sem node_id)", {
            "un": 0, "linhas": 0, "atual": Counter(), "com_lista": Counter(), "mudancas": Counter(), "store_ids": Counter(), "primeiro_dia": dia, "ultimo_dia": dia})
        n["un"] += q
        n["linhas"] += 1
        n["atual"][atual] += q
        n["com_lista"][nova] += q
        if atual != nova:
            n["mudancas"][f"{atual} → {nova}"] += q
        n["primeiro_dia"], n["ultimo_dia"] = min(n["primeiro_dia"], dia), max(n["ultimo_dia"], dia)
        if l["store_id"]:
            n["store_ids"][l["store_id"]] += q
            s = por_store.setdefault(l["store_id"], {"un": 0, "primeiro_dia": dia, "ultimo_dia": dia})
            s["un"] += q
            s["primeiro_dia"], s["ultimo_dia"] = min(s["primeiro_dia"], dia), max(s["ultimo_dia"], dia)
    nos_do_banco = [{
        "node_id": nome, "un": n["un"], "linhas": n["linhas"], "atual": dict(n["atual"]), "com_lista": dict(n["com_lista"]), "mudancas": dict(n["mudancas"]),
        "store_ids": dict(n["store_ids"]), "no_esta_na_lista": nome in nos, "algum_store_id_esta_na_lista": any(s in ids for s in n["store_ids"]),
        "primeiro_dia": n["primeiro_dia"], "ultimo_dia": n["ultimo_dia"],
    } for nome, n in por_no.items()]
    nos_do_banco.sort(key=lambda x: (not x["mudancas"], -x["un"]))
    return {
        "un_total": sum(m["un"] for m in matriz.values()), "un_que_mudam": sum(m["un"] for (a, b), m in matriz.items() if a != b),
        "matriz": [{"atual": a, "com_lista": b, "un": m["un"], "linhas": m["linhas"]} for (a, b), m in sorted(matriz.items())],
        "nos": nos_do_banco, "store_ids_no_banco": {s: v for s, v in por_store.items()},
        "depositos_sem_venda_no_banco": [x["id"] or x["network_node_id"] for x in dep["lojas"]
                                         if x["id"] not in por_store and x["network_node_id"] not in por_no],
    }


def mostrar_depositos(linhas, dep):
    console.rule("[bold]PARTE 4 · Depósitos do vendedor (a chamada extra) × o que o banco tem")
    lista_vazia = not dep["lojas"]
    if dep["erro"]:
        console.print(f"[bold red]A chamada falhou: {t(str(dep['erro'])[:200])}[/] (HTTP {dep['http']}). Sem a lista, a coluna 'com a lista' abaixo vale como 'só store_id'.")
    elif lista_vazia:
        console.print("[yellow]A API respondeu 200, mas sem nenhum depósito com a tag stock_location. A coluna 'com a lista' abaixo vale como 'só store_id'.[/]")
    cruz = cruzar_banco_com_depositos(linhas, dep)
    resultado["cruzamento_banco_depositos"] = cruz

    if dep["lojas"]:
        tabela = Table(title="Depósitos devolvidos pela API (um por linha)", box=box.SIMPLE_HEAD, title_justify="left")
        for coluna in ("#", "id (= store_id)", "descrição", "status", "network_node_id (= node_id)", "serviços (stock_location)", "tags"):
            tabela.add_column(coluna)
        for coluna in ("un no banco com esse store_id", "un no banco com esse nó"):
            tabela.add_column(coluna, justify="right")
        tabela.add_column("vendas no banco (primeira → última)")
        por_nome = {n["node_id"]: n for n in cruz["nos"]}
        for i, d in enumerate(dep["lojas"], 1):
            s, n = cruz["store_ids_no_banco"].get(d["id"]), por_nome.get(d["network_node_id"])
            datas = [x for x in ((s or {}).get("primeiro_dia"), (n or {}).get("primeiro_dia")) if x] + [x for x in ((s or {}).get("ultimo_dia"), (n or {}).get("ultimo_dia")) if x]
            servicos = dig(d, "servicos", "stock_location")
            tabela.add_row(str(i), t(sem_id(d["id"] or "-")), t(sem_id(str(d["descricao"] or "-"))), t(str(d["status"] or "-")), t(sem_id(d["network_node_id"] or "-")),
                           t(", ".join(str(x) for x in servicos) if isinstance(servicos, list) else sem_id(json_compacto(d["servicos"], 60)) if d["servicos"] else "-"),
                           t(", ".join(str(x) for x in d["tags"]) if isinstance(d["tags"], list) else "-"),
                           str((s or {}).get("un", 0)), str((n or {}).get("un", 0)), f"{min(datas):%d/%m/%Y} → {max(datas):%d/%m/%Y}" if datas else "nenhuma venda")
        console.print(tabela)

        campos = defaultdict(lambda: {"em": 0, "tipos": set(), "valores": []})
        for d in dep["lojas"]:
            for k in d["tipos"]:
                c = campos[k]
                c["em"] += 1
                c["tipos"].add(d["tipos"][k])
                if d["campos"][k] not in c["valores"] and len(c["valores"]) < 3:
                    c["valores"].append(d["campos"][k])
        tabela = Table(title="Todos os campos que a API devolveu para cada depósito", box=box.SIMPLE_HEAD, title_justify="left")
        tabela.add_column("campo")
        tabela.add_column(f"em quantos (de {len(dep['lojas'])})", justify="right")
        tabela.add_column("tipo / forma")
        tabela.add_column("valor (só dos campos liberados)")
        for k, c in sorted(campos.items()):
            tabela.add_row(t(k), str(c["em"]), t(" | ".join(sorted(c["tipos"]))), t(" | ".join(c["valores"])))
        console.print(tabela)
        console.print("  [dim]Os campos sem valor (ex.: location) são o endereço do depósito: o script guarda só o nome dos campos, não o endereço.[/]")

    matriz = {(m["atual"], m["com_lista"]): m for m in cruz["matriz"]}
    origens = ("full", "fora", "indefinido")
    tabela = Table(title="Regra atual da tela → regra com a lista de depósitos (unidades; fora da diagonal = muda de origem)", box=box.SIMPLE_HEAD, title_justify="left")
    tabela.add_column("regra atual ↓  /  com a lista →")
    for o in origens:
        tabela.add_column(o if o != "indefinido" else "sem origem", justify="right")
    for a in origens:
        celulas = []
        for b in origens:
            q = matriz.get((a, b), {"un": 0})["un"]
            celulas.append(f"[yellow]{q}[/]" if a != b and q else str(q))
        tabela.add_row(a if a != "indefinido" else "sem origem", *celulas)
    console.print(tabela)
    console.print(f"  {cruz['un_que_mudam']} un de {cruz['un_total']} ({texto_pct(cruz['un_que_mudam'], cruz['un_total'])}) mudariam de origem com a regra que usa a lista.")

    tabela = Table(title="Cada nó do banco × lista de depósitos (quem muda aparece primeiro)", box=box.SIMPLE_HEAD, title_justify="left")
    tabela.add_column("node_id")
    tabela.add_column("un", justify="right")
    for coluna in ("store_id (un)", "regra atual (un)", "com a lista (un)", "nó está na lista?", "store_id está na lista?", "o que muda (un)"):
        tabela.add_column(coluna)
    for n in cruz["nos"]:
        muda = "; ".join(f"{k}: {q}" for k, q in n["mudancas"].items())
        tabela.add_row(t(sem_id(n["node_id"])), str(n["un"]), t(sem_id(texto_de_origem(n["store_ids"]))), texto_de_origem(n["atual"]), texto_de_origem(n["com_lista"]),
                       "sim" if n["no_esta_na_lista"] else "não", ("sim" if n["algum_store_id_esta_na_lista"] else "não") if n["store_ids"] else "-",
                       f"[yellow]{t(muda)}[/]" if muda else "nada")
    console.print(tabela)

    console.print("\n[bold]O que isso nos diz[/]")
    para_full = [n for n in cruz["nos"] if "fora → full" in n["mudancas"]]
    para_fora = [n for n in cruz["nos"] if "full → fora" in n["mudancas"]]
    if para_full:
        console.print(("  • Hoje contados como Fora do Full só porque o nó começa com BRP (sem store_id; a lista de depósitos não veio, então não dá para confirmar): " if lista_vazia
                       else "  • Hoje contados como Fora do Full, mas o nó NÃO é depósito do vendedor (e não tem store_id): ")
                      + t(sem_id(" · ".join(f"{n['node_id']} ({n['mudancas']['fora → full']} un)" for n in para_full))) + ". Provável centro do Full contado como Fora.")
    if para_fora:
        console.print("  • Hoje contados como Full, mas o nó É depósito do vendedor: " + t(sem_id(" · ".join(f"{n['node_id']} ({n['mudancas']['full → fora']} un)" for n in para_fora))) + ".")
    if not para_full and not para_fora:
        console.print("  • As duas regras dão o mesmo resultado em todas as vendas do banco." + (" (a lista veio vazia: só vale como 'só store_id')" if lista_vazia else ""))
    if cruz["depositos_sem_venda_no_banco"]:
        console.print("  • Depósitos da lista sem nenhuma venda no banco: " + t(sem_id(" · ".join(cruz["depositos_sem_venda_no_banco"]))) + ".")
    console.print("[bold]Como isso pode ajudar[/]")
    for linha in (
        "o 'id' do depósito é o store_id do pedido e o 'network_node_id' é o node_id do pedido: se o pedido traz um deles, o estoque é do vendedor (Fora do Full) com certeza, sem adivinhar pelo prefixo BRP;",
        "nó que não está na lista e não tem store_id seria um centro do Mercado Livre (Full): a confirmação vem do envio (ligue ENVIOS_DE_PEDIDOS_FORA_DO_FULL = 12 e veja logistic.type = fulfillment);",
        "'serviços' diz que tipos de envio o depósito atende (na doc: cross_docking = Coletas, xd_drop_off = Places); não separa Coleta de Agência por pedido;",
        "a lista é pequena e quase não muda: dá para guardar no banco e atualizar de vez em quando (1 chamada por conta), em vez de 1 chamada por pedido.",
    ):
        console.print(f"  • {t(linha)}")


def consultar_envios_de_pedidos_fora_do_full(linhas, dep):
    """OPCIONAL (ENVIOS_DE_PEDIDOS_FORA_DO_FULL > 0): o logistic.type do envio de pedidos 'fora do Full' de 2 grupos — depósito do vendedor x nó que só parece (BRP...)."""
    console.rule("[bold]PARTE 2C · Envios de pedidos 'fora do Full' (opcional)")
    ids, nos = (set(dep["ids"]), set(dep["nos"])) if dep else (set(), set())
    g1, g2 = "depósito do vendedor (store_id ou nó da lista)", "regra atual diz Fora, mas sem store_id e nó fora da lista"
    grupos, vistos = {g1: [], g2: []}, set()
    for l in sorted(linhas, key=lambda x: x["criado_em_ml"], reverse=True):
        if l["status"] == "cancelled" or l["order_id"] in vistos or not l["shipping_id"]:
            continue
        atual, nova = origem_da_linha(l), origem_com_depositos(l, ids, nos)
        if atual == "fora" and nova == "fora":
            grupos[g1].append(l)
            vistos.add(l["order_id"])
        elif atual == "fora" and nova == "full":
            grupos[g2].append(l)
            vistos.add(l["order_id"])
    n = ENVIOS_DE_PEDIDOS_FORA_DO_FULL
    q1 = min(len(grupos[g1]), (n + 1) // 2)
    q2 = min(len(grupos[g2]), n - q1)
    q1 = min(len(grupos[g1]), n - q2)
    escolhidos = []
    for nome, quantos in ((g1, q1), (g2, q2)):
        lista = grupos[nome]
        escolhidos += [(nome, lista[int(i * len(lista) / quantos)]) for i in range(quantos)] if quantos else []
    console.print(f"{len(grupos[g1])} pedidos no grupo 1 e {len(grupos[g2])} no grupo 2 (com shipping.id); consultando {len(escolhidos)} envios (espalhados no tempo).")
    saida = []
    for indice, (nome, l) in enumerate(escolhidos, 1):
        r = chamar_com_repeticao("envio", f"envio fora do Full {indice}/{len(escolhidos)}", f"/shipments/{l['shipping_id']}", None, {"x-format-new": "true"})
        item = {"grupo": nome, "order_id": l["order_id"], "dia_venda": l["dia_venda"], "node_id": l["node_id"], "store_id": l["store_id"], "http": r["http"]}
        if r["http"] == 200 and isinstance(r["_corpo"], dict):
            item.update({"logistic_type": dig(r["_corpo"], "logistic", "type") or r["_corpo"].get("logistic_type"), "logistic_mode": dig(r["_corpo"], "logistic", "mode"),
                         "origin_node_id": dig(r["_corpo"], "origin", "node", "node_id"), "status": r["_corpo"].get("status")})
        saida.append(item)
    resultado["envios_de_pedidos_fora_do_full"] = saida
    return saida


def mostrar_envios_de_pedidos_fora_do_full(saida):
    if not saida:
        return
    tabela = Table(title="Envio dos pedidos 'fora do Full' consultados (logistic.type por grupo)", box=box.SIMPLE_HEAD, title_justify="left")
    for coluna in ("grupo", "node_id do pedido", "logistic.type", "mode", "origin.node.node_id do envio"):
        tabela.add_column(coluna)
    tabela.add_column("pedidos", justify="right")
    contagem = Counter((s["grupo"], sem_id(str(s["node_id"] or "-")), str(s.get("logistic_type") or f"(HTTP {s['http']})"), str(s.get("logistic_mode") or "-"), sem_id(str(s.get("origin_node_id") or "-"))) for s in saida)
    for (grupo, no, tipo, modo, origem), q in sorted(contagem.items()):
        tabela.add_row(t(grupo), t(no), t(tipo), t(modo), t(origem), str(q))
    console.print(tabela)
    console.print("  [dim]Se o grupo 'depósito do vendedor' só tiver cross_docking/self_service/xd_drop_off e o outro grupo tiver fulfillment, a lista de depósitos separa certo.[/]")


def mostrar_chamadas():
    if not chamadas:
        return
    http = Counter((c["tipo"], c["http"]) for c in chamadas)
    console.print("\nChamadas à API (cada tentativa conta): " + t(" · ".join(f"{tipo} HTTP {codigo}: {q}" for (tipo, codigo), q in sorted(http.items(), key=lambda x: (x[0][0], str(x[0][1]))))))


def salvar_json(banco, amostra):
    saida = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"), "conta": CONTA,
        "config": {
            "consultar_api": CONSULTAR_API, "recentes": RECENTES, "antigas": ANTIGAS, "espalhadas": ESPALHADAS, "com_origem_para_comparar": COM_ORIGEM_PARA_COMPARAR,
            "comparar_com_a_busca": COMPARAR_COM_A_BUSCA, "consultar_envio": CONSULTAR_ENVIO, "pausa_entre_chamadas_s": PAUSA_ENTRE_CHAMADAS_S,
        },
        "banco": banco, "amostra": amostra, **resultado,
        "chamadas": [{k: v for k, v in c.items() if k != "_corpo"} for c in chamadas],
    }
    texto = json.dumps(saida, ensure_ascii=False, indent=2, default=str)
    if user_id and str(user_id) in texto:          # rede de segurança: o id nunca deveria estar aqui
        texto = texto.replace(str(user_id), "***")
    CAMINHO_SAIDA.write_text(texto, encoding="utf-8")


def main():
    global user_id
    load_dotenv(dotenv_path=_RAIZ_DO_PROJETO / ".env")
    user_id = (os.getenv(f"{CONTA}_USER_ID") or "").strip() or None    # carregado já aqui para mascarar o seller_id (ele aparece dentro do nó próprio: BRP<seller_id>1)
    console.print(f"[bold]Vendas sem origem informada[/] · conta {CONTA} · só leitura (SELECT no banco, GET na API)\n")
    linhas = ler_linhas_do_banco()
    banco = analisar_banco(linhas)
    mostrar_banco(banco)
    amostra, depositos, envios_fora = [], None, None
    try:
        if CONSULTAR_API:
            if not user_id:
                console.print(f"[bold red]{CONTA}_USER_ID não encontrado no .env da raiz do repo. Só a PARTE 1 foi feita.[/]")
            else:
                if CONSULTAR_DEPOSITOS:
                    depositos = consultar_depositos()
                if CONSULTAR_AMOSTRA_DE_PEDIDOS and banco["un_sem_origem"]:
                    alvos = escolher_amostra(linhas)
                    por_alvo = 1 + COMPARAR_COM_A_BUSCA + CONSULTAR_ENVIO
                    console.rule("[bold]PARTE 2B · Re-busca de uma amostra de pedidos na API")
                    console.print(f"{len(alvos)} pedidos ({sum(1 for a in alvos if not a['grupo'].startswith('controle'))} sem origem + "
                                  f"{sum(1 for a in alvos if a['grupo'].startswith('controle'))} de controle) · até {len(alvos) * por_alvo} chamadas, 1 por segundo; "
                                  f"cada 429/5xx repete a MESMA chamada (até {MAX_TENTATIVAS_POR_CHAMADA} tentativas) e aparece abaixo.")
                    for numero, alvo in enumerate(alvos, 1):
                        amostra.append(consultar_alvo(alvo, numero, len(alvos)))
                if ENVIOS_DE_PEDIDOS_FORA_DO_FULL > 0:
                    envios_fora = consultar_envios_de_pedidos_fora_do_full(linhas, depositos)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Interrompido (Ctrl+C). Mostrando e salvando o que já foi medido.[/]")
    finally:
        if amostra:
            mostrar_resumo_da_api(amostra)
        if depositos:
            mostrar_depositos(linhas, depositos)
        if envios_fora:
            mostrar_envios_de_pedidos_fora_do_full(envios_fora)
        mostrar_chamadas()
        salvar_json(banco, amostra)
        console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem seller_id, sem token, sem dado de comprador.")


if __name__ == "__main__":
    main()
