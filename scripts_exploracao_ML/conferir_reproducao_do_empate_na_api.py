# scripts_exploracao_ML/conferir_reproducao_do_empate_na_api.py
#
# Função Objetivo: REPRODUZIR com o Mercado Livre, em ~8 chamadas, o problema que o coletor via como "anunciou 202, vieram 201": um empate de fechamento colado na fronteira de duas páginas.
#
# Pré-requisito: rodar antes investigar_empates_de_fechamento_nas_paginas_so_no_banco.py (só banco). Ele grava a lista de dias CANDIDATOS (dias com 2 pedidos fechados no mesmo segundo nas posições
# 49|50, 99|100...) no JSON que este script lê. Este script NÃO calcula nada no banco.
#
# O QUE O SCRIPT FAZ (só leitura: 2 chamadas por repetição, 4 repetições = 8 chamadas de 50 pedidos; nada é gravado):
#   1) Escolhe 1 candidato do JSON: o dia do aviso conhecido (08/07/2026) se ele tem empate na fronteira da janela antiga; senão o 1º candidato da janela antiga; senão o 1º da janela nova.
#      Ou o que você fixar em CANDIDATO.
#   2) Para esse dia e essa fronteira k (posição 50, 100, 150...), repete REPETICOES vezes EXATAMENTE o que o coletor faz em duas páginas seguidas: a chamada da página que termina na posição k−1
#      (offset k−50, limit 50) e a chamada da página que começa na posição k (offset k, limit 50), com a mesma janela que o coletor usava (janela ANTIGA: to = D+1 00:00; NOVA: to = D 23:00).
#   3) Em cada repetição confere: algum pedido aparece nas 2 páginas (repetido)? Faltou algum pedido entre as 2 páginas? Os 2 pedidos da fronteira têm o mesmo date_closed no ML?
#
# COMO LER: se alguma repetição trouxer um pedido repetido (e faltar outro), o mecanismo está REPRODUZIDO: o ML troca a ordem do par empatado entre uma chamada e a outra. Se nas 4 repetições o par
# ficar sempre na mesma ordem, NÃO reproduziu: ou a troca é rara (cada tentativa tem uma chance pequena) ou a causa é outra; aumente REPETICOES (cada +1 custa 2 chamadas) ou use outro candidato.
#
# REGRAS: lê do pedido só o número, o status e as datas (date_created/date_closed); nada de comprador. O seller_id não vai para a tela nem para o JSON. O JSON é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → A chamada é a MESMA do coletor (ApiMercadoLivre.buscar_pedidos, sort=date_desc, limit=50, offset): é a paginação real que se está testando, não uma variação dela.
# * [EXPLICAÇÃO] → O banco ordena o par empatado de um jeito qualquer; o que vale aqui é o que o ML devolve (os date_closed das respostas).

import json
import os
import shutil
import sys
import time
from datetime import date, datetime, timedelta
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

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import requisicoes_enviadas_nesta_thread
from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_detalhes import _caminho_pasta_logs

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                    # "MB" (Magazine) ou "SV" (Samvale)
CANDIDATO = None                # None = o script escolhe no JSON do script de empates. Ou ("antiga", date(2026, 7, 8), 100) = (janela, dia, fronteira)
REPETICOES = 4                  # cada repetição = 2 chamadas (a página antes da fronteira e a depois)
TAMANHO_DA_PAGINA = 50          # o mesmo do coletor
PAUSA_ENTRE_CHAMADAS_S = 0.5    # silêncio entre as chamadas
# ========================================

EMPRESA = {"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA]
definir_empresa_ativa(EMPRESA)
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" usaria a empresa errada.

PASTA = Path(__file__).resolve().parent
CAMINHO_ENTRADA = PASTA / f"exploracao_empates_de_fechamento_nas_paginas_so_no_banco_{CONTA}.json"
CAMINHO_SAIDA = PASTA / f"exploracao_reproducao_do_empate_na_api_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def hora(instante):
    return "—" if instante is None else instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


def tabela(titulo, colunas, linhas, a_direita=()):
    console.print(f"[bold]{t(titulo)}[/]")
    tab = Table(box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
    for i, coluna in enumerate(colunas):
        tab.add_column(coluna, justify="right" if i in a_direita else "left", overflow="fold")
    for linha in linhas:
        tab.add_row(*[t(c) for c in linha])
    console.print(tab)


def mascarar(texto, user_id):
    texto = str(texto)[:300]
    return texto.replace(str(user_id), "***") if user_id else texto


def ler_data(valor):
    if not isinstance(valor, str) or "T" not in valor:
        return None
    try:
        instante = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return instante.astimezone(FUSO) if instante.tzinfo is not None else None


# ======================================================== análise (funções puras) ========================================================

# Função Objetivo: Escolhe o candidato: (janela, dia, fronteira, pedidos_na_janela). Ordem: o fixado em CANDIDATO; o dia do aviso na janela antiga; o 1º da janela antiga; o 1º da nova. None se não houver.
def escolher_candidato(entrada, fixado):
    candidatos = entrada.get("candidatos") or []
    if fixado is not None:
        janela, dia, fronteira = fixado
        for c in candidatos:
            if c["janela"] == janela and c["dia"] == dia.isoformat() and c["fronteira"] == fronteira:
                return c
        return {"janela": janela, "dia": dia.isoformat(), "fronteira": fronteira, "pedidos_na_janela": None, "pedidos": [], "grupo_empatado": None, "fechado_em": None, "variante": "—"}
    aviso = entrada.get("dia_do_aviso")
    if aviso:
        do_aviso = [c for c in candidatos if c["janela"] == "antiga" and c["dia"] == aviso["dia"]]
        if do_aviso:
            return do_aviso[0]
    for janela in ("antiga", "nova"):
        daquela = [c for c in candidatos if c["janela"] == janela]
        if daquela:
            return daquela[0]
    return None


# Função Objetivo: Compara a página ANTES da fronteira (A) com a página DEPOIS (B), sem olhar o banco: pedidos repetidos entre as duas, quantos pedidos distintos vieram (o esperado é len(A) + len(B)),
# os 2 pedidos da fronteira (último de A, primeiro de B) e se eles têm o mesmo date_closed no ML.
def comparar_paginas(pagina_a, pagina_b):
    ids_a, ids_b = [p.get("id") for p in pagina_a], [p.get("id") for p in pagina_b]
    repetidos = sorted(set(ids_a) & set(ids_b))
    distintos = len(set(ids_a) | set(ids_b))
    esperado = len(ids_a) + len(ids_b)
    ultimo_a = pagina_a[-1] if pagina_a else None
    primeiro_b = pagina_b[0] if pagina_b else None
    fechado_a = ler_data(ultimo_a.get("date_closed")) if ultimo_a else None
    fechado_b = ler_data(primeiro_b.get("date_closed")) if primeiro_b else None
    return {"repetidos": repetidos, "distintos": distintos, "esperado": esperado, "faltaram": esperado - distintos,
            "ultimo_de_a": None if ultimo_a is None else ultimo_a.get("id"), "primeiro_de_b": None if primeiro_b is None else primeiro_b.get("id"),
            "fechado_do_ultimo_de_a": fechado_a, "fechado_do_primeiro_de_b": fechado_b, "empate_no_ml": fechado_a is not None and fechado_a == fechado_b,
            "reproduziu": bool(repetidos)}


def montar_leitura(candidato, total_ml, repeticoes):
    leitura = []
    reproduziu = [r for r in repeticoes if r["reproduziu"]]
    empates = [r for r in repeticoes if r["empate_no_ml"]]
    trocas = {(r["ultimo_de_a"], r["primeiro_de_b"]) for r in repeticoes}
    if candidato["pedidos_na_janela"] is not None and total_ml is not None:
        igual = "bate com" if total_ml == candidato["pedidos_na_janela"] else "NÃO bate com"
        leitura.append(f"O ML anunciou {n(total_ml)} pedidos na janela; o banco tem {n(candidato['pedidos_na_janela'])}: o total {igual} o banco.")
    if reproduziu:
        leitura.append(f"REPRODUZIU em {len(reproduziu)} de {len(repeticoes)} repetições: entre as páginas {candidato['fronteira'] - TAMANHO_DA_PAGINA}-{candidato['fronteira'] - 1} e {candidato['fronteira']}-"
                       f"{candidato['fronteira'] + TAMANHO_DA_PAGINA - 1} o MESMO pedido veio nas duas e faltou outro. É o mecanismo do aviso 'anunciou N, vieram N−1': o ML trocou a ordem do par empatado "
                       f"entre uma chamada e a outra. A releitura com página de outro tamanho (que o coletor passou a fazer) completa a janela.")
    elif not empates:
        leitura.append("NÃO reproduziu, e na resposta do ML os 2 pedidos da fronteira NÃO têm o mesmo date_closed: neste momento não há empate aí (o fechamento do banco pode ter mudado). Tente outro candidato.")
    elif len(trocas) > 1:
        leitura.append("O par da fronteira TROCOU de ordem entre repetições (o ML devolve o empate em ordens diferentes), mas nenhuma repetição pegou a troca justo entre as 2 páginas. A ordem instável está provada; "
                       "falta só acertar a troca entre as 2 chamadas. Repita com mais REPETICOES.")
    else:
        leitura.append(f"NÃO reproduziu: em {len(repeticoes)} repetições o par empatado ficou SEMPRE na mesma ordem. Ou a troca de ordem é rara, ou a causa do aviso é outra. Aumente REPETICOES (cada +1 = 2 chamadas) "
                       f"ou teste outro candidato antes de descartar o empate.")
    return leitura


# ======================================================== as chamadas ========================================================

def chamar_pagina(api, inicio, fim, offset, limite):
    antes = requisicoes_enviadas_nesta_thread()
    pacote = api.buscar_pedidos(inicio, fim, offset=offset, limite=limite)
    resposta = {"requisicoes_http": requisicoes_enviadas_nesta_thread() - antes, "http": pacote.http, "erro": None if pacote.erro is None else mascarar(pacote.erro, getattr(api, "_user_id", None)), "total": None, "pagina": []}
    if pacote.erro is None and pacote.http == 200 and isinstance(pacote.dados, dict):
        resposta["total"] = (pacote.dados.get("paging") or {}).get("total")
        resposta["pagina"] = [{"id": p.get("id"), "status": p.get("status"), "date_created": p.get("date_created"), "date_closed": p.get("date_closed")} for p in (pacote.dados.get("results") or []) if isinstance(p, dict)]
    return resposta


def main():
    console.print(f"\n[bold]Reprodução do empate de fechamento na fronteira de página[/] · conta {CONTA} · {2 * REPETICOES} chamadas de {TAMANHO_DA_PAGINA} pedidos (GET) · nada é gravado\n")
    if not CAMINHO_ENTRADA.exists():
        console.print(f"[bold red]Não achei {CAMINHO_ENTRADA.name}. Rode antes: python scripts_exploracao_ML/investigar_empates_de_fechamento_nas_paginas_so_no_banco.py[/]")
        return
    entrada = json.loads(CAMINHO_ENTRADA.read_text(encoding="utf-8"))
    candidato = escolher_candidato(entrada, CANDIDATO)
    if candidato is None:
        console.print("[bold]O script de empates não achou nenhum dia com empate numa fronteira de página (nas 2 janelas).[/] A hipótese de empate não tem como ter causado aviso no que está no banco. Nada a reproduzir.")
        return
    dia = date.fromisoformat(candidato["dia"])
    inicio = datetime(dia.year, dia.month, dia.day, 0, tzinfo=FUSO)
    fim = datetime(dia.year, dia.month, dia.day, 0, tzinfo=FUSO) + (timedelta(days=1) if candidato["janela"] == "antiga" else timedelta(hours=23))
    k = candidato["fronteira"]
    tabela("O candidato", ["O quê", "Valor"], [
        ("Janela", "ANTIGA (o coletor antes da correção: to = D+1 00:00, lê até 00:59)" if candidato["janela"] == "antiga" else "NOVA (to = D 23:00, só o dia)"),
        ("Dia", f"{dia:%d/%m/%Y}"), ("Fronteira testada", f"posições {k - 1}|{k} (páginas de {TAMANHO_DA_PAGINA})"),
        ("Janela pedida (from → to)", f"{hora(inicio)} → {hora(fim)}"), ("Pedidos na janela, segundo o banco", "—" if candidato["pedidos_na_janela"] is None else n(candidato["pedidos_na_janela"])),
        ("Fechamento do par, segundo o banco", "—" if not candidato["fechado_em"] else hora(datetime.fromisoformat(candidato["fechado_em"])))])

    api = ApiMercadoLivre(pasta_logs=_caminho_pasta_logs(EMPRESA), empresa=EMPRESA)
    repeticoes, total_ml, chamadas = [], None, 0
    try:
        for i in range(REPETICOES):
            a = chamar_pagina(api, inicio, fim, k - TAMANHO_DA_PAGINA, TAMANHO_DA_PAGINA)
            time.sleep(PAUSA_ENTRE_CHAMADAS_S)
            b = chamar_pagina(api, inicio, fim, k, TAMANHO_DA_PAGINA)
            if i < REPETICOES - 1:
                time.sleep(PAUSA_ENTRE_CHAMADAS_S)
            chamadas += a["requisicoes_http"] + b["requisicoes_http"]
            total_ml = total_ml if total_ml is not None else (a["total"] if a["total"] is not None else b["total"])
            if a["erro"] or b["erro"] or not a["pagina"] or not b["pagina"]:
                repeticoes.append({"repeticao": i + 1, "erro": a["erro"] or b["erro"] or f"página vazia (HTTP {a['http']}/{b['http']})", "reproduziu": False, "empate_no_ml": False,
                                   "ultimo_de_a": None, "primeiro_de_b": None})
                continue
            comparacao = comparar_paginas(a["pagina"], b["pagina"])
            repeticoes.append({"repeticao": i + 1, "erro": None, **comparacao})
    except ErroAutenticacaoAPI:
        console.print("[bold red]O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi concluído.[/]")
        return

    console.rule("[bold]As repetições")
    linhas = []
    for r in repeticoes:
        if r["erro"]:
            linhas.append((str(r["repeticao"]), "—", "—", "—", "—", "—", r["erro"]))
            continue
        linhas.append((str(r["repeticao"]), str(r["ultimo_de_a"]), str(r["primeiro_de_b"]), hora(r["fechado_do_ultimo_de_a"]) + (" = " if r["empate_no_ml"] else " ≠ ") + hora(r["fechado_do_primeiro_de_b"]),
                       n(len(r["repetidos"])), n(r["faltaram"]), "SIM" if r["reproduziu"] else "não"))
    tabela("Última linha da página antes da fronteira × primeira linha da página depois", ["Rep.", "Último pedido da página A", "Primeiro pedido da página B", "date_closed (A × B)", "Repetidos", "Faltaram", "Reproduziu?"],
           linhas, a_direita=(0, 4, 5))
    console.print(f"Requisições HTTP gastas: {n(chamadas)}.")

    console.rule("[bold]Leitura")
    leitura = montar_leitura(candidato, total_ml, repeticoes)
    for linha in leitura:
        console.print(f"• {t(linha)}")

    saida = {"conta": CONTA, "candidato": candidato, "total_segundo_o_ml": total_ml, "requisicoes_http": chamadas,
             "repeticoes": [{k_: (v.isoformat() if isinstance(v, datetime) else v) for k_, v in r.items()} for r in repeticoes], "leitura": leitura}
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem dado de comprador e sem seller_id.")


if __name__ == "__main__":
    main()
