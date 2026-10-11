# scripts_exploracao_ML/investigar_vendas_full_por_codigo.py
# ============================================================================================================================
# AVISO — ENDPOINT DE OPERAÇÕES DO FULL ABANDONADO PARA O HISTÓRICO DE VENDAS (decisão do Matheus, 10/10/2026, 20:04)
# ============================================================================================================================
# Este código usa GET /stock/fulfillment/operations/search. Ele FUNCIONA (90 dias de 1 SKU = 3 Códigos ML foram coletados),
# mas foi ABANDONADO: o endpoint é instável e a necessidade é rodar para MAIS DE MIL SKUs. NÃO APAGUE — guarda o que foi
# aprendido. Notas completas no vault: 05_Integracao_Mercado_Livre/Historico_de_Vendas/ (descoberta, decisão, dúvida, checkpoint).
#
# PROBLEMAS OBSERVADOS (10/10/2026, dado real, conta Magazine, 1 SKU = 3 Códigos ML):
#  1) 429 FREQUENTE: 8 de 25 chamadas na sondagem (18:33-18:38) e 34 de 51 tentativas nas 3 rodadas reais do coletor (19:43-19:46).
#     Corpo: {"message": "Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota", "error": "over_quota"}
#     NÃO é o texto "requests por minuto" da doc: cita uma entidade interna; o ESCOPO da cota é DESCONHECIDO (app, vendedor, global?).
#  2) SEM PISTA DE QUANDO TENTAR DE NOVO: nenhuma resposta traz Retry-After nem cabeçalho de limite.
#  3) PESO E ESPAÇAMENTO NÃO MUDAM A TAXA: chamada leve (1 Código, limit=1) 3/8 x pesada (3 Códigos, limit=1000) 2/8 com 429;
#     esperar 15 s entre as chamadas ainda deu 5 de 16 primeiras páginas com 429. Os 429 vêm em rajadas e a taxa variou no tempo
#     (32% às 18:33 x 67% às 19:43) — a causa é desconhecida.
#  4) SCROLL FRÁGIL: repetir o MESMO scroll depois de um 429 costuma virar 404 {"message": "Operation not found"} (2 de 2 nas
#     rodadas reais; 1 de 3 passou na sondagem). O coletor recomeça a janela e descarta as linhas repetidas (2000 na rodada de 90 dias).
#  5) Chamadas SEM scroll: 13 de 15 terminaram em 200 nas rodadas reais; 1 esgotou as 5 tentativas com 429 e 1 foi interrompida.
#  6) 120 e 150 dias NÃO foram testados (Ctrl+C durante a espera de 60 s, antes da parte antiga): só 90 dias foram validados.
#  7) A profundidade do histórico NÃO é a causa: o 429 apareceu também na janela dos 7 dias mais recentes (11 de 14 tentativas).
#
# NUNCA TESTADO: máximo de Códigos ML por chamada; omitir "type" (1 chamada em vez de 4 por janela); dividir a janela por data até
# caber em 1000 operações (sem scroll); se o horário muda a taxa. Não há contato com o Mercado Livre por ora.
#
# CAMINHO NOVO: GET /orders/search (ver o checkpoint 'Checkpoint - Historico de Vendas e Calendario de Vendas' no vault).
# Textos mais abaixo que dizem que o limite é "por minuto" ou que o 429 "passa depois de esperar" foram escritos ANTES desses
# testes: valem os fatos deste aviso.
#
# ESCOPO: script do Passo 2 (investigação). Os fatos de cancelamento (61 de 62 pareados por envio + Código) continuam válidos.
# ============================================================================================================================
#
# Objetivo: ver quantas unidades o FULL vendeu por dia, em cada Código ML de 1 produto (SKU),
# nos últimos 90 dias completos (00h a 24h, horário de Brasília) + hoje (parcial), usando as
# OPERAÇÕES DE ESTOQUE do Full: GET /stock/fulfillment/operations/search.
#
# PASSO 2 (10/10/2026) — REGRA DO MATHEUS: "venda cancelada NÃO conta no dia da venda original"
# (comprou dia 05, cancelou dia 10 -> o dia 05 não contém essa venda). Por isso o script:
#   1) busca 4 tipos de operação de saída (doc "Envios Fulfillment"):
#        SALE_CONFIRMATION         reserva as unidades pra venda            (a VENDA)
#        SALE_CANCELATION          cancela a reserva                         (tira a venda do dia original)
#        SALE_DELIVERY_CANCELATION venda não entregue, volta ao depósito     (só observação, NÃO desconta)
#        SALE_RETURN               devolução pelo comprador                  (só observação, NÃO desconta)
#   2) casa cada cancelamento com a venda dele pelo ENVIO (shipment_id) + Código ML;
#   3) desconta o cancelamento no DIA DA VENDA (nunca no dia em que o cancelamento aconteceu);
#   4) mostra como os cancelamentos casaram (quantos casam, atraso em dias, quantos ficam sem par),
#      pra a regra ser conferida em dado real antes de virar tabela do banco.
#
# Por que operações e não pedidos: 1 chamada traz até 1000 operações e aceita vários Códigos ML
# separados por vírgula (doc "Envios Fulfillment"), então o custo é de poucas chamadas mesmo em
# produto de alto giro. A doc limita o intervalo de datas a 60 dias por chamada; por isso o período
# é fatiado em janelas (aqui, de 46 dias).
#
# Só leitura (GET). Não toca no banco. Não chama /orders nem /shipments. A operação não traz dado de
# comprador, e o seller_id não vai pra tela nem pro JSON (mensagens de erro da API também passam
# por uma máscara antes de aparecer). O JSON deste passo tem nome próprio (não sobrescreve o do
# passo 1) e é sobrescrito a cada execução.
#
# O que este script NÃO responde:
#   - Qual MLB vendeu: a operação traz o Código ML (inventory_id) e o envio (shipment_id), mas não
#     o MLB. Dividir um Código entre os seus MLBs exige os pedidos.
#   - Vendas fora do Full (Coleta, Agência, Flex): essas não geram operação no estoque do Full.
#   - Dias recentes ainda podem cair: um cancelamento que ainda não aconteceu não pode ser descontado.

import json
import os
import shutil
import statistics
import sys
import time
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
CONTA = "MB"                    # "MB" (Magazine) ou "SV" (Samvale)
SKU = "F7908050719121.001"      # só rótulo (tela e nome do JSON); a busca é pelos Códigos ML abaixo
# Códigos ML (inventory_id) do SKU. Fonte: detalhes_mlbs.json da Magazine (gerado em 07/10/2026 23:05).
# RWBD51502 hoje está em Coleta, mas já esteve no Full: pode ter vendido pelo Full dentro dos 90 dias.
CODIGOS_ML = ["QAVX18725", "RWBD51502", "OPXW24140"]
# Tipos buscados. Os 2 primeiros formam a regra (venda e cancelamento); os outros 2 são só observação.
TIPOS = ["SALE_CONFIRMATION", "SALE_CANCELATION", "SALE_DELIVERY_CANCELATION", "SALE_RETURN"]
# ========================================

TIPO_VENDA = "SALE_CONFIRMATION"
TIPO_CANCELA = "SALE_CANCELATION"
TIPOS_DA_REGRA = [TIPO_VENDA, TIPO_CANCELA]
ROTULO_DO_TIPO = {
    "SALE_CONFIRMATION": "venda (confirmação)",
    "SALE_CANCELATION": "cancelamento da venda",
    "SALE_DELIVERY_CANCELATION": "venda não entregue",
    "SALE_RETURN": "devolução pelo comprador",
}
ENDPOINT = "/stock/fulfillment/operations/search"
DIAS_TOTAL = 90                 # dias completos analisados (mais hoje, que é parcial)
DIAS_POR_JANELA_API = 46        # a doc limita a 60 dias por chamada; 46 deixa folga
LIMITE_POR_PAGINA = 1000        # máximo da doc
MAX_PAGINAS_POR_JANELA = 30     # trava de segurança (30 x 1000 operações por janela)
MAX_REINICIOS_POR_JANELA = 3    # se uma página de scroll der 404, recomeça a janela do zero (no máximo 3 vezes)
PAUSA_ENTRE_CHAMADAS_S = 1.0    # espaça as chamadas (a API devolve 429 "por minuto"; o cliente já espera e tenta de novo)
JANELAS_DE_DIAS = [("1 dia (ontem)", 1), ("3 dias", 3), ("7 dias", 7), ("15 dias", 15), ("30 dias", 30), ("90 dias", 90)]
FAIXAS_DE_ATRASO = [("mesmo dia", 0, 0), ("1 dia", 1, 1), ("2 a 3 dias", 2, 3), ("4 a 7 dias", 4, 7), ("8 a 30 dias", 8, 30), ("mais de 30 dias", 31, 10 ** 6)]
NOME_LOG = "investigar_vendas_full_por_codigo"

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_vendas_full_cancelamentos_{SKU}_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

contador = {"chamadas": 0, "segundos": 0.0}
ultima_chamada_em = {"t": None}
# a doc mostra o tipo em MAIÚSCULAS nos exemplos e em minúsculas na lista de parâmetros; começa em
# MAIÚSCULAS e, só se a API reclamar do tipo na 1ª chamada, tenta minúsculas (plano B, registrado no JSON)
forma_do_tipo = {tipo: tipo for tipo in TIPOS}
plano_b_tipo_minusculo = {"tentado": set(), "funcionou": set()}   # tipos em que o plano B foi tentado / deu certo
# 1 coluna de margem abaixo da largura do terminal: sem isso, no Windows a linha que ocupa a largura
# toda gruda na linha de baixo (mesmo cuidado que os outros scripts já têm)
console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(80, 24)).columns - 1, 20))
t = escape  # protege texto vindo da API de ser lido como marcação do rich
user_id = None


def sem_id(texto):
    """Troca o seller_id por *** antes de mostrar qualquer texto que veio da API."""
    texto = str(texto)
    return texto.replace(str(user_id), "***") if user_id else texto


def n_br(valor, casas=0):
    """Número no padrão brasileiro: 1.234 e 12,50."""
    texto_numero = f"{valor:,.{casas}f}"
    return texto_numero.replace(",", "X").replace(".", ",").replace("X", ".")


def barra(valor, maximo, largura=20):
    """Barrinha proporcional ao valor (ASCII se o terminal não aceitar Unicode)."""
    if not maximo or valor <= 0:
        return ""
    caractere = "#" if console.options.ascii_only else "█"
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


def variacao_texto(atual, anterior):
    """'+12,3%' em verde, '-8,0%' em vermelho; '-' quando o bloco anterior foi zero (não dá pra comparar)."""
    if not anterior:
        return "[dim]-[/]"
    pct = (atual - anterior) / anterior * 100
    cor = "green" if pct > 0 else ("red" if pct < 0 else "dim")
    return f"[{cor}]{pct:+.1f}%[/]".replace(".", ",")


def ler_instante_utc(texto):
    """A operação traz date_created em UTC (termina com Z). Converte pra horário de Brasília."""
    if not texto:
        return None
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(FUSO)


def chamar_operacoes(tipo, data_de, data_ate, scroll=None):
    params = {
        "seller_id": user_id,
        "inventory_id": ",".join(CODIGOS_ML),
        "type": forma_do_tipo[tipo],
        "date_from": data_de.isoformat(),     # AAAA-MM-DD
        "date_to": data_ate.isoformat(),      # AAAA-MM-DD, EXCLUSIVO (a doc: "retorna até o dia -1")
        "limit": LIMITE_POR_PAGINA,
    }
    if scroll:
        params["scroll"] = scroll
    if ultima_chamada_em["t"] is not None:
        espera = PAUSA_ENTRE_CHAMADAS_S - (time.perf_counter() - ultima_chamada_em["t"])
        if espera > 0:
            time.sleep(espera)
    tempo_inicio = time.perf_counter()
    try:
        resposta = chamar_api(
            "GET", ENDPOINT,
            pasta_logs=PASTA_LOGS, conta=CONTA,
            params=params, nome_log=NOME_LOG,
        )
    finally:
        # conta também a chamada que a API recusou (ela gasta cota do mesmo jeito)
        contador["chamadas"] += 1
        contador["segundos"] += time.perf_counter() - tempo_inicio
        ultima_chamada_em["t"] = time.perf_counter()
    return resposta.json()


def fatiar_em_janelas(data_de, data_ate):
    """Divide [data_de, data_ate) em janelas de até DIAS_POR_JANELA_API dias (limite da doc: 60)."""
    janelas = []
    atual = data_de
    while atual < data_ate:
        proxima = min(atual + timedelta(days=DIAS_POR_JANELA_API), data_ate)
        janelas.append((atual, proxima))
        atual = proxima
    return janelas


def info_vazia(tipo, data_de, data_ate):
    return {
        "tipo": tipo, "de": data_de.isoformat(), "ate_exclusive": data_ate.isoformat(),
        "paginas": 0, "linhas_recebidas": 0, "total_segundo_a_api": None,
        "scroll_usado": False, "bateu_limite_de_paginas": False, "erro": None,
        "reinicios_por_scroll_404": 0, "linhas_repetidas_apos_reinicio": 0, "resposta_404_tratada_como_vazio": False,
    }


def erro_404(erro):
    return str(erro).startswith("Erro 404")


def buscar_janela(tipo, data_de, data_ate):
    """Traz todas as operações de 1 tipo numa janela, paginando por scroll. Retorna (lista, info).

    Duas proteções, ambas visíveis na tela e no JSON:
    - 404 numa PÁGINA DE SCROLL (visto em dado real, depois de 2 respostas 429 na mesma página): recomeça a janela
      do zero, sem scroll, e descarta as operações repetidas pelo id (até MAX_REINICIOS_POR_JANELA vezes);
    - 404 na PRIMEIRA página de um tipo que não é a venda: tratado como "nenhuma operação deste tipo na janela"
      (a doc não diz o que a API devolve quando não há resultado); a venda nunca recebe esse tratamento."""
    info = info_vazia(tipo, data_de, data_ate)
    linhas = []
    ids_da_janela = set()
    scroll = None
    while True:
        try:
            pagina = chamar_operacoes(tipo, data_de, data_ate, scroll)
        except ErroAutenticacaoAPI:
            raise
        except ErroAPI as erro:
            primeira_chamada_do_tipo = info["paginas"] == 0 and forma_do_tipo[tipo] == tipo
            if primeira_chamada_do_tipo and "type" in str(erro).lower() and tipo != tipo.lower():
                forma_do_tipo[tipo] = tipo.lower()
                plano_b_tipo_minusculo["tentado"].add(tipo)
                continue
            if erro_404(erro) and scroll and info["reinicios_por_scroll_404"] < MAX_REINICIOS_POR_JANELA:
                info["reinicios_por_scroll_404"] += 1
                scroll = None
                continue
            if erro_404(erro) and scroll is None and info["paginas"] == 0 and tipo != TIPO_VENDA:
                info["resposta_404_tratada_como_vazio"] = True
                break
            raise
        if forma_do_tipo[tipo] != tipo:
            plano_b_tipo_minusculo["funcionou"].add(tipo)
        info["paginas"] += 1
        resultados = pagina.get("results") or []
        paging = pagina.get("paging") or {}
        if info["total_segundo_a_api"] is None:
            info["total_segundo_a_api"] = paging.get("total")
        for linha in resultados:
            id_da_linha = linha.get("id")
            if id_da_linha in ids_da_janela:
                info["linhas_repetidas_apos_reinicio"] += 1
                continue
            ids_da_janela.add(id_da_linha)
            linhas.append(linha)
        info["linhas_recebidas"] = len(linhas)
        scroll = paging.get("scroll")
        total = paging.get("total")
        # fim: a API devolve scroll vazio/nulo, ou não veio linha nenhuma, ou já recebemos o total anunciado
        if not scroll or not resultados or (isinstance(total, int) and info["linhas_recebidas"] >= total):
            break
        info["scroll_usado"] = True
        if info["paginas"] >= MAX_PAGINAS_POR_JANELA:
            info["bateu_limite_de_paginas"] = True
            break
    return linhas, info


def quantidade_da_operacao(operacao):
    """Unidades da operação (sempre positivo). Na venda a quantidade vem NEGATIVA em detail.available_quantity (ex: -10)."""
    detalhe = operacao.get("detail") or {}
    return abs(detalhe.get("available_quantity") or 0)


def envio_da_operacao(operacao):
    for referencia in (operacao.get("external_references") or []):
        if referencia.get("type") == "shipment_id" and referencia.get("value") is not None:
            return str(referencia["value"])
    return None


def chave_do_envio(operacao):
    """Chave que liga cancelamento -> venda: o MESMO envio no MESMO Código ML. None se a operação não traz envio."""
    if not operacao["shipment_id"]:
        return None
    return (operacao["shipment_id"], operacao["inventory_id"])


def dia_curto(dia):
    return f"{dia:%d/%m}"


# ---------- validações de configuração ----------
tipos_invalidos = [tipo for tipo in TIPOS if tipo not in ROTULO_DO_TIPO]
if tipos_invalidos or TIPO_VENDA not in TIPOS or not CODIGOS_ML:
    console.print(f"[bold red]Configuração inválida:[/] TIPOS aceita só {list(ROTULO_DO_TIPO)}, precisa ter {TIPO_VENDA}, e CODIGOS_ML não pode ficar vazio.")
    sys.exit(1)
desconta_cancelamento = TIPO_CANCELA in TIPOS

agora = datetime.now(FUSO)
hoje_00h = agora.replace(hour=0, minute=0, second=0, microsecond=0)
inicio_periodo = hoje_00h - timedelta(days=DIAS_TOTAL)    # 00h do 1º dia completo
fim_periodo = hoje_00h + timedelta(days=1)                # 00h de amanhã (fim do hoje parcial)
# Datas enviadas à API: a doc não diz em que fuso o dia é cortado. Por isso a busca começa 1 dia
# ANTES do período e o que sobra fica de fora dos números por dia (mas serve pra casar cancelamentos).
# O fim é exclusivo (a doc: "retorna até o dia -1"), então amanhã traz tudo até hoje. Se o corte for em
# UTC e você rodar depois das 21h, as últimas horas de hoje podem faltar; hoje é parcial e fica fora das médias.
data_api_inicio = (inicio_periodo - timedelta(days=1)).date()
data_api_fim = fim_periodo.date()
janelas_da_api = fatiar_em_janelas(data_api_inicio, data_api_fim)

# user_id vem do .env da raiz do repo (<CONTA>_USER_ID), mesmo padrão de api_mercado_livre/__init__.py
load_dotenv(dotenv_path=_RAIZ_DO_PROJETO / ".env")
user_id = os.getenv(f"{CONTA}_USER_ID")
if not user_id:
    console.print(f"[bold red]{CONTA}_USER_ID não encontrado no .env da raiz do repo.[/]")
    sys.exit(1)

# ---------- lista das chamadas que serão feitas (antes de fazer) ----------
console.print(
    f"Conta [bold]{CONTA}[/] | SKU [bold]{SKU}[/] | Códigos ML: [bold]{', '.join(CODIGOS_ML)}[/]\n"
    f"Chamadas (todas GET {ENDPOINT}): {len(janelas_da_api)} janela(s) x {len(TIPOS)} tipo(s), "
    f"cada uma com 1 chamada por página de até {LIMITE_POR_PAGINA} operações:"
)
for tipo in TIPOS:
    for data_de, data_ate in janelas_da_api:
        console.print(f"  - type={tipo}  date_from={data_de}  date_to={data_ate} (exclusivo)  inventory_id=<os {len(CODIGOS_ML)} Códigos>")

# ---------- busca ----------
operacoes_brutas = []     # (tipo, operação)
info_janelas = []
try:
    for tipo in TIPOS:
        for data_de, data_ate in janelas_da_api:
            try:
                linhas, info = buscar_janela(tipo, data_de, data_ate)
            except ErroAutenticacaoAPI:
                raise
            except ErroAPI as erro:
                if tipo in TIPOS_DA_REGRA:
                    raise
                # tipo só de observação: se a API recusar, registra o motivo e segue pro próximo tipo
                info = info_vazia(tipo, data_de, data_ate)
                info["erro"] = sem_id(erro)[:300]
                info_janelas.append(info)
                break
            info_janelas.append(info)
            operacoes_brutas.extend((tipo, linha) for linha in linhas)
except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f"[bold red]Erro ao chamar a API:[/] {t(sem_id(erro))}")
    sys.exit(1)

# ---------- limpeza: duplicadas, tipo, Código, data ----------
# Operações FORA do período continuam na lista (servem pra casar cancelamento com venda), só não entram nos números por dia.
vistos = set()
duplicadas = 0
tipo_nao_pedido = 0
fora_dos_codigos = 0
fora_do_periodo = 0
sem_data = 0
tipos_vistos = {}
operacoes = []
for _tipo_pedido, op in operacoes_brutas:
    op_id = op.get("id")
    if op_id in vistos:
        duplicadas += 1
        continue
    vistos.add(op_id)
    tipo_da_op = op.get("type")
    tipos_vistos[tipo_da_op] = tipos_vistos.get(tipo_da_op, 0) + 1
    # rede de segurança: se a API ignorar o filtro de tipo, o que não for dos TIPOS pedidos é descartado
    tipo_normalizado = str(tipo_da_op or "").upper()
    if tipo_normalizado not in TIPOS:
        tipo_nao_pedido += 1
        continue
    codigo = op.get("inventory_id") or op.get("seller_product_id")
    if codigo not in CODIGOS_ML:
        fora_dos_codigos += 1
        continue
    instante = ler_instante_utc(op.get("date_created"))
    if instante is None:
        sem_data += 1
        continue
    no_periodo = inicio_periodo <= instante < fim_periodo
    if not no_periodo:
        fora_do_periodo += 1
    operacoes.append({
        "id": op_id,
        "inventory_id": codigo,
        "tipo": tipo_normalizado,
        "date_created": op.get("date_created"),
        "unidades": quantidade_da_operacao(op),
        "shipment_id": envio_da_operacao(op),
        "_instante": instante,
        "_dia": pd.Timestamp(instante.date()),
        "_no_periodo": no_periodo,
    })
operacoes.sort(key=lambda o: o["_instante"], reverse=True)

# ---------- casamento: cancelamento -> venda original (mesmo envio + mesmo Código ML) ----------
confirmacoes = sorted((o for o in operacoes if o["tipo"] == TIPO_VENDA), key=lambda o: o["_instante"])
cancelamentos = sorted((o for o in operacoes if o["tipo"] == TIPO_CANCELA), key=lambda o: o["_instante"]) if desconta_cancelamento else []
vendas_por_chave = {}
for venda in confirmacoes:
    venda["_restante"] = venda["unidades"]        # unidades da venda ainda não canceladas
    chave = chave_do_envio(venda)
    if chave:
        vendas_por_chave.setdefault(chave, []).append(venda)

pares = []                       # 1 linha por (cancelamento x venda) com unidades descontadas
cancel_sem_envio = []
cancel_sem_venda_na_busca = []
cancel_a_mais = []               # cancelamento com mais unidades do que a venda ainda tinha
cancel_total = 0                 # cancela todas as unidades da venda do par
cancel_parcial = 0               # cancela só parte
cancel_antes_da_venda = 0        # anomalia: o cancelamento é anterior à venda
unidades_casadas_total = 0
for cancel in cancelamentos:
    chave = chave_do_envio(cancel)
    if chave is None:
        cancel_sem_envio.append(cancel)
        continue
    pool = vendas_por_chave.get(chave)
    if not pool:
        cancel_sem_venda_na_busca.append(cancel)
        continue
    unidades_do_par = sum(v["unidades"] for v in pool)
    a_cancelar = cancel["unidades"]
    for venda in pool:
        if a_cancelar <= 0:
            break
        tira = min(venda["_restante"], a_cancelar)
        if tira <= 0:
            continue
        venda["_restante"] -= tira
        a_cancelar -= tira
        unidades_casadas_total += tira
        if cancel["_instante"] < venda["_instante"]:
            cancel_antes_da_venda += 1
        pares.append({
            "cancelamento_id": cancel["id"], "venda_id": venda["id"], "inventory_id": cancel["inventory_id"],
            "shipment_id": cancel["shipment_id"], "unidades": tira,
            "dia_da_venda": venda["_dia"], "dia_do_cancelamento": cancel["_dia"],
            "dias_entre": (cancel["_dia"] - venda["_dia"]).days, "venda_no_periodo": venda["_no_periodo"],
        })
    if a_cancelar > 0:
        cancel_a_mais.append(cancel)
    if cancel["unidades"] >= unidades_do_par:
        cancel_total += 1
    else:
        cancel_parcial += 1
atrasos = [p["dias_entre"] for p in pares]
atrasos_por_faixa = {nome: sum(1 for d in atrasos if minimo <= d <= maximo) for nome, minimo, maximo in FAIXAS_DE_ATRASO}
cancel_unidades_total = sum(c["unidades"] for c in cancelamentos)

# ---------- outros tipos (só observação): casam com alguma venda? em quantos dias? ----------
outros_tipos = {}
for tipo in TIPOS:
    if tipo in TIPOS_DA_REGRA:
        continue
    ops_do_tipo = [o for o in operacoes if o["tipo"] == tipo]
    atrasos_do_tipo = []
    casam = 0
    for o in ops_do_tipo:
        chave = chave_do_envio(o)
        pool = vendas_por_chave.get(chave) if chave else None
        if pool:
            casam += 1
            atrasos_do_tipo.append((o["_dia"] - pool[0]["_dia"]).days)
    erros_do_tipo = [j["erro"] for j in info_janelas if j["tipo"] == tipo and j["erro"]]
    outros_tipos[tipo] = {
        "operacoes": len(ops_do_tipo), "unidades": sum(o["unidades"] for o in ops_do_tipo),
        "com_envio": sum(1 for o in ops_do_tipo if o["shipment_id"]), "casam_com_venda": casam,
        "atraso_mediano_dias": statistics.median(atrasos_do_tipo) if atrasos_do_tipo else None,
        "atraso_maximo_dias": max(atrasos_do_tipo) if atrasos_do_tipo else None,
        "recusado_pela_api": erros_do_tipo[0] if erros_do_tipo else None,
    }

# ---------- números por dia (pandas): bruto, cancelado (no DIA DA VENDA) e líquido ----------
hoje = pd.Timestamp(agora.date())
dias_do_periodo = pd.date_range(end=hoje, periods=DIAS_TOTAL + 1, freq="D")   # 90 dias completos + hoje
bruto = pd.DataFrame(0, index=dias_do_periodo, columns=CODIGOS_ML, dtype="int64")
cancelado = pd.DataFrame(0, index=dias_do_periodo, columns=CODIGOS_ML, dtype="int64")
for venda in confirmacoes:
    if venda["_no_periodo"]:
        bruto.at[venda["_dia"], venda["inventory_id"]] += venda["unidades"]
cancelado_em_por_dia = {}        # dia da venda -> dias em que os cancelamentos aconteceram
for par in pares:
    if par["venda_no_periodo"]:
        cancelado.at[par["dia_da_venda"], par["inventory_id"]] += par["unidades"]
        cancelado_em_por_dia.setdefault(par["dia_da_venda"], set()).add(par["dia_do_cancelamento"])
liquido = bruto - cancelado
for tabela_dia in (bruto, cancelado, liquido):
    tabela_dia["TOTAL"] = tabela_dia[CODIGOS_ML].sum(axis=1)
completos = liquido.iloc[:-1]            # só dias completos (hoje é parcial e fica de fora das médias)
completos_bruto = bruto.iloc[:-1]
completos_cancelado = cancelado.iloc[:-1]
rotulo_unidades = (
    "líquidas: vendas menos cancelamentos casados, descontados no DIA DA VENDA"
    if desconta_cancelamento else "brutas: vendas (confirmações), sem descontar cancelamentos"
)

janelas_resumo = []
for nome, dias in JANELAS_DE_DIAS:
    bloco = completos.iloc[-dias:]
    linha = {"janela": nome, "dias": dias, "total": int(bloco["TOTAL"].sum()),
             "bruto": int(completos_bruto.iloc[-dias:]["TOTAL"].sum()),
             "cancelado": int(completos_cancelado.iloc[-dias:]["TOTAL"].sum()),
             "media_por_dia": round(float(bloco["TOTAL"].sum()) / dias, 2),
             "por_codigo": {c: int(bloco[c].sum()) for c in CODIGOS_ML}}
    janelas_resumo.append(linha)

blocos_30 = []
for rotulo, inicio, fim in [("61 a 90 dias atrás", 0, 30), ("31 a 60 dias atrás", 30, 60), ("últimos 30 dias", 60, 90)]:
    bloco = completos.iloc[inicio:fim]
    blocos_30.append({
        "bloco": rotulo, "de": bloco.index[0].date().isoformat(), "ate": bloco.index[-1].date().isoformat(),
        "total": int(bloco["TOTAL"].sum()), "bruto": int(completos_bruto.iloc[inicio:fim]["TOTAL"].sum()),
        "media_por_dia": round(float(bloco["TOTAL"].sum()) / 30, 2),
        "por_codigo": {c: int(bloco[c].sum()) for c in CODIGOS_ML},
    })

nomes_dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
media_semana = completos["TOTAL"].groupby(completos.index.weekday).mean()
dias_zerados = int((completos["TOTAL"] == 0).sum())
codigos_sem_venda = [c for c in CODIGOS_ML if int(completos[c].sum()) == 0 and int(liquido[c].iloc[-1]) == 0]

janelas_sem_erro = [j for j in info_janelas if not j["erro"]]
recebidas_total = sum(j["linhas_recebidas"] for j in info_janelas)
completo = (
    all(j["total_segundo_a_api"] is None or j["linhas_recebidas"] >= j["total_segundo_a_api"] for j in janelas_sem_erro)
    and not any(j["bateu_limite_de_paginas"] for j in janelas_sem_erro)
)
envios_distintos = len({v["shipment_id"] for v in confirmacoes if v["shipment_id"]})
qtd_maior_que_1 = sum(1 for o in operacoes if o["unidades"] > 1)
qtd_zero = sum(1 for o in operacoes if o["unidades"] == 0)
primeira_op = min((o["_instante"] for o in operacoes), default=None)
ultima_op = max((o["_instante"] for o in operacoes), default=None)
vendas_sem_envio = sum(1 for v in confirmacoes if not v["shipment_id"])

# ---------- apresentação no terminal (rich + pandas) ----------
console.print()
console.print(Panel(
    f"[bold]Produto (SKU)[/]  {SKU}     [bold]Conta[/]  {CONTA}\n"
    f"[bold]Códigos ML[/]  {', '.join(CODIGOS_ML)}\n"
    f"[bold]Gerado em[/]  {agora:%d/%m/%Y %H:%M} (horário de Brasília)\n"
    f"[bold]Período[/]  {inicio_periodo:%d/%m/%Y} a {(hoje_00h - timedelta(days=1)):%d/%m/%Y} "
    f"({DIAS_TOTAL} dias completos, 00h a 24h) + hoje parcial\n"
    f"[bold]Unidades[/]  {rotulo_unidades}\n"
    f"[bold]Regra[/]  só {TIPO_CANCELA} tira a venda do dia original; {', '.join(tp for tp in TIPOS if tp not in TIPOS_DA_REGRA) or '-'} só observação",
    title="Vendas do Full por Código ML", border_style="cyan", expand=False,
))

# ----- 1. como a busca se comportou -----
console.print()
console.print("[bold cyan]1. Como a busca se comportou[/]")
tabela_busca = Table(box=box.SIMPLE_HEAVY, show_edge=False)
for coluna in ["Tipo", "Janela (date_from → date_to excl.)", "Páginas", "Linhas", "Total (API)", "Scroll"]:
    tabela_busca.add_column(coluna, justify="left" if coluna in ("Tipo", "Janela (date_from → date_to excl.)") else "right")
for j in info_janelas:
    tabela_busca.add_row(
        j["tipo"], f"{j['de']} → {j['ate_exclusive']}", str(j["paginas"]), n_br(j["linhas_recebidas"]),
        "-" if j["total_segundo_a_api"] is None else n_br(j["total_segundo_a_api"]),
        "[red]recusado[/]" if j["erro"] else (
            "[yellow]404 = vazio[/]" if j["resposta_404_tratada_como_vazio"] else (
                f"[yellow]reiniciou {j['reinicios_por_scroll_404']}x[/]" if j["reinicios_por_scroll_404"] else ("usado" if j["scroll_usado"] else "não precisou"))),
    )
console.print(tabela_busca)
console.print(
    f"  Chamadas: [bold]{contador['chamadas']}[/] em {contador['segundos']:.1f}s | "
    f"linhas recebidas: {n_br(recebidas_total)} | duplicadas descartadas: {duplicadas} | "
    f"de tipo não pedido (descartadas): {tipo_nao_pedido} | fora dos Códigos: {fora_dos_codigos} | "
    f"fora do período (ficam só pra casar cancelamento): {fora_do_periodo} | sem data: {sem_data}"
)
console.print(
    f"  Tipos que vieram nas linhas: {t(', '.join(f'{k}={v}' for k, v in tipos_vistos.items()) or '-')} | "
    f"operações com mais de 1 unidade: {qtd_maior_que_1} | com 0 unidade (quantidade ausente): {qtd_zero}"
)
if primeira_op and ultima_op:
    console.print(f"  Primeira operação: {primeira_op:%d/%m/%Y %H:%M} | última: {ultima_op:%d/%m/%Y %H:%M} (horário de Brasília)")
if plano_b_tipo_minusculo["funcionou"]:
    console.print(f"  [yellow]A API não aceitou em MAIÚSCULAS e aceitou em minúsculas (plano B): {', '.join(sorted(plano_b_tipo_minusculo['funcionou']))}.[/]")
for j in info_janelas:
    if j["reinicios_por_scroll_404"]:
        console.print(
            f"  [yellow]{j['tipo']} {j['de']}: uma página de scroll deu 404; a janela recomeçou {j['reinicios_por_scroll_404']}x "
            f"({j['linhas_repetidas_apos_reinicio']} operações repetidas descartadas pelo id).[/]")
    if j["resposta_404_tratada_como_vazio"]:
        console.print(f"  [yellow]{j['tipo']} {j['de']}: a API respondeu 404 na 1ª página; tratado como nenhuma operação deste tipo na janela.[/]")
    if j["erro"]:
        console.print(f"  [yellow]A API recusou o tipo {j['tipo']} (só observação, o resto segue): {t(j['erro'])}[/]")
if not completo:
    console.print("  [bold yellow]Atenção: a busca pode estar incompleta (linhas recebidas menores que o total da API, ou bateu a trava de páginas).[/]")
if not operacoes:
    console.print("  [bold yellow]Nenhuma operação dos Códigos no período. O JSON foi gravado só com o diagnóstico.[/]")

# ----- 2. cancelamentos e a regra do dia da venda original -----
console.print()
console.print("[bold cyan]2. Cancelamentos: como casam com a venda (chave = envio + Código ML)[/]")
if not desconta_cancelamento:
    console.print(f"  {TIPO_CANCELA} não está em TIPOS: nada foi descontado.")
else:
    unidades_de_vendas = sum(v["unidades"] for v in confirmacoes)
    tabela_canc = Table(box=box.SIMPLE_HEAVY, show_edge=False)
    tabela_canc.add_column("O que", justify="left")
    tabela_canc.add_column("Quantos", justify="right")
    tabela_canc.add_column("Unidades", justify="right")
    tabela_canc.add_row("Vendas (confirmações) recebidas", n_br(len(confirmacoes)), n_br(unidades_de_vendas))
    tabela_canc.add_row("   vendas sem envio informado", n_br(vendas_sem_envio), "")
    tabela_canc.add_row("Cancelamentos recebidos", n_br(len(cancelamentos)), n_br(cancel_unidades_total))
    tabela_canc.add_row("   casados com uma venda (descontados no dia da venda)", n_br(len(cancelamentos) - len(cancel_sem_envio) - len(cancel_sem_venda_na_busca)), n_br(unidades_casadas_total))
    tabela_canc.add_row("   sem envio informado (não dá pra casar)", n_br(len(cancel_sem_envio)), n_br(sum(c["unidades"] for c in cancel_sem_envio)))
    tabela_canc.add_row("   sem venda correspondente na busca", n_br(len(cancel_sem_venda_na_busca)), n_br(sum(c["unidades"] for c in cancel_sem_venda_na_busca)))
    tabela_canc.add_row("   que cancelam MAIS do que a venda tinha", n_br(len(cancel_a_mais)), "")
    tabela_canc.add_row("   cancelam tudo da venda do par", n_br(cancel_total), "")
    tabela_canc.add_row("   cancelam só parte da venda do par", n_br(cancel_parcial), "")
    tabela_canc.add_row("   anteriores à venda (anomalia)", n_br(cancel_antes_da_venda), "")
    console.print(tabela_canc)
    if atrasos:
        console.print(
            "  Atraso entre a venda e o cancelamento (em dias): "
            + " | ".join(f"{nome}: {n_br(qtd)}" for nome, qtd in atrasos_por_faixa.items())
            + f" | máximo: {max(atrasos)} dia(s) | mediana: {statistics.median(atrasos):g}"
        )
    if cancel_sem_venda_na_busca:
        console.print("  Cancelamentos sem venda na busca (os mais antigos primeiro; perto do início da janela é esperado: a venda é anterior):")
        for c in cancel_sem_venda_na_busca[:8]:
            console.print(f"    - {c['_instante']:%d/%m %H:%M} | {c['inventory_id']} | {c['unidades']} un | envio {c['shipment_id']}")
    if cancel_sem_envio:
        console.print(f"  [yellow]{len(cancel_sem_envio)} cancelamento(s) sem shipment_id: não dá pra descontar de nenhuma venda.[/]")

console.print()
console.print("[bold]Outros tipos (só observação: NÃO descontam a venda)[/]")
if not outros_tipos:
    console.print("  nenhum tipo extra em TIPOS.")
else:
    tabela_outros = Table(box=box.SIMPLE_HEAVY, show_edge=False)
    tabela_outros.add_column("Tipo", justify="left")
    tabela_outros.add_column("Operações", justify="right")
    tabela_outros.add_column("Unidades", justify="right")
    tabela_outros.add_column("Com envio", justify="right")
    tabela_outros.add_column("Casam c/ venda", justify="right")
    tabela_outros.add_column("Atraso mediano/máx (dias)", justify="right")
    for tipo, d in outros_tipos.items():
        if d["recusado_pela_api"]:
            tabela_outros.add_row(f"{tipo} ({ROTULO_DO_TIPO[tipo]})", "[red]recusado pela API[/]", "", "", "", "")
            continue
        atraso_txt = "-" if d["atraso_maximo_dias"] is None else f"{d['atraso_mediano_dias']:g} / {d['atraso_maximo_dias']}"
        tabela_outros.add_row(
            f"{tipo} ({ROTULO_DO_TIPO[tipo]})", n_br(d["operacoes"]), n_br(d["unidades"]),
            n_br(d["com_envio"]), n_br(d["casam_com_venda"]), atraso_txt,
        )
    console.print(tabela_outros)

# ----- 3. janelas de dias completos -----
console.print()
console.print(f"[bold cyan]3. Vendas do Full em dias completos (por dia da venda)[/]  (hoje parcial: [bold]{n_br(int(liquido['TOTAL'].iloc[-1]))}[/] un líquidas, fora das médias)")
tabela_janelas = Table(box=box.SIMPLE_HEAVY, show_edge=False)
tabela_janelas.add_column("Janela", justify="left")
tabela_janelas.add_column("Bruto", justify="right")
tabela_janelas.add_column("Cancelado", justify="right")
tabela_janelas.add_column("Líquido", justify="right")
tabela_janelas.add_column("Média/dia", justify="right")
for c in CODIGOS_ML:
    tabela_janelas.add_column(c, justify="right")
for linha in janelas_resumo:
    tabela_janelas.add_row(
        linha["janela"], n_br(linha["bruto"]), n_br(linha["cancelado"]), f"[bold]{n_br(linha['total'])}[/]", n_br(linha["media_por_dia"], 1),
        *[n_br(linha["por_codigo"][c]) for c in CODIGOS_ML],
    )
console.print(tabela_janelas)
console.print("  Média/dia e colunas dos Códigos são do LÍQUIDO.")
console.print(f"  Dias completos sem nenhuma venda líquida no Full: [bold]{dias_zerados}[/] de {DIAS_TOTAL}")
if codigos_sem_venda:
    console.print(f"  Códigos sem nenhuma unidade no período: [bold]{', '.join(codigos_sem_venda)}[/]")

# ----- 4. aumentou ou diminuiu? (blocos de 30 dias) -----
console.print()
console.print("[bold cyan]4. Aumentou ou diminuiu? (líquido, blocos de 30 dias, do mais antigo ao mais novo)[/]")
tabela_blocos = Table(box=box.SIMPLE_HEAVY, show_edge=False)
tabela_blocos.add_column("Bloco", justify="left")
tabela_blocos.add_column("Período", justify="left")
tabela_blocos.add_column("Bruto", justify="right")
tabela_blocos.add_column("Líquido", justify="right")
tabela_blocos.add_column("Média/dia", justify="right")
tabela_blocos.add_column("vs bloco anterior", justify="right")
for c in CODIGOS_ML:
    tabela_blocos.add_column(c, justify="right")
for i, b in enumerate(blocos_30):
    anterior = blocos_30[i - 1]["total"] if i > 0 else None
    tabela_blocos.add_row(
        b["bloco"], f"{b['de'][8:10]}/{b['de'][5:7]} a {b['ate'][8:10]}/{b['ate'][5:7]}",
        n_br(b["bruto"]), f"[bold]{n_br(b['total'])}[/]", n_br(b["media_por_dia"], 1),
        variacao_texto(b["total"], anterior) if anterior is not None else "[dim]-[/]",
        *[n_br(b["por_codigo"][c]) for c in CODIGOS_ML],
    )
console.print(tabela_blocos)

# ----- 5. últimos 14 dias + dias mais ajustados por cancelamento -----
console.print()
console.print("[bold cyan]5. Últimos 14 dias (hoje é parcial; dias recentes ainda podem cair com novos cancelamentos)[/]")
ultimos = liquido.iloc[-14:]
maximo_14 = int(ultimos["TOTAL"].max()) if len(ultimos) else 0
tabela_dias = Table(box=box.SIMPLE_HEAVY, show_edge=False)
tabela_dias.add_column("Dia da venda", justify="left")
tabela_dias.add_column("Bruto", justify="right")
tabela_dias.add_column("Cancelado", justify="right")
tabela_dias.add_column("Líquido", justify="right")
tabela_dias.add_column("", justify="left")
for data, linha in ultimos.iloc[::-1].iterrows():
    marca = " (hoje, parcial)" if data == hoje else ""
    tabela_dias.add_row(
        f"{data:%d/%m} {nomes_dias[data.weekday()]}{marca}", n_br(int(bruto.at[data, "TOTAL"])),
        n_br(int(cancelado.at[data, "TOTAL"])), f"[bold]{n_br(int(linha['TOTAL']))}[/]",
        f"[green]{barra(int(linha['TOTAL']), maximo_14)}[/]",
    )
console.print(tabela_dias)

if desconta_cancelamento:
    console.print()
    console.print("[bold]Dias da venda mais ajustados pelo cancelamento (conferência da regra)[/]")
    mais_ajustados = cancelado[cancelado["TOTAL"] > 0]["TOTAL"].sort_values(ascending=False).head(8)
    if mais_ajustados.empty:
        console.print("  Nenhum cancelamento foi descontado de nenhum dia do período.")
    else:
        tabela_ajuste = Table(box=box.SIMPLE_HEAVY, show_edge=False)
        tabela_ajuste.add_column("Dia da venda", justify="left")
        tabela_ajuste.add_column("Bruto", justify="right")
        tabela_ajuste.add_column("Cancelado", justify="right")
        tabela_ajuste.add_column("Líquido", justify="right")
        tabela_ajuste.add_column("Cancelado em", justify="left")
        for data, valor in mais_ajustados.items():
            dias_do_cancelamento = ", ".join(dia_curto(d) for d in sorted(cancelado_em_por_dia.get(data, [])))
            tabela_ajuste.add_row(
                f"{data:%d/%m} {nomes_dias[data.weekday()]}", n_br(int(bruto.at[data, "TOTAL"])), n_br(int(valor)),
                f"[bold]{n_br(int(liquido.at[data, 'TOTAL']))}[/]", dias_do_cancelamento,
            )
        console.print(tabela_ajuste)

# ----- 6. calendário semanas x dias da semana (líquido) -----
console.print()
console.print("[bold cyan]6. Calendário de vendas líquidas do Full (unidades por dia da venda; * = hoje, parcial)[/]")
primeiro_dia = liquido.index[0]
segunda_inicial = primeiro_dia - pd.Timedelta(days=primeiro_dia.weekday())
maximo_dia = int(completos["TOTAL"].max()) if len(completos) else 0
tabela_cal = Table(box=box.SIMPLE_HEAVY, show_edge=False)
tabela_cal.add_column("Semana de", justify="left")
for nome in nomes_dias:
    tabela_cal.add_column(nome, justify="right")
tabela_cal.add_column("Semana", justify="right")
segunda = segunda_inicial
while segunda <= hoje:
    celulas = []
    total_semana = 0
    contem_hoje = False
    for k in range(7):
        dia = segunda + pd.Timedelta(days=k)
        if dia < primeiro_dia or dia > hoje:
            celulas.append("")
            continue
        valor = int(liquido.at[dia, "TOTAL"])
        total_semana += valor
        if dia == hoje:
            contem_hoje = True
            celulas.append(f"[bold yellow]{n_br(valor)}*[/]")
        else:
            celulas.append(estilo_celula(valor, maximo_dia, n_br(valor)))
    tabela_cal.add_row(f"{segunda:%d/%m}" + (" [bold yellow]HOJE[/]" if contem_hoje else ""), *celulas, n_br(total_semana))
    segunda += pd.Timedelta(days=7)
console.print(tabela_cal)
console.print(
    "  Média por dia da semana (dias completos, líquido): "
    + " | ".join(f"{nomes_dias[d]} {n_br(float(media_semana.get(d, 0.0)), 1)}" for d in range(7))
)

# ----- rodapé -----
console.print()
console.print(Panel(
    "• Isto é só o FULL: vendas por Coleta, Agência ou Flex (mesmo de anúncio que também está no Full) não aparecem aqui.\n"
    "• A operação não traz o MLB. Dividir um Código entre os MLBs dele precisa dos pedidos.\n"
    "• O dia vem do horário de criação da operação (UTC convertido pra Brasília).\n"
    + (f"• Regra: o cancelamento sai do DIA DA VENDA (casado por envio + Código), nunca do dia em que foi cancelado. "
       f"Só {TIPO_CANCELA} desconta; não entregue e devolução aparecem à parte.\n"
       if desconta_cancelamento else "• Cancelamentos NÃO foram descontados.\n")
    + "• Cancelamento sem venda na busca (venda anterior à janela) não tem dia pra descontar e fica fora dos números por dia.\n"
    + f"• JSON com o resumo, os pares cancelamento x venda e as operações: {CAMINHO_SAIDA.name}",
    title="Leitura", border_style="dim", expand=False,
))

# ---------- JSON de saída ----------
por_dia_json = []
for data in liquido.index:
    por_dia_json.append({
        "data": data.date().isoformat(), "parcial": bool(data == hoje),
        "bruto": {"total": int(bruto.at[data, "TOTAL"]), "por_codigo": {c: int(bruto.at[data, c]) for c in CODIGOS_ML}},
        "cancelado": {"total": int(cancelado.at[data, "TOTAL"]), "por_codigo": {c: int(cancelado.at[data, c]) for c in CODIGOS_ML}},
        "liquido": {"total": int(liquido.at[data, "TOTAL"]), "por_codigo": {c: int(liquido.at[data, c]) for c in CODIGOS_ML}},
    })


def operacao_para_json(o):
    return {"id": o["id"], "inventory_id": o["inventory_id"], "tipo": o["tipo"], "date_created": o["date_created"],
            "unidades": o["unidades"], "shipment_id": o["shipment_id"], "no_periodo": o["_no_periodo"]}


saida = {
    "conta": CONTA, "sku": SKU, "codigos_ml": CODIGOS_ML, "tipos": TIPOS,
    "regra": f"so {TIPO_CANCELA} tira a venda do dia original; casamento por shipment_id + inventory_id; os outros tipos so observacao",
    "gerado_em": agora.isoformat(timespec="seconds"),
    "periodo": {
        "dias_completos": DIAS_TOTAL, "de": inicio_periodo.isoformat(),
        "ate_exclusive": hoje_00h.isoformat(), "busca_ate_exclusive": fim_periodo.isoformat(),
    },
    "info_da_busca": {
        "endpoint": ENDPOINT, "chamadas": contador["chamadas"], "segundos": round(contador["segundos"], 1),
        "janelas": info_janelas, "linhas_recebidas": recebidas_total, "duplicadas": duplicadas,
        "de_tipo_nao_pedido_descartadas": tipo_nao_pedido, "fora_dos_codigos": fora_dos_codigos,
        "fora_do_periodo_usadas_so_pra_casar": fora_do_periodo, "sem_data": sem_data,
        "tipos_vistos_nas_linhas": tipos_vistos, "plano_b_tipo_minusculo_funcionou_em": sorted(plano_b_tipo_minusculo["funcionou"]),
        "busca_completa": bool(completo), "operacoes_com_mais_de_1_unidade": qtd_maior_que_1,
        "operacoes_com_quantidade_zero": qtd_zero, "envios_distintos_nas_confirmacoes": envios_distintos,
        "primeira_operacao": primeira_op.isoformat(timespec="seconds") if primeira_op else None,
        "ultima_operacao": ultima_op.isoformat(timespec="seconds") if ultima_op else None,
    },
    "cancelamentos": {
        "recebidos": len(cancelamentos), "unidades": cancel_unidades_total,
        "casados_unidades": unidades_casadas_total, "pares_cancelamento_x_venda": len(pares),
        "sem_envio": len(cancel_sem_envio), "sem_venda_na_busca": len(cancel_sem_venda_na_busca),
        "cancelam_mais_que_a_venda": len(cancel_a_mais), "cancelam_tudo_da_venda": cancel_total,
        "cancelam_so_parte": cancel_parcial, "anteriores_a_venda": cancel_antes_da_venda,
        "vendas_sem_envio": vendas_sem_envio, "atraso_em_dias_por_faixa": atrasos_por_faixa,
        "atraso_maximo_dias": max(atrasos) if atrasos else None,
        "atraso_mediano_dias": statistics.median(atrasos) if atrasos else None,
        "pares": [
            {"cancelamento_id": p["cancelamento_id"], "venda_id": p["venda_id"], "inventory_id": p["inventory_id"],
             "shipment_id": p["shipment_id"], "unidades": p["unidades"], "dia_da_venda": p["dia_da_venda"].date().isoformat(),
             "dia_do_cancelamento": p["dia_do_cancelamento"].date().isoformat(), "dias_entre": p["dias_entre"],
             "venda_no_periodo": p["venda_no_periodo"]}
            for p in pares
        ],
        "sem_venda_na_busca_lista": [operacao_para_json(c) for c in cancel_sem_venda_na_busca],
        "sem_envio_lista": [operacao_para_json(c) for c in cancel_sem_envio],
    },
    "outros_tipos": outros_tipos,
    "janelas": janelas_resumo,
    "blocos_de_30_dias": blocos_30,
    "media_por_dia_da_semana": {nomes_dias[d]: round(float(media_semana.get(d, 0.0)), 2) for d in range(7)},
    "dias_completos_sem_venda": dias_zerados,
    "por_dia": por_dia_json,
    "operacoes": [operacao_para_json(o) for o in operacoes],
}
CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
console.print(f"\nSalvo em [bold]{CAMINHO_SAIDA.name}[/] ({len(operacoes)} operações, {len(por_dia_json)} dias).")
