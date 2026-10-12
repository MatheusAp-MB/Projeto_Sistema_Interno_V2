# scripts_exploracao_ML/conferir_ordem_do_sort_do_orders_search.py
#
# Função Objetivo: DESCOBRIR, com 1 chamada ao GET /orders/search, POR QUAL CAMPO DE DATA o parâmetro sort=date_desc realmente ordena a lista de pedidos.
#
# Contexto (12/10/2026): no teste do filtro de hora (conferir_filtro_de_hora_do_orders_search.py), o 1º pedido da lista com sort=date_desc foi criado às 12:44:32 do dia 24/11/2025,
# mesmo havendo no banco pedidos desse dia criados até 23:57. Ou seja: a lista NÃO está ordenada pela data de criação (date_created). A coleta pagina por offset (50 por página); se a
# ordem da lista muda ENQUANTO se pagina (por exemplo, um pedido recebe uma atualização e sobe para o topo), um pedido pode aparecer 2 vezes (o coletor descarta o repetido) e outro pode
# não aparecer. É a pista mais forte para o aviso "o ML anunciou 202 pedidos, vieram 201" visto em 08/07/2026. Este script diz por qual campo a lista está em ordem.
#
# RESULTADO (12/10/2026, dia 24/11/2025): a lista segue date_closed (fechamento). O pedido de 12:44:32 apareceu no topo porque fechou só em 27/11; expiration_date = date_closed + 28 dias. A doc de Orders do
# vault (Fontes/Orders.txt) já dizia: "Sellers por date_closed". O palpite inicial (last_updated) estava errado.
#
# O QUE O SCRIPT FAZ (só leitura: 1 GET, nenhum SELECT, nada é gravado):
#   1) Pede os primeiros PEDIDOS_NA_LISTA pedidos do dia DIA_DO_TESTE, com a MESMA chamada do coletor (ApiMercadoLivre.buscar_pedidos), com to = fim − 1 hora (a correção confirmada hoje).
#   2) Acha sozinho todos os campos de data de 1º nível do pedido (date_created, date_closed, last_updated...) e mostra a tabela na ordem em que o ML mandou.
#   3) Para cada campo, conta quantos pares vizinhos estão FORA da ordem decrescente. O campo com 0 pares fora de ordem (e com datas diferentes entre si) é o campo do sort.
#
# REGRAS: não lê nem mostra dado de comprador; mostra só o número do pedido, o status e as datas. O seller_id não vai para a tela nem para o JSON. O JSON é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → 1 chamada de limit=20 custa o mesmo que 1 de limit=5 (a cota conta chamadas, não pedidos): 20 pedidos dão mais prova para escolher o campo.
# * [EXPLICAÇÃO] → O dia padrão é 24/11/2025 (o mesmo do teste anterior, 465 pedidos): é o dia em que a anomalia já apareceu. Troque DIA_DO_TESTE para repetir em outro dia (dentro dos últimos 12 meses).

import json
import os
import shutil
import sys
from datetime import date, datetime
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
CONTA = "MB"                            # "MB" (Magazine) ou "SV" (Samvale)
DIA_DO_TESTE = date(2025, 11, 24)       # o dia D da busca (dentro dos últimos 12 meses): from = D 00:00, to = D 23:00 (que lê o dia D inteiro)
PEDIDOS_NA_LISTA = 20                   # quantos pedidos a única chamada traz (máximo 50 por página)
MIN_VALORES_PARA_CONCLUIR = 8           # um campo só conta se pelo menos tantos pedidos da lista tiverem esse campo preenchido
MIN_DATAS_DIFERENTES = 4                # e se as datas não forem (quase) todas iguais: campo constante não prova ordem nenhuma
# ========================================

EMPRESA = {"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA]
definir_empresa_ativa(EMPRESA)
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" usaria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_ordem_do_sort_do_orders_search_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def hora(instante):
    return "—" if instante is None else instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


def hora_curta(instante):
    return "—" if instante is None else instante.astimezone(FUSO).strftime("%d/%m %H:%M:%S")


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


# ======================================================== análise (funções puras, sem API) ========================================================

# Função Objetivo: Texto ISO com fuso (ex.: 2025-11-24T12:44:32.000-04:00) vira datetime; qualquer outra coisa (None, número, texto sem fuso) vira None.
def ler_data(valor):
    if not isinstance(valor, str) or "T" not in valor:
        return None
    try:
        instante = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return instante.astimezone(FUSO) if instante.tzinfo is not None else None


# Função Objetivo: Os nomes dos campos de 1º nível que, em algum pedido da lista, trazem uma data com fuso, na ordem em que aparecem.
def descobrir_campos_de_data(itens):
    nomes = []
    for item in itens:
        for nome, valor in item.items():
            if nome not in nomes and ler_data(valor) is not None:
                nomes.append(nome)
    return nomes


# Função Objetivo: Para 1 campo, quantos pares de vizinhos da lista estão fora da ordem DECRESCENTE (e da CRESCENTE), e se o campo prova a ordem do sort.
def avaliar_campo(nome, itens):
    presentes = [ler_data(item.get(nome)) for item in itens]
    presentes = [v for v in presentes if v is not None]
    fora_decrescente = sum(1 for a, b in zip(presentes, presentes[1:]) if a < b)
    fora_crescente = sum(1 for a, b in zip(presentes, presentes[1:]) if a > b)
    distintos = len(set(presentes))
    return {"campo": nome, "preenchidos": len(presentes), "datas_diferentes": distintos, "pares_fora_da_ordem_decrescente": fora_decrescente, "pares_fora_da_ordem_crescente": fora_crescente,
            "prova_a_ordem": len(presentes) >= MIN_VALORES_PARA_CONCLUIR and distintos >= MIN_DATAS_DIFERENTES,
            "decrescente_perfeito": len(presentes) >= MIN_VALORES_PARA_CONCLUIR and distintos >= MIN_DATAS_DIFERENTES and fora_decrescente == 0}


def montar_leitura(avaliacoes, quantos_pedidos, total):
    leitura = []
    if quantos_pedidos == 0:
        return ["A chamada não trouxe pedidos: nada a concluir. Confira DIA_DO_TESTE (precisa ter vendas e estar dentro dos últimos 12 meses)."]
    perfeitos = [a["campo"] for a in avaliacoes if a["decrescente_perfeito"]]
    if "date_closed" in perfeitos and "expiration_date" in perfeitos:
        perfeitos.remove("expiration_date")
        leitura.append("expiration_date também aparece em ordem, mas só porque é a data de fechamento (date_closed) mais um prazo fixo; não é outro critério.")
    sem_prova = [a["campo"] for a in avaliacoes if not a["prova_a_ordem"]]
    if len(perfeitos) == 1:
        campo = perfeitos[0]
        if campo == "date_created":
            leitura.append("A lista está em ordem decrescente de date_created (data de criação). Então a posição 'estranha' vista em 24/11/2025 NÃO vem do sort; procure outra causa para o 201 de 202.")
        elif campo == "date_closed":
            leitura.append("A lista está em ordem decrescente de date_closed (data de FECHAMENTO do pedido), e NÃO da data de criação: o sort=date_desc ordena por date_closed. Isso bate com a doc de Orders "
                           "(vault, Fontes/Orders.txt, nota do 'sort': para vendedor a ordem é por date_closed). Um pedido criado de manhã e fechado dias depois vai para o topo, longe dos criados na mesma hora.")
            leitura.append("Para a paginação por offset isso significa: (a) dois pedidos fechados no mesmo segundo não têm ordem definida entre si; se o par ficar na fronteira de uma página (posição 50, 100, 150...), "
                           "o ML pode mandar em ordens diferentes de uma página para outra, e 1 pedido repete (o coletor descarta a cópia) enquanto outro não vem; (b) pedido ainda sem fechamento que fecha durante a leitura muda de posição. "
                           "Nenhum dos dois está provado: o primeiro dá para testar só com o banco (fechado_em_ml).")
        else:
            leitura.append(f"A lista está em ordem decrescente de '{campo}' (0 pares fora de ordem), e NÃO da data de criação. O sort=date_desc do ML ordena por '{campo}'.")
            if campo in ("last_updated", "date_last_updated"):
                leitura.append("Isso é COMPATÍVEL com a paginação instável (ainda não provada): ordenar pela última atualização significa que um pedido que recebe atualização (pagamento, envio, entrega, reclamação, cancelamento) enquanto "
                               "a coleta pagina SOBE para o topo da lista e empurra os outros 1 posição: um pedido aparece 2 vezes (o coletor descarta a cópia) e o último da página some. "
                               "É o padrão do aviso 'anunciou 202, vieram 201'. A proteção é reler a janela quando o total não fecha (ver proposta).")
            else:
                leitura.append("Pistas para a paginação: pergunte se esse campo muda enquanto o pedido existe. Se mudar, a ordem muda no meio da paginação.")
    elif len(perfeitos) > 1:
        leitura.append(f"Mais de um campo está em ordem decrescente nesta lista ({', '.join(perfeitos)}): estes campos são quase iguais para estes pedidos. Repita com outro DIA_DO_TESTE para separar.")
    else:
        leitura.append("Nenhum campo de data de 1º nível está em ordem decrescente nesta lista. O ML pode ordenar por um campo que o pedido não mostra (ou por outro critério). "
                       "Peça a doc oficial do parâmetro 'sort' do GET /orders/search antes de decidir.")
    if sem_prova:
        leitura.append(f"Sem prova (poucos valores ou quase todos iguais): {', '.join(sem_prova)}.")
    criacao = next((a for a in avaliacoes if a["campo"] == "date_created"), None)
    if criacao is not None and criacao["pares_fora_da_ordem_decrescente"] > 0:
        leitura.append(f"Pela data de criação, {n(criacao['pares_fora_da_ordem_decrescente'])} pares vizinhos desta lista estão fora da ordem: confirmado que a lista NÃO segue a criação.")
    leitura.append(f"O ML anunciou {n(total) if total is not None else '—'} pedidos nesta janela; a chamada trouxe só os {n(quantos_pedidos)} primeiros da lista (é de propósito: 1 chamada).")
    return leitura


# ======================================================== a chamada ========================================================

def main():
    console.print(f"\n[bold]Ordem do sort=date_desc no /orders/search[/] · conta {CONTA} · 1 chamada (GET) de {n(PEDIDOS_NA_LISTA)} pedidos · nada é gravado\n")
    inicio = datetime(DIA_DO_TESTE.year, DIA_DO_TESTE.month, DIA_DO_TESTE.day, 0, tzinfo=FUSO)
    fim_para_a_api = datetime(DIA_DO_TESTE.year, DIA_DO_TESTE.month, DIA_DO_TESTE.day, 23, tzinfo=FUSO)
    api = ApiMercadoLivre(pasta_logs=_caminho_pasta_logs(EMPRESA), empresa=EMPRESA)
    antes = requisicoes_enviadas_nesta_thread()
    try:
        pacote = api.buscar_pedidos(inicio, fim_para_a_api, offset=0, limite=PEDIDOS_NA_LISTA)
    except ErroAutenticacaoAPI:
        console.print("[bold red]O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi concluído.[/]")
        return
    requisicoes = requisicoes_enviadas_nesta_thread() - antes
    erro = None if pacote.erro is None else mascarar(pacote.erro, getattr(api, "_user_id", None))
    itens, total = [], None
    if pacote.erro is None and pacote.http == 200 and isinstance(pacote.dados, dict):
        itens = [i for i in (pacote.dados.get("results") or []) if isinstance(i, dict)]
        total = (pacote.dados.get("paging") or {}).get("total")

    console.rule("[bold]A chamada")
    tabela("O que foi pedido e o que voltou", [ "O quê", "Valor"], [
        ("Janela pedida (from → to)", f"{hora(inicio)} → {hora(fim_para_a_api)}  (to = fim − 1 hora: lê o dia {DIA_DO_TESTE:%d/%m/%Y} inteiro)"),
        ("Requisições HTTP gastas", n(requisicoes)), ("HTTP", str(pacote.http)), ("Erro", erro or "—"),
        ("paging.total (pedidos na janela, segundo o ML)", "—" if total is None else n(total)), ("Pedidos trazidos nesta chamada", n(len(itens)))])

    campos = descobrir_campos_de_data(itens)
    avaliacoes = [avaliar_campo(c, itens) for c in campos]
    if itens:
        console.rule("[bold]A lista, na ordem em que o ML mandou")
        tabela("Cada linha é um pedido; as colunas são os campos de data que o pedido traz (horário de Brasília)", ["Pos.", "Pedido", "Status"] + campos,
               [(str(i + 1), item.get("id", "—"), item.get("status", "—")) + tuple(hora_curta(ler_data(item.get(c))) for c in campos) for i, item in enumerate(itens)], a_direita=(0,))
        console.rule("[bold]Qual campo está em ordem decrescente")
        tabela("Pares vizinhos fora da ordem, por campo (0 = a lista segue esse campo)", ["Campo", "Preenchidos", "Datas diferentes", "Fora da ordem decrescente", "Fora da ordem crescente", "Segue o sort?"],
               [(a["campo"], n(a["preenchidos"]), n(a["datas_diferentes"]), n(a["pares_fora_da_ordem_decrescente"]), n(a["pares_fora_da_ordem_crescente"]),
                 ("SIM" if a["decrescente_perfeito"] else ("não" if a["prova_a_ordem"] else "sem prova"))) for a in avaliacoes], a_direita=(1, 2, 3, 4))

    console.rule("[bold]Leitura")
    leitura = montar_leitura(avaliacoes, len(itens), total)
    for linha in leitura:
        console.print(f"• {t(linha)}")

    linhas_json = [{"posicao": i + 1, "pedido": item.get("id"), "status": item.get("status"), **{c: (None if ler_data(item.get(c)) is None else ler_data(item.get(c)).isoformat()) for c in campos}}
                   for i, item in enumerate(itens)]
    saida = {"conta": CONTA, "dia_do_teste": DIA_DO_TESTE.isoformat(), "to_enviado_para_a_api": fim_para_a_api.isoformat(), "requisicoes_http": requisicoes, "http": pacote.http, "erro": erro,
             "total_segundo_o_ml": total, "pedidos_trazidos": len(itens), "campos_de_data_achados": campos, "avaliacao_por_campo": avaliacoes, "lista": linhas_json, "leitura": leitura}
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem dado de comprador e sem seller_id.")


if __name__ == "__main__":
    main()
