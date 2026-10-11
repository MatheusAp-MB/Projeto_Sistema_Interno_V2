# scripts_exploracao_ML/sondar_limite_operacoes_full.py
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
# ESCOPO: sondagem de 10/10/2026 (25 chamadas: 15 OK, 8 x 429, 2 x 404); resultado em sondagem_limite_operacoes_full_MB.json.
# O parágrafo 'O que já se sabe' abaixo é anterior à sondagem e foi superado por este aviso.
# ============================================================================================================================
#
# Objetivo: MEDIR como o endpoint GET /stock/fulfillment/operations/search se comporta quanto ao limite de chamadas (429) e ao
# scroll (404 "Operation not found"), com dado real, ANTES de ajustar o coletor (coletar_operacoes_full).
#
# O que já se sabe (logs de 10/10/2026): as 429 aparecem em chamadas SEM scroll e, em geral, passam depois de esperar; já uma
# página de SCROLL que toma 429 nunca passou depois (3 casos: 2 viraram 404 e 1 esgotou). Os 429 do coletor aconteceram só na
# janela mais antiga (a 360 dias); nas janelas recentes (Passo 2) quase não houve. Horário, janela antiga e rajada de chamadas
# estão misturados nesses dados: esta sonda separa as causas.
#
# O que a sonda faz: revezando 4 condições em RODADAS rodadas, no mesmo intervalo de tempo (assim o horário afeta todas por igual):
#   leve_recente   1 Código, 1 dia recente,            limit=1
#   leve_antiga    1 Código, 1 dia a ~358 dias,        limit=1
#   pesada_recente os 3 Códigos, 46 dias recentes,     limit=1000   (a chamada que o coletor faz, em janela recente)
#   pesada_antiga  os 3 Códigos, 15/10/2025 a 30/11/2025, limit=1000 (a chamada que o coletor faz, na janela mais antiga)
# Nas pesadas, se a resposta traz scroll, 1 s depois pede a página seguinte; se ela der 429, repete o MESMO scroll até
# MAX_REPETICOES_DO_SCROLL vezes (a cada PAUSA_REPETICAO_SCROLL_S s), só para ver se algum dia passa.
#
# REGRAS: só leitura (GET), UMA tentativa por chamada (sem retry: o objetivo é ver cada 429 como ele é). O seller_id e o token
# nunca vão para a tela nem para o JSON; do corpo das respostas só vai a mensagem curta de erro; nenhum dado de comprador
# (a operação nem traz). Não toca no banco.
#
# * [EXPLICAÇÃO] → Por que não usa chamar_api(): ele tenta de novo sozinho quando recebe 429 e não entrega os cabeçalhos da
#                  resposta; aqui eu preciso ver o 429 cru (status, tempo e cabeçalhos). Por isso este script usa a MESMA sessão
#                  HTTP e o MESMO gerenciador de token do cliente, mas faz 1 requisição por chamada. Só vale para exploração.

import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
CONTA = "MB"                                         # "MB" (Magazine) ou "SV" (Samvale)
CODIGOS_ML = ["QAVX18725", "RWBD51502", "OPXW24140"]   # os 3 Códigos do SKU F7908050719121.001 (mesmos do Passo 2)
CODIGO_LEVE = "QAVX18725"                            # o Código das chamadas leves
RODADAS = 4                                          # quantas vezes as 4 condições são repetidas
PAUSA_ENTRE_CHAMADAS_S = 15                          # silêncio antes de cada chamada de 1ª página (contado do fim da anterior)
PAUSA_DO_SCROLL_S = 1                                # entre a 1ª página e o scroll dela (o mesmo ritmo do coletor)
MAX_REPETICOES_DO_SCROLL = 2                         # repetições do MESMO scroll depois de um 429
PAUSA_REPETICAO_SCROLL_S = 5
# ========================================

ENDPOINT = "/stock/fulfillment/operations/search"
TIPO = "SALE_CONFIRMATION"
DIAS_DA_JANELA_PESADA = 46                           # o mesmo do coletor
DIAS_ATRAS_DA_JANELA_ANTIGA = 360                    # o mesmo do coletor (hoje - 360 dias)
PADROES_DE_CABECALHO_DE_LIMITE = ("rate", "limit", "retry", "remaining", "reset", "quota", "throttl", "wait")
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"sondagem_limite_operacoes_full_{CONTA}.json"

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(80, 24)).columns - 1, 20))
t = escape
user_id = None
chamadas = []                                        # 1 dict por chamada feita (vai para o JSON)
ultimo_fim = {"t": None}


def sem_id(texto):
    """Troca o seller_id por *** antes de mostrar qualquer texto que veio da API."""
    texto = str(texto)
    return texto.replace(str(user_id), "***") if user_id else texto


def hoje_utc():
    return datetime.now(timezone.utc).date()


def montar_condicoes(hoje):
    """As 4 condições, com as datas calculadas a partir de hoje (dia UTC, como o coletor). date_to é EXCLUSIVO."""
    antiga_de = hoje - timedelta(days=DIAS_ATRAS_DA_JANELA_ANTIGA)
    return [
        {"nome": "leve_recente", "pesada": False, "codigos": [CODIGO_LEVE], "de": hoje - timedelta(days=3), "ate": hoje - timedelta(days=2), "limit": 1},
        {"nome": "leve_antiga", "pesada": False, "codigos": [CODIGO_LEVE], "de": hoje - timedelta(days=358), "ate": hoje - timedelta(days=357), "limit": 1},
        {"nome": "pesada_recente", "pesada": True, "codigos": CODIGOS_ML, "de": hoje - timedelta(days=DIAS_DA_JANELA_PESADA - 1), "ate": hoje + timedelta(days=1), "limit": 1000},
        {"nome": "pesada_antiga", "pesada": True, "codigos": CODIGOS_ML, "de": antiga_de, "ate": antiga_de + timedelta(days=DIAS_DA_JANELA_PESADA), "limit": 1000},
    ]


def esperar_ate(segundos_desde_a_ultima_chamada):
    """Garante pelo menos N segundos de silêncio desde o fim da chamada anterior."""
    if ultimo_fim["t"] is None:
        return
    falta = segundos_desde_a_ultima_chamada - (time.perf_counter() - ultimo_fim["t"])
    if falta > 0:
        time.sleep(falta)


def cabecalhos_de_interesse(resposta):
    """Só os cabeçalhos que falam de limite/espera (e a data do servidor). Nunca o resto dos valores."""
    achados = {}
    for nome, valor in resposta.headers.items():
        minusculo = nome.lower()
        if minusculo in ("date", "age") or any(p in minusculo for p in PADROES_DE_CABECALHO_DE_LIMITE):
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


def chamar_uma_vez(condicao, tipo_de_chamada, rodada, scroll=None):
    """1 GET, 1 tentativa. Registra tudo em `chamadas` e devolve o registro (com o `scroll` seguinte em registro['_scroll'])."""
    params = {
        "seller_id": user_id,
        "inventory_id": ",".join(condicao["codigos"]),
        "type": TIPO,
        "date_from": condicao["de"].isoformat(),
        "date_to": condicao["ate"].isoformat(),
        "limit": condicao["limit"],
    }
    if scroll:
        params["scroll"] = scroll
    desde_a_anterior = None if ultimo_fim["t"] is None else round(time.perf_counter() - ultimo_fim["t"], 1)
    registro = {
        "n": len(chamadas) + 1, "rodada": rodada, "condicao": condicao["nome"], "chamada": tipo_de_chamada,
        "hora_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "segundos_desde_o_fim_da_anterior": desde_a_anterior,
        "http": None, "ms": None, "total": None, "linhas": None, "tem_scroll": None, "erro": None,
        "cabecalhos_de_limite": {}, "nomes_dos_cabecalhos": [],
    }
    inicio = time.perf_counter()
    try:
        resposta = _sessao.get(
            f"{BASE_URL}{ENDPOINT}", params=params,
            headers={"Authorization": f"Bearer {obter_token_valido(CONTA)}"},
            timeout=(TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS),
        )
    except requests.exceptions.RequestException as erro:
        registro["erro"] = f"{type(erro).__name__} (sem resposta)"
        resposta = None
    registro["ms"] = round((time.perf_counter() - inicio) * 1000)
    ultimo_fim["t"] = time.perf_counter()
    registro["_scroll"] = None
    if resposta is not None:
        registro["http"] = resposta.status_code
        registro["cabecalhos_de_limite"] = cabecalhos_de_interesse(resposta)
        registro["nomes_dos_cabecalhos"] = sorted(resposta.headers.keys())
        if resposta.status_code == 200:
            try:
                dados = resposta.json()
                paging = dados.get("paging") or {}
                registro["total"] = paging.get("total")
                registro["linhas"] = len(dados.get("results") or [])
                registro["_scroll"] = paging.get("scroll") or None
                registro["tem_scroll"] = bool(registro["_scroll"])
            except ValueError:
                registro["erro"] = "200 sem JSON válido"
        else:
            registro["erro"] = erro_curto(resposta)
    chamadas.append(registro)
    mostrar_linha(registro)
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
    """1 linha por chamada, na hora em que ela acontece."""
    http = registro["http"]
    cor = cor_do_status(http)
    detalhe = ""
    if http == 200:
        detalhe = f"total={registro['total']} linhas={registro['linhas']} scroll={'sim' if registro['tem_scroll'] else 'não'}"
    elif registro["erro"]:
        detalhe = t(registro["erro"][:110])
    hora = registro["hora_local"][11:19]
    console.print(
        f"  #{registro['n']:<2} {hora}  {registro['condicao']:<15} {registro['chamada']:<19} "
        f"[{cor}]HTTP {http if http is not None else '---'}[/]  {registro['ms']} ms  {detalhe}"
    )


def contar(lista_de_registros):
    """Conta os status de uma lista de chamadas."""
    contagem = {"n": len(lista_de_registros), "200": 0, "429": 0, "404": 0, "outros": 0}
    for registro in lista_de_registros:
        http = registro["http"]
        if http in (200, 429, 404):
            contagem[str(http)] += 1
        else:
            contagem["outros"] += 1
    return contagem


def resumir():
    """Tabelas de contagem por condição + o que os cabeçalhos das respostas disseram. Só fatos medidos, sem conclusão."""
    nomes = []
    for registro in chamadas:
        if registro["condicao"] not in nomes:
            nomes.append(registro["condicao"])

    tabela = Table(box=box.SIMPLE_HEAVY, title="Contagem por condição e tipo de chamada (HTTP)", title_justify="left")
    tabela.add_column("condição")
    tabela.add_column("chamada")
    tabela.add_column("n", justify="right")
    tabela.add_column("200", justify="right")
    tabela.add_column("429", justify="right")
    tabela.add_column("404", justify="right")
    tabela.add_column("outros", justify="right")
    tabela.add_column("status em ordem")
    grupos = [("primeira_pagina", "1ª página"), ("scroll", "scroll (1ª tentativa)"), ("scroll_repeticao", "scroll repetido após 429")]
    resumo = {}
    for nome in nomes:
        deste = [r for r in chamadas if r["condicao"] == nome]
        resumo[nome] = {}
        for chave, rotulo in grupos:
            do_grupo = [r for r in deste if (r["chamada"] == chave if chave != "scroll_repeticao" else r["chamada"].startswith("scroll_repeticao"))]
            if not do_grupo:
                continue
            c = contar(do_grupo)
            sequencia = " ".join(str(r["http"]) if r["http"] is not None else "ERR" for r in do_grupo)
            resumo[nome][chave] = {**c, "sequencia": sequencia}
            tabela.add_row(nome, rotulo, str(c["n"]), str(c["200"]), str(c["429"]), str(c["404"]), str(c["outros"]), sequencia)
    console.print()
    console.print(tabela)

    # cabeçalhos: o que veio em cada status
    nomes_por_status, valores_de_limite = {}, {}
    for registro in chamadas:
        status = str(registro["http"])
        nomes_por_status.setdefault(status, set()).update(registro["nomes_dos_cabecalhos"])
        for nome_cab, valor in registro["cabecalhos_de_limite"].items():
            if nome_cab.lower() in ("date", "age"):
                continue
            valores_de_limite.setdefault(status, {}).setdefault(nome_cab, set()).add(valor)
    console.print("[bold]Cabeçalhos das respostas[/]")
    for status in sorted(nomes_por_status):
        console.print(f"  HTTP {status}: {t(', '.join(sorted(nomes_por_status[status])) or '(nenhum)')}")
    if valores_de_limite:
        console.print("[bold]Cabeçalhos que falam de limite/espera (nome: valores distintos)[/]")
        for status in sorted(valores_de_limite):
            for nome_cab, valores in sorted(valores_de_limite[status].items()):
                console.print(f"  HTTP {status}  {t(nome_cab)}: {t(', '.join(sorted(valores)))}")
    else:
        console.print("[bold]Cabeçalhos que falam de limite/espera:[/] nenhum veio em nenhuma resposta")

    # segundos de silêncio antes de cada 1ª página, por status (a pausa é a mesma por desenho; aqui fica o que realmente aconteceu)
    console.print()
    return resumo, {s: sorted(n) for s, n in nomes_por_status.items()}, {s: {k: sorted(v) for k, v in d.items()} for s, d in valores_de_limite.items()}


def salvar_json(condicoes, interrompido, resumo, nomes_por_status, valores_de_limite):
    limpas = [{k: v for k, v in registro.items() if not k.startswith("_")} for registro in chamadas]
    saida = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "conta": CONTA, "endpoint": ENDPOINT, "tipo": TIPO, "interrompido_pelo_usuario": interrompido,
        "configuracao": {
            "rodadas": RODADAS, "pausa_entre_chamadas_s": PAUSA_ENTRE_CHAMADAS_S, "pausa_do_scroll_s": PAUSA_DO_SCROLL_S,
            "max_repeticoes_do_scroll": MAX_REPETICOES_DO_SCROLL, "pausa_repeticao_scroll_s": PAUSA_REPETICAO_SCROLL_S,
        },
        "condicoes": [
            {"nome": c["nome"], "quantidade_de_codigos": len(c["codigos"]), "de": c["de"].isoformat(), "ate_exclusive": c["ate"].isoformat(), "limit": c["limit"]}
            for c in condicoes
        ],
        "resumo": resumo, "nomes_dos_cabecalhos_por_status": nomes_por_status, "cabecalhos_de_limite_por_status": valores_de_limite,
        "chamadas": limpas,
    }
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    global user_id
    load_dotenv(dotenv_path=_RAIZ_DO_PROJETO / ".env")
    user_id = os.getenv(f"{CONTA}_USER_ID")
    if not user_id:
        console.print(f"[bold red]{CONTA}_USER_ID não encontrado no .env da raiz do repo.[/]")
        sys.exit(1)

    hoje = hoje_utc()
    condicoes = montar_condicoes(hoje)

    # ---------- lista das chamadas (antes de fazer) ----------
    console.print(
        f"Conta [bold]{CONTA}[/] | Códigos: leve = 1, pesada = {len(CODIGOS_ML)} | todas GET {ENDPOINT}, type={TIPO}, UMA tentativa por chamada.\n"
        f"{RODADAS} rodada(s) x {len(condicoes)} condições = {RODADAS * len(condicoes)} chamadas de 1ª página, com {PAUSA_ENTRE_CHAMADAS_S}s de silêncio antes de cada uma;\n"
        f"nas pesadas, +1 chamada de scroll (a {PAUSA_DO_SCROLL_S}s) se a resposta trouxer scroll, e até {MAX_REPETICOES_DO_SCROLL} repetições dela se der 429 "
        f"(a cada {PAUSA_REPETICAO_SCROLL_S}s). Dias em UTC (hoje = {hoje:%d/%m/%Y}), date_to exclusivo:"
    )
    for c in condicoes:
        console.print(f"  - {c['nome']:<15} date_from={c['de']}  date_to={c['ate']}  limit={c['limit']}  inventory_id=<{len(c['codigos'])} Código(s)>")
    console.print()

    interrompido = False
    try:
        for rodada in range(1, RODADAS + 1):
            console.print(f"[bold]Rodada {rodada}/{RODADAS}[/]")
            for condicao in condicoes:
                esperar_ate(PAUSA_ENTRE_CHAMADAS_S)
                primeira = chamar_uma_vez(condicao, "primeira_pagina", rodada)
                if primeira["http"] == 401:
                    console.print("[bold red]401: o Mercado Livre recusou o token. Sonda interrompida.[/]")
                    raise SystemExit(1)
                tem_proxima = primeira["http"] == 200 and primeira["_scroll"] and (primeira["total"] or 0) > (primeira["linhas"] or 0)
                if condicao["pesada"] and tem_proxima:
                    esperar_ate(PAUSA_DO_SCROLL_S)
                    seguinte = chamar_uma_vez(condicao, "scroll", rodada, scroll=primeira["_scroll"])
                    repeticao = 0
                    while seguinte["http"] == 429 and repeticao < MAX_REPETICOES_DO_SCROLL:
                        repeticao += 1
                        esperar_ate(PAUSA_REPETICAO_SCROLL_S)
                        seguinte = chamar_uma_vez(condicao, f"scroll_repeticao_{repeticao}", rodada, scroll=primeira["_scroll"])
    except KeyboardInterrupt:
        interrompido = True
        console.print("\n[yellow]Interrompido por você. O que já foi medido será resumido e salvo.[/]")
    finally:
        if chamadas:
            resumo, nomes_por_status, valores_de_limite = resumir()
            salvar_json(condicoes, interrompido, resumo, nomes_por_status, valores_de_limite)
            console.print(f"JSON salvo em: {CAMINHO_SAIDA.name} ({len(chamadas)} chamadas). Sem seller_id, sem token, sem dado de comprador.")


if __name__ == "__main__":
    main()
