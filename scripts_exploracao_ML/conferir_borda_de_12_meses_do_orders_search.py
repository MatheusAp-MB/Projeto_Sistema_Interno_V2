# scripts_exploracao_ML/conferir_borda_de_12_meses_do_orders_search.py
#
# Função Objetivo: DESCOBRIR, com 3 chamadas de 1 pedido ao GET /orders/search, como o Mercado Livre trata o dia da BORDA dos 12 meses: ele devolve o dia inteiro, só parte dele, ou nada?
#
# Contexto (12/10/2026): na coleta do ano (11/10/2025 a 11/10/2026), o 1º dia (11/10/2025) tem no banco 1 pedido criado às 03:45:38 que NENHUMA coleta recente releu (ele veio de uma coleta
# de produto de 10/10/2026, 22:12). O 1º pedido que a coleta do ano releu nesse dia foi às 06:05:04. O coletor pediu o dia a partir de 00:00. Duas explicações:
#   (A) o ML corta o dia mais antigo no meio (por exemplo por volta das 06:00): o pedido das 03:45 já não é devolvido. O banco o guarda porque a coleta de 10/10 ainda o via.
#   (B) o ML devolve o dia inteiro e a coleta do ano deixou escapar o pedido (a paginação, ver conferir_ordem_do_sort_do_orders_search.py). A coleta do ano teve 2 avisos e o texto de 1 se perdeu.
# O total que o ML devolve HOJE para esse dia, comparado com o banco, decide entre as duas.
#
# O QUE O SCRIPT FAZ (só leitura: SELECT no banco + 3 GET de 1 pedido cada; nada é gravado):
#   1) Calcula os dias de teste a partir de HOJE: B = a mesma data de 12 meses atrás (12/10/2025 em 12/10/2026); testa B − 1, B e B + 1 (o dia de controle, que deve vir inteiro).
#      O corte do ML anda 1 dia por dia: o dia que está cortado "agora" é B − 1 ou B, por isso o script olha os dois.
#   2) Para cada dia faz 1 chamada com from = D 00:00, to = D 23:00 (o dia inteiro, com a correção `fim − 1 hora`), limit=1: só interessa o paging.total.
#   3) Compara o total do ML com os pedidos do banco no dia: INTEIRO (igual), PARCIAL (o ML devolve menos), FORA (o ML devolve 0) ou MAIOR (o ML tem mais que o banco).
#   4) Num dia PARCIAL ou FORA, diz quantos pedidos do banco o ML não devolve e entre QUAIS 2 horários de criação o corte está (supondo que o ML corta só o começo do dia).
#
# COMO LER: o dia de controle (B + 1) TEM de vir INTEIRO; se não vier, o teste não vale. Se o dia B − 1 vier PARCIAL com 1 pedido a menos (o das 03:45:38), a explicação (A) está confirmada.
# Se vier INTEIRO, vale a (B): o ML devolve o pedido e foi a coleta que o perdeu. Se vier FORA (0), o corte já passou por esse dia (isto acontece depois da virada diária do corte): o teste do
# pedido das 03:45 não é mais possível, mas o dia B mostra onde o corte está hoje; rode de novo amanhã, antes da virada, se quiser a prova direta.
#
# RESULTADO (rodado em 12/10/2026 01:14): 11/10/2025 PARCIAL (ML 196 × banco 197; o pedido das 03:45:38 é cortado; o 1º que vem é o das 06:05:04), 12/10/2025 INTEIRO (203 = 203) e o controle
# 13/10/2025 INTEIRO (332 = 332): explicação (A) confirmada. Aplicado: FOLGA_DO_LIMITE_ML_DIAS = 1 em cobertura_vendas_ml.py. Falta medir a hora exata do corte e se ele anda no dia.
#
# REGRAS: nenhum dado de comprador é lido além do paging.total; o seller_id não vai para a tela nem para o JSON. O JSON é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → limit=1 de propósito: só o total interessa (1 chamada barata, não 1 página de 50). 3 chamadas ao todo, uma vez só: é uma calibração da conta, não cresce com o número de SKUs.
# * [EXPLICAÇÃO] → "Pedidos do banco no dia" = pedidos distintos com dia_venda = D (todos os status: a busca do vendedor também traz os cancelados).

import json
import os
import shutil
import sys
import time
from collections import defaultdict
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

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import requisicoes_enviadas_nesta_thread
from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_detalhes import _caminho_pasta_logs
from integracao_mercado_livre.servicos.cobertura_vendas_ml import MESES_DO_HISTORICO_ML, voltar_meses
from mercado_livre.models import VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                    # "MB" (Magazine) ou "SV" (Samvale)
DIA_DA_BORDA = None             # None = hoje − 12 meses (o script testa esse dia, o anterior e o seguinte). Ou date(2025, 10, 12) para fixar o B
PAUSA_ENTRE_CHAMADAS_S = 1      # silêncio entre as chamadas
# ========================================

EMPRESA = {"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA]
definir_empresa_ativa(EMPRESA)
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_borda_de_12_meses_do_orders_search_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def hora(instante):
    return "—" if instante is None else instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


def hora_do_dia(instante):
    return "—" if instante is None else instante.astimezone(FUSO).strftime("%H:%M:%S")


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


def mascarar(texto, user_id):
    texto = str(texto)[:300]
    return texto.replace(str(user_id), "***") if user_id else texto


# ======================================================== análise (funções puras) ========================================================

# Função Objetivo: Compara o total do ML com o do banco no dia: INTEIRO, PARCIAL, FORA, MAIOR ou SEM_TOTAL (a chamada falhou).
def classificar(total_ml, total_banco):
    if total_ml is None:
        return "SEM_TOTAL"
    if total_ml == total_banco:
        return "INTEIRO"
    if total_ml > total_banco:
        return "MAIOR"
    return "FORA" if total_ml == 0 else "PARCIAL"


# Função Objetivo: Se o ML devolve menos que o banco, SUPÕE que ele cortou só o começo do dia: os `faltam` pedidos mais antigos do banco não vêm mais. Devolve (último pedido cortado, primeiro que vem)
# pelo horário de criação: o corte fica entre os dois. `criados` = horários de criação dos pedidos do banco no dia.
def intervalo_do_corte(criados, faltam):
    ordenados = sorted(criados)
    if faltam <= 0 or faltam > len(ordenados):
        return None, None
    ultimo_cortado = ordenados[faltam - 1]
    primeiro_que_vem = ordenados[faltam] if faltam < len(ordenados) else None
    return ultimo_cortado, primeiro_que_vem


def montar_leitura(dias):
    """`dias` = lista de dicts na ordem [B-1, B, B+1] com: dia, total_banco, total_ml, estado, faltam, ultimo_cortado, primeiro_que_vem, primeiro_do_banco."""
    leitura = []
    anterior, borda, controle = dias
    if controle["estado"] == "INTEIRO":
        leitura.append(f"Controle: o dia {dia_curto(controle['dia'])} veio INTEIRO ({n(controle['total_ml'])} no ML = {n(controle['total_banco'])} no banco). O teste vale.")
    elif controle["estado"] == "SEM_TOTAL":
        leitura.append(f"Controle: a chamada do dia {dia_curto(controle['dia'])} falhou. Nada a concluir.")
        return leitura
    else:
        leitura.append(f"Controle: o dia {dia_curto(controle['dia'])} NÃO veio inteiro (ML {n(controle['total_ml'])}, banco {n(controle['total_banco'])}, estado {controle['estado']}). O teste é inconclusivo: "
                       f"o banco ou o ML diferem até no meio da janela.")
    for d in (anterior, borda):
        r = f"Dia {dia_curto(d['dia'])}: ML {n(d['total_ml']) if d['total_ml'] is not None else '—'} × banco {n(d['total_banco'])} → {d['estado']}."
        if d["estado"] == "INTEIRO":
            r += " O ML devolve o dia inteiro; este dia não está cortado."
        elif d["estado"] in ("PARCIAL", "FORA"):
            if d["estado"] == "FORA":
                r += " O ML não devolve NENHUM pedido deste dia: o corte já passou por ele."
            else:
                r += f" Faltam {n(d['faltam'])} pedido(s) do banco no ML."
                if d["ultimo_cortado"] is not None:
                    fim = f" e {hora_do_dia(d['primeiro_que_vem'])}" if d["primeiro_que_vem"] is not None else " e o fim do dia"
                    r += (f" Se o ML cortou só o começo do dia, o corte fica entre {hora_do_dia(d['ultimo_cortado'])}{fim} "
                          f"(o pedido mais antigo do banco é das {hora_do_dia(d['primeiro_do_banco'])}).")
        elif d["estado"] == "MAIOR":
            r += f" O ML tem {n(d['total_ml'] - d['total_banco'])} pedido(s) A MAIS que o banco neste dia: o banco está incompleto aqui (se for o dia da borda, o banco só tem o que alguma coleta já trouxe)."
        leitura.append(r)
    if controle["estado"] != "INTEIRO":
        leitura.append("Sem o dia de controle inteiro, NÃO conclua nada sobre a borda: repita o script mais tarde ou investigue por que o dia de controle não fecha.")
        return leitura
    if anterior["estado"] == "PARCIAL" or borda["estado"] == "PARCIAL":
        leitura.append("EXPLICAÇÃO (A) CONFIRMADA para o dia da borda: o ML corta o começo do dia mais antigo. O banco guarda pedidos que a coleta de ontem ainda via. Correção: FOLGA_DO_LIMITE_ML_DIAS = 1 "
                       "em cobertura_vendas_ml.py (o 1º dia coletado passa a vir inteiro e a tela mostra o aviso 'limite do ML') e tratar o 1º dia do banco como dia parcial nas contas de ritmo de venda.")
    elif anterior["estado"] == "FORA" or borda["estado"] == "FORA":
        leitura.append("O ML já cortou um dia inteiro da borda: o limite de 12 meses existe e anda 1 dia por dia. Mas a prova direta do pedido das 03:45:38 de 11/10/2025 não é mais possível hoje "
                       "(o dia saiu da janela do ML). Para ter essa prova, rode este script ANTES da virada do corte (de manhã cedo, antes das 06:00 de Brasília) olhando o dia que ainda está na borda.")
    elif anterior["estado"] == "INTEIRO" and borda["estado"] == "INTEIRO":
        leitura.append("Os dois dias da borda vieram INTEIROS: o ML devolve o dia de 12 meses atrás sem cortar. Então, se o pedido de 03:45:38 de 11/10/2025 não veio na coleta do ano, "
                       "a falha foi da coleta (provável: o 2º aviso da coleta do ano, cujo texto se perdeu). Reler o dia depois da correção do coletor confirma.")
    elif anterior["estado"] == "MAIOR" or borda["estado"] == "MAIOR":
        leitura.append("O ML tem mais pedidos do que o banco no dia da borda: o banco está incompleto ali. Reler o dia pelo coletor (conta toda) completa.")
    return leitura


# ======================================================== as chamadas ========================================================

def chamar(api, dia):
    inicio = datetime(dia.year, dia.month, dia.day, 0, tzinfo=FUSO)
    fim_do_filtro = datetime(dia.year, dia.month, dia.day, 23, tzinfo=FUSO)
    antes = requisicoes_enviadas_nesta_thread()
    pacote = api.buscar_pedidos(inicio, fim_do_filtro, offset=0, limite=1)
    resultado = {"requisicoes_http": requisicoes_enviadas_nesta_thread() - antes, "http": pacote.http, "erro": None if pacote.erro is None else mascarar(pacote.erro, getattr(api, "_user_id", None)), "total": None}
    if pacote.erro is None and pacote.http == 200 and isinstance(pacote.dados, dict):
        resultado["total"] = (pacote.dados.get("paging") or {}).get("total")
    return resultado


def ler_banco(dias):
    por_dia = defaultdict(dict)
    for order_id, dia, criado in VendaItemMercadoLivre.objects.filter(dia_venda__in=dias).values_list("order_id", "dia_venda", "criado_em_ml").iterator(chunk_size=5000):
        por_dia[dia][order_id] = criado.astimezone(FUSO)
    return por_dia


def main():
    agora = datetime.now(FUSO)
    borda = DIA_DA_BORDA or voltar_meses(agora.date(), MESES_DO_HISTORICO_ML)
    dias_do_teste = [borda - timedelta(days=1), borda, borda + timedelta(days=1)]
    console.print(f"\n[bold]Borda de {MESES_DO_HISTORICO_ML} meses do /orders/search[/] · conta {CONTA} · 3 chamadas de 1 pedido (GET) · nada é gravado · rodando em {hora(agora)}\n")
    por_dia = ler_banco(dias_do_teste)
    api = ApiMercadoLivre(pasta_logs=_caminho_pasta_logs(EMPRESA), empresa=EMPRESA)

    resultados = []
    try:
        for i, dia in enumerate(dias_do_teste):
            if i:
                time.sleep(PAUSA_ENTRE_CHAMADAS_S)
            resultados.append(chamar(api, dia))
    except ErroAutenticacaoAPI:
        console.print("[bold red]O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi concluído.[/]")
        return

    dias = []
    for dia, r in zip(dias_do_teste, resultados):
        criados = list(por_dia.get(dia, {}).values())
        total_banco = len(criados)
        estado = classificar(r["total"], total_banco)
        faltam = total_banco - r["total"] if r["total"] is not None and r["total"] < total_banco else 0
        ultimo_cortado, primeiro_que_vem = intervalo_do_corte(criados, faltam) if faltam else (None, None)
        dias.append({"dia": dia, "total_banco": total_banco, "total_ml": r["total"], "estado": estado, "faltam": faltam, "ultimo_cortado": ultimo_cortado, "primeiro_que_vem": primeiro_que_vem,
                     "primeiro_do_banco": min(criados) if criados else None, "requisicoes_http": r["requisicoes_http"], "http": r["http"], "erro": r["erro"]})

    console.rule("[bold]O que o ML devolve em cada dia")
    papeis = ["B − 1 (dia anterior à borda)", "B (a mesma data de 12 meses atrás)", "B + 1 (controle)"]
    tabela("Total do ML (from = 00:00, to = 23:00) × pedidos do banco no dia", ["Dia", "Papel", "HTTP", "Chamadas", "ML", "Banco", "Estado", "Pedido mais antigo do banco"],
           [(dia_curto(d["dia"]), papel, str(d["http"]), n(d["requisicoes_http"]), "—" if d["total_ml"] is None else n(d["total_ml"]), n(d["total_banco"]), d["estado"], hora_do_dia(d["primeiro_do_banco"]))
            for d, papel in zip(dias, papeis)], a_direita=(2, 3, 4, 5))
    for d in dias:
        if d["erro"]:
            console.print(f"[red]Erro no dia {dia_curto(d['dia'])}: {t(d['erro'])}[/]")

    console.rule("[bold]Leitura")
    leitura = montar_leitura(dias)
    for linha in leitura:
        console.print(f"• {t(linha)}")

    saida = {"conta": CONTA, "rodou_em": agora.isoformat(), "dia_da_borda": borda.isoformat(),
             "dias": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()} for d in dias], "leitura": leitura}
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem dado de comprador e sem seller_id.")


if __name__ == "__main__":
    main()
