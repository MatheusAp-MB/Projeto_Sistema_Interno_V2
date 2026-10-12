# scripts_exploracao_ML/investigar_empates_de_fechamento_nas_paginas_so_no_banco.py
#
# Função Objetivo: TESTAR, SÓ COM O BANCO, a hipótese de que o aviso "o ML anunciou 202 pedidos e vieram 201" (08/07/2026, coleta do ano) nasce de um EMPATE de fechamento colado na fronteira de uma página.
#
# Contexto (12/10/2026): a doc de Orders (vault, Fontes/Orders.txt: "Sellers por date_closed") e o teste conferir_ordem_do_sort_do_orders_search.py mostraram que o sort=date_desc do /orders/search ordena
# pela data de FECHAMENTO do pedido (date_closed), não pela de criação, e com precisão de 1 segundo. Dois pedidos fechados no MESMO segundo não têm ordem definida entre si. O coletor pagina por offset
# (páginas de 50: posições 0-49, 50-99...). Se um par empatado fica nas posições 49 e 50 (ou 99 e 100, 149 e 150...), e o ML manda o par em ordens diferentes na chamada de uma página e na da
# seguinte, o pedido da posição 49 vem 2 vezes (o coletor descarta a cópia) e o outro não vem nunca: "anunciou 202, vieram 201".
#
# O QUE O SCRIPT FAZ (só leitura: SELECT em VendaItemMercadoLivre; NENHUMA chamada ao ML; nada é gravado):
#   1) Para cada dia fechado do banco, monta as 2 janelas que o coletor já usou: ANTIGA (de D 00:00 até D+1 00:59, porque o filtro "to" lê a hora inteira: o dia D + os pedidos criados na hora 0 de D+1)
#      e NOVA (só o dia D, a que o coletor passou a usar com `to = fim − 1 hora`).
#   2) Ordena cada janela por fechamento (decrescente), como o ML, e olha as FRONTEIRAS de página (posições 49|50, 99|100, 149|150...): se os 2 pedidos de uma fronteira fecharam no mesmo segundo,
#      o dia é um CANDIDATO a falhar.
#   3) Olha o dia do aviso conhecido (08/07/2026): quantos pedidos tem a janela ANTIGA (o aviso diz 202) e se ela tem empate numa fronteira.
#   4) Conta quantos dias são candidatos nas 2 janelas e guarda a lista no JSON (o script conferir_reproducao_do_empate_na_api.py usa essa lista para reproduzir o problema com ~8 chamadas).
#
# COMO LER O RESULTADO: um empate na fronteira é CONDIÇÃO para o problema, não prova de que ele aconteceu (o ML precisa trocar a ordem do par entre as duas páginas). Por isso o número de dias
# candidatos é o TETO de avisos que a hipótese explica. Se o dia 08/07 NÃO for candidato na janela antiga, a hipótese de empate NÃO explica aquele aviso.
#
# REGRAS: SÓ LEITURA e SÓ BANCO. Sem dado de comprador (o banco nem guarda). O JSON de saída é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → O ML pode colocar os pedidos SEM fechamento (ainda não pagos) no começo ou no fim da lista: a doc não diz. Quando um dia tem pedido sem fechamento, o script calcula os dois casos
#                  e chama de candidato se QUALQUER um dos dois põe um empate na fronteira.
# * [EXPLICAÇÃO] → Pedido é contado por order_id distinto (um pedido com vários itens tem várias linhas). O fechamento é cortado no segundo (o ML manda sem milissegundos).
# * [EXPLICAÇÃO] → O banco guarda o fechamento de HOJE; a coleta do ano leu os valores de 11/10/2026. Pedido que mudou de fechamento nesse meio-tempo pode mudar a conta (raro).

import json
import os
import shutil
import sys
from collections import Counter, defaultdict
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

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from mercado_livre.models import VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                                    # "MB" (Magazine) ou "SV" (Samvale): decide o banco
TAMANHO_DA_PAGINA = 50                          # o tamanho da página do coletor (LIMITE_POR_PAGINA)
DIA_DO_AVISO_CONHECIDO = date(2026, 7, 8)       # o dia do aviso "o ML anunciou 202 pedidos e vieram 201" da coleta do ano de 11/10/2026
TOTAL_ANUNCIADO_NO_AVISO = 202                  # o total que o aviso dizia
PRIMEIRO_DIA = None                             # None = o 2º dia do banco (o 1º pode estar cortado pelo limite de 12 meses do ML). Ou date(2025, 10, 12)
ULTIMO_DIA = None                               # None = ontem (hoje ainda está aberto)
LINHAS_NA_LISTA = 15                            # linhas de exemplo na tela (o JSON leva todas)
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_empates_de_fechamento_nas_paginas_so_no_banco_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def hora(instante):
    return "—" if instante is None else instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


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


# ======================================================== análise (funções puras) ========================================================

# Função Objetivo: Os pedidos do banco por dia da venda: {dia: {order_id: (hora_da_venda, fechado_em cortado no segundo ou None)}}. 1 entrada por pedido (não por item).
def carregar_pedidos(primeiro, ultimo):
    por_dia = defaultdict(dict)
    consulta = VendaItemMercadoLivre.objects.filter(dia_venda__gte=primeiro, dia_venda__lte=ultimo + timedelta(days=1))
    for order_id, dia, hora_da_venda, fechado in consulta.values_list("order_id", "dia_venda", "hora_venda", "fechado_em_ml").iterator(chunk_size=5000):
        fechado = fechado.replace(microsecond=0) if fechado else None
        atual = por_dia[dia].get(order_id)
        if atual is None or (atual[1] is None and fechado is not None):
            por_dia[dia][order_id] = (hora_da_venda, fechado)
    return por_dia


# Função Objetivo: Os pedidos de 1 janela, como (order_id, fechado_em). "antiga" = o dia D + os criados na hora 0 de D+1 (o que o coletor lia antes da correção); "nova" = só o dia D.
def pedidos_da_janela(por_dia, dia, modelo):
    itens = [(order_id, fechado) for order_id, (_, fechado) in por_dia.get(dia, {}).items()]
    if modelo == "antiga":
        itens += [(order_id, fechado) for order_id, (hora_da_venda, fechado) in por_dia.get(dia + timedelta(days=1), {}).items() if hora_da_venda == 0]
    return itens


# Função Objetivo: A janela na ordem do sort (fechamento decrescente). Pedido sem fechamento vai para o fim ou para o começo (a doc não diz onde o ML põe).
def ordenar_por_fechamento(itens, sem_fechamento_no_comeco):
    com = sorted((i for i in itens if i[1] is not None), key=lambda i: i[1], reverse=True)
    sem = [i for i in itens if i[1] is None]
    return sem + com if sem_fechamento_no_comeco else com + sem


# Função Objetivo: As fronteiras de página (posições k-1 e k, k = 50, 100, 150...) cujos 2 pedidos têm o MESMO fechamento (ao segundo), numa ordem dada. Mais: o tamanho do grupo empatado.
def fronteiras_com_empate(ordenados, tamanho_da_pagina):
    grupos = Counter(f for _, f in ordenados if f is not None)
    achadas = []
    for k in range(tamanho_da_pagina, len(ordenados), tamanho_da_pagina):
        antes, depois = ordenados[k - 1], ordenados[k]
        if antes[1] is not None and antes[1] == depois[1]:
            achadas.append({"fronteira": k, "fechado_em": antes[1], "grupo": grupos[antes[1]], "pedidos": [antes[0], depois[0]]})
    return achadas


# Função Objetivo: Tudo de 1 janela: tamanho, pedidos sem fechamento, grupos empatados em qualquer lugar e as fronteiras com empate (nos 2 casos de pedido sem fechamento, se houver).
def analisar_janela(itens, tamanho_da_pagina):
    sem_fechamento = sum(1 for _, f in itens if f is None)
    grupos = Counter(f for _, f in itens if f is not None)
    variantes = [("sem fechamento no fim", False)] if not sem_fechamento else [("sem fechamento no fim", False), ("sem fechamento no começo", True)]
    fronteiras = []
    for nome, no_comeco in variantes:
        for achada in fronteiras_com_empate(ordenar_por_fechamento(itens, no_comeco), tamanho_da_pagina):
            fronteiras.append({**achada, "variante": nome if sem_fechamento else "—"})
    return {"pedidos": len(itens), "sem_fechamento": sem_fechamento, "grupos_empatados": sum(1 for c in grupos.values() if c >= 2),
            "pedidos_em_empate": sum(c for c in grupos.values() if c >= 2), "fronteiras_com_empate": fronteiras}


def montar_leitura(resumo, aviso):
    leitura = []
    for modelo, rotulo in (("antiga", "janela ANTIGA (dia + hora 0 do dia seguinte)"), ("nova", "janela NOVA (só o dia)")):
        r = resumo[modelo]
        porcento = f"{100 * r['dias_candidatos'] / r['dias']:.1f}".replace(".", ",") if r["dias"] else "0"
        leitura.append(f"{rotulo}: {n(r['dias_candidatos'])} de {n(r['dias'])} dias ({porcento}%) têm 2 pedidos de fechamento IGUAL colados numa fronteira de página "
                       f"(em média {str(round(r['empates_por_dia'], 2)).replace('.', ',')} grupos empatados por dia).")
    a = aviso
    if a is None:
        leitura.append(f"O dia do aviso ({dia_curto(DIA_DO_AVISO_CONHECIDO)}) não está no intervalo analisado do banco: não dá para conferir o aviso conhecido.")
    else:
        confere = "bate com" if a["pedidos_janela_antiga"] == TOTAL_ANUNCIADO_NO_AVISO else "NÃO bate com"
        leitura.append(f"Dia do aviso {dia_curto(DIA_DO_AVISO_CONHECIDO)}: a janela antiga tem {n(a['pedidos_janela_antiga'])} pedidos no banco, o que {confere} os {n(TOTAL_ANUNCIADO_NO_AVISO)} que o ML anunciou.")
        if a["fronteiras_janela_antiga"]:
            pares = "; ".join(f"posições {f['fronteira'] - 1}|{f['fronteira']} fechadas em {hora(f['fechado_em'])}" for f in a["fronteiras_janela_antiga"])
            leitura.append(f"O dia {dia_curto(DIA_DO_AVISO_CONHECIDO)} TEM empate numa fronteira da janela antiga ({pares}). Isso COMBINA com o aviso: era um candidato a falhar.")
        else:
            leitura.append(f"O dia {dia_curto(DIA_DO_AVISO_CONHECIDO)} NÃO tem empate de fechamento numa fronteira da janela antiga. Então a hipótese de empate NÃO explica o aviso de 08/07 "
                           f"(salvo se o fechamento de algum pedido mudou depois da coleta). Próximo passo: reler esse dia (\"Coletar dia\") para ver se o aviso volta.")
        if a["fronteiras_janela_nova"]:
            leitura.append("Na janela NOVA esse dia também tem empate na fronteira: a releitura do coletor é a proteção que importa.")
        else:
            leitura.append("Na janela NOVA esse dia não tem empate na fronteira: com a correção `fim − 1 hora` a fronteira mudou de lugar.")
    avisos_reais = 2
    leitura.append(f"A coleta do ano teve {avisos_reais} avisos. O empate só vira aviso se o ML trocar a ordem do par entre as duas páginas; por isso os {n(resumo['antiga']['dias_candidatos'])} dias candidatos da janela antiga "
                   f"são o TETO do que a hipótese explica. Se forem poucos (ordem de 2 a 10), combina; se forem centenas, empate é comum e o ML quase nunca troca a ordem, então a hipótese perde força.")
    leitura.append("Para reproduzir com o ML, rode conferir_reproducao_do_empate_na_api.py (~8 chamadas): ele lê a lista de candidatos deste JSON.")
    return leitura


def main():
    console.print(f"\n[bold]Empates de fechamento nas fronteiras de página[/] · conta {CONTA} · só banco, nenhuma chamada ao ML · páginas de {TAMANHO_DA_PAGINA}\n")
    ontem = datetime.now(FUSO).date() - timedelta(days=1)
    datas = list(VendaItemMercadoLivre.objects.order_by("dia_venda").values_list("dia_venda", flat=True).distinct()[:2])
    if not datas:
        console.print("[bold red]O banco não tem nenhuma venda.[/]")
        return
    primeiro = PRIMEIRO_DIA or (datas[1] if len(datas) > 1 else datas[0])
    ultimo = ULTIMO_DIA or ontem
    por_dia = carregar_pedidos(primeiro, ultimo)
    dias = [primeiro + timedelta(days=i) for i in range((ultimo - primeiro).days + 1)]
    dias = [d for d in dias if por_dia.get(d)]
    console.print(f"Dias analisados: {n(len(dias))} ({dia_curto(dias[0])} a {dia_curto(dias[-1])}).\n")

    resumo = {"antiga": {"dias": 0, "dias_candidatos": 0, "pedidos": 0, "sem_fechamento": 0, "empates_por_dia": 0.0}, "nova": {"dias": 0, "dias_candidatos": 0, "pedidos": 0, "sem_fechamento": 0, "empates_por_dia": 0.0}}
    candidatos, aviso = [], None
    grupos_total = {"antiga": 0, "nova": 0}
    for dia in dias:
        por_modelo = {}
        for modelo in ("antiga", "nova"):
            analise = analisar_janela(pedidos_da_janela(por_dia, dia, modelo), TAMANHO_DA_PAGINA)
            por_modelo[modelo] = analise
            r = resumo[modelo]
            r["dias"] += 1
            r["pedidos"] += analise["pedidos"]
            r["sem_fechamento"] += analise["sem_fechamento"]
            grupos_total[modelo] += analise["grupos_empatados"]
            if analise["fronteiras_com_empate"]:
                r["dias_candidatos"] += 1
                for f in analise["fronteiras_com_empate"]:
                    candidatos.append({"janela": modelo, "dia": dia.isoformat(), "pedidos_na_janela": analise["pedidos"], "fronteira": f["fronteira"], "fechado_em": f["fechado_em"].isoformat(),
                                       "grupo_empatado": f["grupo"], "variante": f["variante"], "pedidos": f["pedidos"]})
        if dia == DIA_DO_AVISO_CONHECIDO:
            aviso = {"pedidos_janela_antiga": por_modelo["antiga"]["pedidos"], "pedidos_janela_nova": por_modelo["nova"]["pedidos"],
                     "fronteiras_janela_antiga": por_modelo["antiga"]["fronteiras_com_empate"], "fronteiras_janela_nova": por_modelo["nova"]["fronteiras_com_empate"]}
    for modelo in ("antiga", "nova"):
        resumo[modelo]["empates_por_dia"] = grupos_total[modelo] / max(1, resumo[modelo]["dias"])

    console.rule("[bold]1) Quanto empate existe")
    tabela("Por janela", ["Janela", "Dias", "Pedidos por dia (média)", "Pedidos sem fechamento", "Grupos empatados por dia (média)", "Dias com empate NA FRONTEIRA"],
           [(modelo, n(r["dias"]), f"{r['pedidos'] / max(1, r['dias']):.0f}", n(r["sem_fechamento"]), f"{r['empates_por_dia']:.2f}".replace(".", ","), n(r["dias_candidatos"])) for modelo, r in resumo.items()],
           a_direita=(1, 2, 3, 4, 5))
    console.print("Janela antiga = o dia D + os pedidos criados na hora 0 de D+1 (como o coletor lia). Janela nova = só o dia D (como lê depois da correção).")

    console.rule("[bold]2) O dia do aviso conhecido")
    if aviso is None:
        console.print(f"O dia {dia_curto(DIA_DO_AVISO_CONHECIDO)} não está no banco/intervalo analisado.")
    else:
        linhas = [("Pedidos na janela ANTIGA (o aviso dizia " + n(TOTAL_ANUNCIADO_NO_AVISO) + ")", n(aviso["pedidos_janela_antiga"])), ("Pedidos na janela NOVA", n(aviso["pedidos_janela_nova"]))]
        for rotulo, chave in (("ANTIGA", "fronteiras_janela_antiga"), ("NOVA", "fronteiras_janela_nova")):
            if not aviso[chave]:
                linhas.append((f"Empate numa fronteira da janela {rotulo}", "nenhum"))
            for f in aviso[chave]:
                linhas.append((f"Empate numa fronteira da janela {rotulo}", f"posições {f['fronteira'] - 1}|{f['fronteira']}, fechadas em {hora(f['fechado_em'])} (grupo de {f['grupo']})"))
        tabela(f"Dia {dia_curto(DIA_DO_AVISO_CONHECIDO)}", ["O quê", "Valor"], linhas)

    console.rule("[bold]3) Dias candidatos (empate numa fronteira)")
    ordenados = sorted(candidatos, key=lambda c: (c["janela"] != "antiga", c["dia"], c["fronteira"]))
    tabela(f"Mostrando até {LINHAS_NA_LISTA} de {n(len(ordenados))} (o JSON leva todos)", ["Janela", "Dia", "Pedidos na janela", "Fronteira", "Fechamento do par", "Grupo", "Variante"],
           [(c["janela"], f"{c['dia'][8:10]}/{c['dia'][5:7]}/{c['dia'][:4]}", n(c["pedidos_na_janela"]), f"{c['fronteira'] - 1}|{c['fronteira']}", hora(datetime.fromisoformat(c["fechado_em"])), str(c["grupo_empatado"]), c["variante"])
            for c in ordenados[:LINHAS_NA_LISTA]], a_direita=(2,))

    console.rule("[bold]Leitura")
    leitura = montar_leitura(resumo, aviso)
    for linha in leitura:
        console.print(f"• {t(linha)}")

    saida = {"conta": CONTA, "tamanho_da_pagina": TAMANHO_DA_PAGINA, "primeiro_dia": dias[0].isoformat(), "ultimo_dia": dias[-1].isoformat(), "resumo": resumo,
             "dia_do_aviso": None if aviso is None else {"dia": DIA_DO_AVISO_CONHECIDO.isoformat(), "pedidos_janela_antiga": aviso["pedidos_janela_antiga"], "pedidos_janela_nova": aviso["pedidos_janela_nova"],
                                                          "fronteiras_janela_antiga": [{**f, "fechado_em": f["fechado_em"].isoformat()} for f in aviso["fronteiras_janela_antiga"]],
                                                          "fronteiras_janela_nova": [{**f, "fechado_em": f["fechado_em"].isoformat()} for f in aviso["fronteiras_janela_nova"]]},
             "candidatos": ordenados, "leitura": leitura}
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem dado de comprador.")


if __name__ == "__main__":
    main()
