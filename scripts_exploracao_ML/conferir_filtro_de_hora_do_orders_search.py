# scripts_exploracao_ML/conferir_filtro_de_hora_do_orders_search.py
#
# Função Objetivo: CONFIRMAR, com 2 chamadas de 1 pedido cada ao GET /orders/search, como o filtro "order.date_created.to" trata a HORA, e se a correção
# candidata lê o dia inteiro sem repetir a 1ª hora do dia seguinte.
#
# Contexto (12/10/2026): a coleta da conta toda e a coleta por produto contam ~1,3% de pedidos a mais do que existem no banco (84.510 lidos contra 83.438 no ano;
# 1.226 contra 1.207 na semana). A diferença bate com o número de pedidos criados entre 00:00 e 00:59 (1.074). O cabeçalho de api_mercado_livre/pedidos_ml.py já
# dizia, desde 10/10/2026, que "o filtro de data ignora minutos, segundos e milissegundos". Se isso vale também para o "to", a busca do dia D com to = D+1 00:00
# lê até D+1 00:59:59, e todo pedido da hora 0 de D+1 é lido 2 vezes (no dia D e no dia D+1). O banco guarda 1 só (upsert por pedido+posição); o que sobe é a
# contagem de "lidos" (e uma fração mínima de chamadas).
#
# RESULTADO (12/10/2026, dia 24/11/2025, conta MB): CONFIRMADO. Chamada 1 (to = D+1 00:00): total 477 = 465 do dia + 12 da hora 0 do dia seguinte. Chamada 2 (to = D 23:00): total 465 =
# o dia exato. O coletor passou a mandar `fim − 1 hora` (coletar_vendas_ml._buscar_pagina). O aviso sobre "o pedido mais novo não é da hora 23" era erro deste teste: a lista é ordenada por
# date_closed, não por criação (ver conferir_ordem_do_sort_do_orders_search.py). Não precisa rodar de novo.
#
# O QUE O SCRIPT FAZ (só leitura: SELECT no banco + 2 GET de 1 pedido cada):
#   0) Escolhe no banco um dia D dos últimos dias com várias vendas na hora 0 de D+1 e na hora 23 de D (ou usa DIA_DO_TESTE).
#   1) CHAMADA 1: a busca EXATAMENTE como o coletor faz hoje: from = D 00:00, to = D+1 00:00, sort date_desc, limit 1. Lê paging.total e a data do 1º pedido da lista.
#        - Se a hipótese vale: total ≈ pedidos de D no banco + pedidos da hora 0 de D+1.
#        - Se não vale: total ≈ pedidos de D no banco.
#   2) CHAMADA 2: a correção candidata: from = D 00:00, to = D 23:00 (fim − 1 hora), mesmo sort e limit.
#        - Se a correção serve: total ≈ pedidos de D no banco (e NÃO pedidos de D menos os da hora 23).
#   3) Diz o que COMBINA e o que NÃO combina. Não muda nada no coletor.
#
# REGRAS: nenhum dado de comprador é lido além do paging.total, da data e do status do 1º pedido da lista; nada é gravado no banco. O seller_id não vai para a tela nem
# para o JSON. O JSON de saída é sobrescrito a cada execução. Usa o MESMO caminho do coletor (ApiMercadoLivre.buscar_pedidos), então as chamadas entram no log normal.
#
# * [EXPLICAÇÃO] → limit=1 de propósito: queremos só o total (e a data do 1º da lista), não a lista (1 chamada barata, não 1 página de 50).
# * [EXPLICAÇÃO] → Aprendido em 12/10/2026: com sort=date_desc o 1º da lista NÃO é o pedido mais novo por data de criação (24/11/2025: veio o de 12:44:32 nas duas chamadas, havendo pedido
#                  até 23:57 no banco). Por isso o veredito usa só o TOTAL da janela, nunca a posição do 1º pedido. A linha "ORDEM" da Leitura avisa quando isso se repete.
# * [EXPLICAÇÃO] → "Pedidos de D no banco" = pedidos com dia_venda D (todos os status: a busca do vendedor também traz os cancelados). O banco pode ter 1 ou 2 pedidos
#                  a menos que o ML (paginação instável já vista em 08/07), por isso a comparação tem tolerância (TOLERANCIA).

import json
import os
import shutil
import sys
import time
from collections import defaultdict
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
from mercado_livre.models import VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                    # "MB" (Magazine) ou "SV" (Samvale)
DIA_DO_TESTE = None             # None = o script escolhe no banco. Ou date(2026, 9, 20): o dia D (o banco precisa ter D e D+1 completos)
DIAS_PARA_TRAS_MAX = 330        # o dia escolhido fica entre (hoje − 330 dias) e (hoje − 3 dias): o banco tem esses dias completos (coleta do ano) e o ML ainda os devolve (limite de 12 meses)
MIN_PEDIDOS_NA_HORA_0 = 5       # o dia D só serve se tiver pelo menos tantos pedidos criados na hora 0 de D+1 (senão a diferença some na tolerância)
MIN_PEDIDOS_NA_HORA_23 = 5      # idem para a hora 23 de D (a chamada 2 corta a hora 23? precisa de pedidos nela para a diferença aparecer)
TOLERANCIA = 2                  # diferença aceita entre o total do ML e o do banco, em pedidos (os mínimos acima precisam ser maiores que o dobro disso)
PAUSA_ENTRE_CHAMADAS_S = 1      # silêncio antes da 2ª chamada
# ========================================

EMPRESA = {"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA]
definir_empresa_ativa(EMPRESA)
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_filtro_de_hora_do_orders_search_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def hora(instante):
    return instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


def dia_curto(dia):
    return f"{dia:%d/%m/%Y}"


def tabela(titulo, colunas, linhas, a_direita=()):
    console.print(f"[bold]{t(titulo)}[/]")
    tab = Table(box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
    for i, coluna in enumerate(colunas):
        tab.add_column(coluna, justify="right" if i in a_direita else "left", overflow="fold")
    for linha in linhas:
        tab.add_row(*[t(c) for c in linha])
    console.print(tab)


def inicio_do_dia(dia, hora_do_dia=0):
    return datetime(dia.year, dia.month, dia.day, hora_do_dia, tzinfo=FUSO)


# ======================================================== 0) o dia do teste, escolhido no banco ========================================================

def estatisticas_do_dia(por_dia, dia):
    do_dia, do_seguinte = por_dia.get(dia, {}), por_dia.get(dia + timedelta(days=1), {})
    hora_0_seguinte = [c for c in do_seguinte.values() if c.hour == 0]
    hora_23 = [c for c in do_dia.values() if c.hour == 23]
    return {"dia": dia, "pedidos_do_dia": len(do_dia), "pedidos_hora_0_do_dia_seguinte": len(hora_0_seguinte), "pedidos_hora_23_do_dia": len(hora_23),
            "mais_novo_do_dia": max(do_dia.values()) if do_dia else None, "mais_novo_hora_0_do_dia_seguinte": max(hora_0_seguinte) if hora_0_seguinte else None}


def escolher_o_dia():
    hoje = datetime.now(FUSO).date()
    primeiro, ultimo = hoje - timedelta(days=DIAS_PARA_TRAS_MAX), hoje - timedelta(days=3)
    por_dia = defaultdict(dict)
    if DIA_DO_TESTE is not None:
        primeiro = ultimo = DIA_DO_TESTE
    consulta = VendaItemMercadoLivre.objects.filter(dia_venda__gte=primeiro, dia_venda__lte=ultimo + timedelta(days=1))
    for order_id, dia, criado in consulta.values_list("order_id", "dia_venda", "criado_em_ml").iterator(chunk_size=5000):
        por_dia[dia][order_id] = criado.astimezone(FUSO)
    dias = [primeiro + timedelta(days=i) for i in range((ultimo - primeiro).days + 1)]
    estatisticas = [estatisticas_do_dia(por_dia, d) for d in dias]
    if DIA_DO_TESTE is not None:
        return estatisticas[0], estatisticas
    aptos = [e for e in estatisticas if e["pedidos_hora_0_do_dia_seguinte"] >= MIN_PEDIDOS_NA_HORA_0 and e["pedidos_hora_23_do_dia"] >= MIN_PEDIDOS_NA_HORA_23 and e["pedidos_do_dia"] >= 20]
    if not aptos:
        return None, estatisticas
    return max(aptos, key=lambda e: (e["pedidos_hora_0_do_dia_seguinte"], e["dia"])), estatisticas


def mostrar_o_dia(escolhido, estatisticas):
    console.rule("[bold]0) O dia do teste, escolhido no banco")
    melhores = sorted(estatisticas, key=lambda e: (-e["pedidos_hora_0_do_dia_seguinte"], e["dia"]))[:5]
    tabela("Os dias com mais pedidos na hora 0 do dia seguinte (o escolhido é o de cima que serve)", ["Dia D", "Pedidos de D", "Hora 0 de D+1", "Hora 23 de D"],
           [(dia_curto(e["dia"]), n(e["pedidos_do_dia"]), n(e["pedidos_hora_0_do_dia_seguinte"]), n(e["pedidos_hora_23_do_dia"])) for e in melhores], a_direita=(1, 2, 3))
    d = escolhido["dia"]
    tabela(f"O que o BANCO diz sobre o dia {dia_curto(d)}", ["O quê", "Valor"], [
        ("Pedidos de D", n(escolhido["pedidos_do_dia"])),
        (f"Pedidos criados na hora 0 de {dia_curto(d + timedelta(days=1))}", n(escolhido["pedidos_hora_0_do_dia_seguinte"])),
        ("Pedidos criados na hora 23 de D", n(escolhido["pedidos_hora_23_do_dia"])),
        ("Pedido mais novo de D", "—" if escolhido["mais_novo_do_dia"] is None else hora(escolhido["mais_novo_do_dia"])),
        ("Pedido mais novo da hora 0 de D+1", "—" if escolhido["mais_novo_hora_0_do_dia_seguinte"] is None else hora(escolhido["mais_novo_hora_0_do_dia_seguinte"])),
    ], a_direita=(1,))


# ======================================================== 1 e 2) as 2 chamadas ========================================================

def mascarar(texto, user_id):
    texto = str(texto)[:300]
    return texto.replace(str(user_id), "***") if user_id else texto


def chamar(api, inicio, fim):
    antes = requisicoes_enviadas_nesta_thread()
    pacote = api.buscar_pedidos(inicio, fim, offset=0, limite=1)
    resultado = {"requisicoes_http": requisicoes_enviadas_nesta_thread() - antes, "http": pacote.http, "erro": None if pacote.erro is None else mascarar(pacote.erro, getattr(api, "_user_id", None)),
                 "total": None, "primeiro_da_lista_criado_em": None, "status_do_primeiro_da_lista": None}
    if pacote.erro is None and pacote.http == 200 and isinstance(pacote.dados, dict):
        resultado["total"] = (pacote.dados.get("paging") or {}).get("total")
        itens = pacote.dados.get("results") or []
        if itens:
            try:
                resultado["primeiro_da_lista_criado_em"] = datetime.fromisoformat(str(itens[0].get("date_created"))).astimezone(FUSO)
            except ValueError:
                pass
            resultado["status_do_primeiro_da_lista"] = itens[0].get("status")
    return resultado


def mostrar_chamada(titulo, inicio, fim, r):
    linhas = [("Janela pedida (from → to)", f"{hora(inicio)} → {hora(fim)}"), ("Requisições HTTP gastas", n(r["requisicoes_http"])), ("HTTP", str(r["http"]))]
    if r["erro"]:
        linhas.append(("Erro", r["erro"]))
    linhas.append(("paging.total (pedidos na janela, segundo o ML)", "—" if r["total"] is None else n(r["total"])))
    linhas.append(("1º pedido da lista, sort=date_desc (criado em)", "—" if r["primeiro_da_lista_criado_em"] is None else hora(r["primeiro_da_lista_criado_em"])))
    tabela(titulo, ["O quê", "Valor"], linhas)


# ======================================================== 3) leitura ========================================================

def perto(a, b):
    return a is not None and abs(a - b) <= TOLERANCIA


def montar_leitura(e, c1, c2):
    d = e["dia"]
    seguinte = d + timedelta(days=1)
    n_d, h0, h23 = e["pedidos_do_dia"], e["pedidos_hora_0_do_dia_seguinte"], e["pedidos_hora_23_do_dia"]
    leitura, hipotese, correcao = [], None, None
    if c1["total"] is None:
        leitura.append(f"CHAMADA 1 não trouxe o total (HTTP {c1['http']}). Nada a concluir sobre a busca atual.")
    else:
        com_hora, sem_hora = perto(c1["total"], n_d + h0), perto(c1["total"], n_d)
        if com_hora and not sem_hora:
            hipotese = True
            leitura.append(f"CHAMADA 1 CONFIRMA a hipótese: o ML devolveu {n(c1['total'])} pedidos, que é o dia {dia_curto(d)} ({n(n_d)}) MAIS a hora 0 de {dia_curto(seguinte)} ({n(h0)}). "
                           f"A busca 'até 00:00 do dia seguinte' lê até 00:59:59.")
        elif sem_hora and not com_hora:
            hipotese = False
            leitura.append(f"CHAMADA 1 REFUTA a hipótese: o ML devolveu {n(c1['total'])} pedidos, igual ao dia {dia_curto(d)} no banco ({n(n_d)}); a hora 0 do dia seguinte NÃO veio junto.")
        elif com_hora and sem_hora:
            leitura.append(f"CHAMADA 1 inconclusiva: total {n(c1['total'])}, dentro da tolerância tanto de 'só o dia' ({n(n_d)}) quanto de 'o dia + a hora 0' ({n(n_d + h0)}). Escolha outro dia com DIA_DO_TESTE.")
        else:
            leitura.append(f"CHAMADA 1 não combina com nenhuma das duas contas: total {n(c1['total'])}; só o dia seria {n(n_d)} e o dia + a hora 0 seria {n(n_d + h0)}. O banco pode estar incompleto neste dia.")
    if c2["total"] is None:
        leitura.append(f"CHAMADA 2 não trouxe o total (HTTP {c2['http']}). A correção candidata não foi testada.")
    else:
        com_23, sem_23 = perto(c2["total"], n_d), perto(c2["total"], n_d - h23)
        if com_23 and not sem_23:
            correcao = True
            leitura.append(f"CHAMADA 2 CONFIRMA a correção candidata: com to = {hora(inicio_do_dia(d, 23))} (fim − 1 hora) o ML devolveu {n(c2['total'])} pedidos, igual ao dia {dia_curto(d)} no banco ({n(n_d)}). "
                           f"A hora 23 entrou inteira (sem ela seriam {n(n_d - h23)}) e a hora 0 do dia seguinte ficou de fora.")
        elif sem_23 and not com_23:
            correcao = False
            leitura.append(f"CHAMADA 2 NÃO confirma a correção: total {n(c2['total'])} = o dia SEM a hora 23 ({n(n_d)} − {n(h23)}). Com to = 23:00 o ML cortou a hora 23: NÃO mude o coletor.")
        elif com_23 and sem_23:
            leitura.append(f"CHAMADA 2 inconclusiva: total {n(c2['total'])}, dentro da tolerância tanto de 'o dia' ({n(n_d)}) quanto de 'o dia sem a hora 23' ({n(n_d - h23)}). Escolha outro dia com DIA_DO_TESTE.")
        else:
            leitura.append(f"CHAMADA 2 não combina com nenhuma das duas contas: total {n(c2['total'])}; o dia seria {n(n_d)} e o dia sem a hora 23 seria {n(n_d - h23)}. O banco pode estar incompleto neste dia.")
    primeiro = c1["primeiro_da_lista_criado_em"]
    mais_novo_no_banco = e["mais_novo_hora_0_do_dia_seguinte"] or e["mais_novo_do_dia"]
    if primeiro is not None and mais_novo_no_banco is not None and primeiro < mais_novo_no_banco - timedelta(minutes=1):
        leitura.append(f"ORDEM: o 1º pedido da lista (sort=date_desc) foi criado em {hora(primeiro)}, mas o banco tem pedido mais novo na mesma janela ({hora(mais_novo_no_banco)}): a ordem do ML NÃO é pela data "
                       f"de criação. Isso importa para a paginação por offset (se a ordem muda enquanto se pagina, pedido pode repetir ou faltar) e é uma pista para o aviso 'anunciou 202, vieram 201', mas não está provado.")
    if hipotese and correcao:
        leitura.append("RESUMO: as duas chamadas confirmam. Mandar fim − 1 hora como order.date_created.to lê o dia sem repetir a hora 0 do dia seguinte. Antes de mudar o coletor, o mesmo cuidado vale "
                       "para a divisão de janelas grandes (por hora) e para a busca por MLB.")
    elif hipotese is False:
        leitura.append("RESUMO: a hipótese da hora 0 foi refutada para este dia; a diferença das coletas tem outra causa (as conferências do banco continuam valendo).")
    return leitura, hipotese, correcao


def main():
    console.print(f"\n[bold]Filtro de hora do /orders/search[/] · conta {CONTA} · 2 chamadas de 1 pedido (GET) · nada é gravado\n")
    escolhido, estatisticas = escolher_o_dia()
    if escolhido is None:
        console.print(f"[bold red]Nenhum dia dos últimos {DIAS_PARA_TRAS_MAX} dias tem {MIN_PEDIDOS_NA_HORA_0}+ pedidos na hora 0 do dia seguinte e {MIN_PEDIDOS_NA_HORA_23}+ na hora 23. Informe DIA_DO_TESTE ou aumente DIAS_PARA_TRAS_MAX.[/]")
        return
    mostrar_o_dia(escolhido, estatisticas)
    d = escolhido["dia"]
    api = ApiMercadoLivre(pasta_logs=_caminho_pasta_logs(EMPRESA), empresa=EMPRESA)

    console.rule("[bold]1) Chamada 1: a busca como o coletor faz hoje")
    inicio, fim_atual, fim_candidato = inicio_do_dia(d), inicio_do_dia(d + timedelta(days=1)), inicio_do_dia(d, 23)
    try:
        c1 = chamar(api, inicio, fim_atual)
        mostrar_chamada("Resposta da chamada 1 (to = D+1 00:00)", inicio, fim_atual, c1)
        console.rule("[bold]2) Chamada 2: a correção candidata (to = fim − 1 hora)")
        time.sleep(PAUSA_ENTRE_CHAMADAS_S)
        c2 = chamar(api, inicio, fim_candidato)
        mostrar_chamada("Resposta da chamada 2 (to = D 23:00)", inicio, fim_candidato, c2)
    except ErroAutenticacaoAPI:
        console.print("[bold red]O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi concluído.[/]")
        return

    console.rule("[bold]Leitura")
    leitura, hipotese, correcao = montar_leitura(escolhido, c1, c2)
    for linha in leitura:
        if linha.startswith("   "):
            console.print(f"    {t(linha.strip())}")
        else:
            console.print(f"• {t(linha)}")
    banco = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in escolhido.items()}
    saida = {"conta": CONTA, "dia_do_teste": d.isoformat(), "banco": banco,
             "chamada_1_to_dia_seguinte_00h": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in c1.items()},
             "chamada_2_to_dia_23h": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in c2.items()},
             "hipotese_da_hora_0_confirmada": hipotese, "correcao_candidata_confirmada": correcao, "leitura": leitura}
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem dado de comprador e sem seller_id.")


if __name__ == "__main__":
    main()
