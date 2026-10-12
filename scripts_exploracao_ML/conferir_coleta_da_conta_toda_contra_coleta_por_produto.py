# scripts_exploracao_ML/conferir_coleta_da_conta_toda_contra_coleta_por_produto.py
#
# Função Objetivo: CONFERIR, só com o que já está no banco, se os DOIS caminhos de coleta de pedidos do histórico de vendas concordam entre si:
#   - CAMINHO POR PRODUTO ("Atualizar produto" / "Reler tudo"): pergunta ao Mercado Livre os pedidos de cada MLB do produto, um por um;
#   - CAMINHO DA CONTA TODA ("Coletar período da conta"): pergunta os pedidos de todos os SKUs, dia a dia.
# Em 11/10/2026 o SKU de teste foi coletado pelo caminho por produto (16.876 pedidos, 364 chamadas) e, 10 minutos depois, a conta toda foi coletada pelo caminho da
# conta (84.510 pedidos, 1.870 chamadas). As duas coletas gravam nas MESMAS linhas (a chave é pedido + posição), então reler não duplica; mas dá para saber qual coleta
# mexeu em cada linha pela coluna `atualizado_em` (o instante da última gravação).
#
# O script responde 4 perguntas, nesta ordem:
#   1) A RÉGUA: qual foi a coleta da conta toda (início, fim, chamadas, pedidos). Vem da tabela de execuções.
#   2) O SKU DE TESTE: o banco tem os mesmos 16.876 pedidos que a coleta por produto leu? Algum pedido do SKU está em MLB que NÃO é do produto (o caminho por produto nunca veria)?
#   3) A CONTA TODA: algum pedido gravado por coletas ANTERIORES não foi visto de novo pela coleta da conta toda? (Seria um pedido que só o caminho por produto enxerga:
#      por exemplo, a busca por vendedor não devolver pedido cancelado, pergunta em aberto no vault.) E a soma bate com os 84.510 lidos?
#   4) OS AVISOS GUARDADOS: lista os avisos de coletas feitas depois de 12/10/2026 (antes disso o texto dos avisos se perdia; só o 1º aparecia na mensagem).
#
# REGRAS: SÓ LEITURA e SÓ BANCO. Nenhuma chamada ao Mercado Livre, nada é gravado no banco. O JSON de saída (sem dado de comprador: o banco nem guarda) é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → Cada linha cai em UMA de 3 faixas, comparando `atualizado_em` com o início e o fim da coleta da conta toda:
#                    ANTES   = gravada antes dela começar e NUNCA mais mexida: só o caminho por produto (ou coleta antiga) a viu. É a faixa que importa: o que cair aqui é pedido
#                              que a coleta da conta toda NÃO enxergou.
#                    DURANTE = mexida enquanto a coleta da conta toda rodava: ela viu o pedido.
#                    DEPOIS  = mexida depois que ela terminou (ex.: o "Atualizar dia" de 08/07, outro "Atualizar produto"). É AMBÍGUA: pode ter sido vista pela coleta da conta
#                              toda e regravada depois, ou não. Por isso o ideal é rodar este script logo depois da coleta da conta, antes de outras coletas.
# * [EXPLICAÇÃO] → Pedido é contado por order_id distinto. Nesta conta cada pedido tem 1 item (84.510 pedidos = 84.510 itens), então linhas e pedidos coincidem; o script mostra os dois.

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

from django.db.models import Sum
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from gestao_vendas.funcoes_auxiliares.vendas_ml import carregar_produto
from mercado_livre.models import ColetaVendasMercadoLivre, ExecucaoColetaVendasMercadoLivre, VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                                       # "MB" (Magazine) ou "SV" (Samvale): decide o banco
SKU = "F7908050719121.001"                         # o SKU que foi coletado pelo caminho por produto
PEDIDOS_DA_COLETA_POR_PRODUTO = 16876              # o que a mensagem da tela disse na coleta por produto (11/10/2026, 364 chamadas)
INICIO_DA_COLETA_DA_CONTA = None                   # None = lê da tabela de execuções (a coleta de período concluída mais longa). Ou datetime(2026, 10, 11, 23, 17, 22) em horário de Brasília
DIAS_PARA_TRAS = 365                               # só vale se INICIO_DA_COLETA_DA_CONTA for informado: a janela é (hoje − 365 dias) até hoje
LINHAS_NA_LISTA = 25                               # linhas de exemplo na tela
LINHAS_NO_JSON = 500                               # linhas de exemplo no JSON
AVISOS_NA_LISTA = 15                               # coletas com avisos guardados que aparecem na tela
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_conferencia_conta_toda_contra_produto_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")
MARCADOR_DE_AVISOS = "Avisos desta coleta"         # o mesmo título que _mensagem_para_registro (coletar_vendas_ml.py) escreve no texto da coleta

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def com_sinal(valor):
    return "0" if valor == 0 else f"{valor:+,}".replace(",", ".")


def hora(instante):
    return instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


def tabela(titulo, colunas, linhas, a_direita=()):
    console.print(f"[bold]{t(titulo)}[/]")
    tab = Table(box=box.SIMPLE_HEAVY, header_style="bold", pad_edge=False)
    for i, coluna in enumerate(colunas):
        tab.add_column(coluna, justify="right" if i in a_direita else "left", overflow="fold")
    for linha in linhas:
        tab.add_row(*[t(c) for c in linha])
    console.print(tab)


def contar(consulta):
    return {
        "linhas": consulta.count(),
        "pedidos": consulta.values("order_id").distinct().count(),
        "unidades": consulta.aggregate(u=Sum("quantidade"))["u"] or 0,
    }


def tres_faixas(consulta, coleta):
    antes = consulta.filter(atualizado_em__lt=coleta["inicio"])
    durante = consulta.filter(atualizado_em__gte=coleta["inicio"], atualizado_em__lte=coleta["fim"])
    depois = consulta.filter(atualizado_em__gt=coleta["fim"])
    return {"total": contar(consulta), "antes": contar(antes), "durante": contar(durante), "depois": contar(depois)}, antes


# ======================================================== 1) a régua: a coleta da conta toda ========================================================

def ler_a_coleta_da_conta():
    if INICIO_DA_COLETA_DA_CONTA is not None:
        agora = datetime.now(FUSO)
        return {"origem": "informada no script", "inicio": INICIO_DA_COLETA_DA_CONTA.replace(tzinfo=FUSO), "fim": agora,
                "de": agora.date() - timedelta(days=DIAS_PARA_TRAS), "ate": agora.date(), "chamadas": None, "pedidos": None, "trechos": None}
    E = ExecucaoColetaVendasMercadoLivre
    execucao = E.objects.filter(tipo=E.Tipo.PERIODO, status=E.Status.CONCLUIDA).order_by("-dias_total", "-iniciado_em").first()
    if execucao is None:
        return None
    return {"origem": "tabela de execuções (a coleta de período concluída mais longa)", "inicio": execucao.iniciado_em.astimezone(FUSO),
            "fim": execucao.concluido_em.astimezone(FUSO), "de": execucao.data_de, "ate": execucao.data_ate, "chamadas": execucao.chamadas,
            "pedidos": execucao.pedidos_lidos, "trechos": execucao.trechos}


def mostrar_a_coleta_da_conta(coleta):
    console.rule("[bold]1) A régua: a coleta da conta toda")
    tabela("Coleta usada como régua", ["Campo", "Valor"], [
        ("Origem", coleta["origem"]),
        ("Início", hora(coleta["inicio"])),
        ("Fim", hora(coleta["fim"])),
        ("Datas de venda lidas", f"{coleta['de']:%d/%m/%Y} a {coleta['ate']:%d/%m/%Y}"),
        ("Pedidos lidos", "—" if coleta["pedidos"] is None else n(coleta["pedidos"])),
        ("Chamadas ao Mercado Livre", "—" if coleta["chamadas"] is None else n(coleta["chamadas"])),
        ("Dias lidos (trechos)", "—" if coleta["trechos"] is None else n(coleta["trechos"])),
    ])


# ======================================================== 2) o SKU de teste ========================================================

def conferir_o_sku(base, coleta):
    console.rule(f"[bold]2) O SKU de teste ({t(SKU)})")
    produto = carregar_produto(SKU)
    if produto is None:
        console.print(f"[bold red]SKU {t(SKU)} não encontrado em Produto. Esta parte foi pulada.[/]")
        return None
    mlbs = sorted(produto["mlbs"])
    console.print(f"O produto tem {len(mlbs)} anúncios (MLBs) ligados a ele. O caminho por produto lê SÓ esses.")

    do_produto = base.filter(mlb__in=mlbs)
    faixas, antes = tres_faixas(do_produto, coleta)
    pedidos_agora = faixas["total"]["pedidos"]
    diferenca = pedidos_agora - PEDIDOS_DA_COLETA_POR_PRODUTO
    tabela("Pedidos do SKU, nos MLBs do produto, na janela da coleta", ["O quê", "Pedidos", "Linhas", "Unidades"], [
        ("No banco agora", n(pedidos_agora), n(faixas["total"]["linhas"]), n(faixas["total"]["unidades"])),
        ("A coleta por produto leu (mensagem da tela)", n(PEDIDOS_DA_COLETA_POR_PRODUTO), "—", "—"),
        ("Diferença (banco − coleta por produto)", com_sinal(diferenca), "—", "—"),
    ], a_direita=(1, 2, 3))
    tabela("Quem mexeu nessas linhas por último", ["Faixa", "Pedidos", "Linhas", "O que significa"], [
        ("ANTES da coleta da conta", n(faixas["antes"]["pedidos"]), n(faixas["antes"]["linhas"]), "só o caminho por produto viu (a coleta da conta NÃO)"),
        ("DURANTE a coleta da conta", n(faixas["durante"]["pedidos"]), n(faixas["durante"]["linhas"]), "a coleta da conta viu"),
        ("DEPOIS da coleta da conta", n(faixas["depois"]["pedidos"]), n(faixas["depois"]["linhas"]), "ambíguo (regravado por outra coleta depois)"),
    ], a_direita=(1, 2))

    # Por MLB: total de pedidos e quantos ficaram na faixa ANTES.
    pedidos_por_mlb, antes_por_mlb = defaultdict(set), defaultdict(set)
    for order_id, mlb in do_produto.values_list("order_id", "mlb"):
        pedidos_por_mlb[mlb].add(order_id)
    for order_id, mlb in antes.values_list("order_id", "mlb"):
        antes_por_mlb[mlb].add(order_id)
    por_mlb = sorted(pedidos_por_mlb, key=lambda m: (-len(antes_por_mlb[m]), -len(pedidos_por_mlb[m])))
    tabela("Por MLB (os de mais pedidos primeiro; os com pedidos só-ANTES sobem)", ["MLB", "Pedidos", "Só ANTES"],
           [(m, n(len(pedidos_por_mlb[m])), n(len(antes_por_mlb[m]))) for m in por_mlb[:15]], a_direita=(1, 2))

    # Vendas do SKU em MLB que NÃO é do produto: o caminho por produto nunca lê isso.
    fora = base.filter(seller_sku=SKU).exclude(mlb__in=mlbs)
    fora_total = contar(fora)
    por_mlb_fora = Counter()
    for order_id, mlb in fora.values_list("order_id", "mlb"):
        por_mlb_fora[mlb] += 1
    if fora_total["pedidos"]:
        tabela("Pedidos com este SKU em MLBs FORA do produto (só a coleta da conta toda enxerga)", ["MLB", "Pedidos"],
               [(m, n(q)) for m, q in por_mlb_fora.most_common(10)], a_direita=(1,))
    else:
        console.print("Pedidos com este SKU em MLBs fora do produto: nenhum.")
    return {"mlbs_do_produto": mlbs, "faixas": faixas, "diferenca_para_a_coleta_por_produto": diferenca,
            "so_antes_por_mlb": {m: len(antes_por_mlb[m]) for m in por_mlb if antes_por_mlb[m]}, "fora_do_produto": fora_total,
            "fora_do_produto_por_mlb": dict(por_mlb_fora)}


# ======================================================== 3) a conta toda ========================================================

def conferir_a_conta_toda(base, coleta):
    console.rule("[bold]3) A conta toda: algum pedido ficou só com o caminho por produto?")
    faixas, antes = tres_faixas(base, coleta)
    total = faixas["total"]
    tabela("Todos os pedidos da janela, por quem mexeu por último", ["Faixa", "Pedidos", "Linhas", "Unidades"], [
        ("Total no banco (janela)", n(total["pedidos"]), n(total["linhas"]), n(total["unidades"])),
        ("ANTES da coleta da conta (nunca mais vistos)", n(faixas["antes"]["pedidos"]), n(faixas["antes"]["linhas"]), n(faixas["antes"]["unidades"])),
        ("DURANTE a coleta da conta", n(faixas["durante"]["pedidos"]), n(faixas["durante"]["linhas"]), n(faixas["durante"]["unidades"])),
        ("DEPOIS da coleta da conta", n(faixas["depois"]["pedidos"]), n(faixas["depois"]["linhas"]), n(faixas["depois"]["unidades"])),
    ], a_direita=(1, 2, 3))

    soma = None
    if coleta["pedidos"] is not None:
        soma = total["pedidos"] - faixas["antes"]["pedidos"]
        tabela("A conta fecha?", ["O quê", "Pedidos"], [
            ("A coleta da conta leu (tabela de execuções)", n(coleta["pedidos"])),
            ("No banco, fora a faixa ANTES (total − ANTES)", n(soma)),
            ("Diferença", com_sinal(soma - coleta["pedidos"])),
        ], a_direita=(1,))
        console.print("Diferença pequena e positiva é esperada: pedidos NOVOS que entraram depois da coleta (o do dia 08/07 que faltou, vendas de hoje à noite).")

    detalhe = {"por_status": {}, "por_mes": {}, "por_sku": {}, "por_mlb": {}, "exemplos": [], "primeiro_gravado_em": None, "ultimo_gravado_em": None}
    if faixas["antes"]["linhas"]:
        linhas = list(antes.order_by("dia_venda", "order_id").values_list("order_id", "dia_venda", "mlb", "seller_sku", "status", "atualizado_em"))
        por_status = Counter(l[4] for l in linhas)
        por_mes = Counter(f"{l[1]:%Y-%m}" for l in linhas)
        por_sku = Counter(l[3] or "(sem SKU)" for l in linhas)
        por_mlb = Counter(l[2] for l in linhas)
        tabela("Os pedidos da faixa ANTES: por situação do pedido", ["Status", "Pedidos"], [(s, n(q)) for s, q in por_status.most_common()], a_direita=(1,))
        tabela("Os pedidos da faixa ANTES: por mês da venda", ["Mês", "Pedidos"], [(m, n(q)) for m, q in sorted(por_mes.items())], a_direita=(1,))
        tabela("Os pedidos da faixa ANTES: SKUs e MLBs mais frequentes", ["SKU", "Pedidos", "MLB", "Pedidos"],
               [(a[0], n(a[1]), b[0], n(b[1])) for a, b in zip(por_sku.most_common(8), por_mlb.most_common(8))], a_direita=(1, 3))
        tabela(f"Exemplos da faixa ANTES (os {LINHAS_NA_LISTA} mais antigos; horário de Brasília)", ["Pedido", "Dia da venda", "MLB", "SKU", "Status", "Última gravação"],
               [(str(l[0]), f"{l[1]:%d/%m/%Y}", l[2], l[3] or "(sem SKU)", l[4], hora(l[5])) for l in linhas[:LINHAS_NA_LISTA]])
        detalhe = {"por_status": dict(por_status), "por_mes": dict(sorted(por_mes.items())), "por_sku": dict(por_sku.most_common(30)),
                   "por_mlb": dict(por_mlb.most_common(30)),
                   "exemplos": [{"order_id": l[0], "dia_venda": l[1].isoformat(), "mlb": l[2], "seller_sku": l[3], "status": l[4], "atualizado_em": l[5].isoformat()}
                                for l in linhas[:LINHAS_NO_JSON]],
                   "primeiro_gravado_em": min(l[5] for l in linhas).isoformat(), "ultimo_gravado_em": max(l[5] for l in linhas).isoformat()}
        console.print(f"Essas linhas foram gravadas entre {hora(min(l[5] for l in linhas))} e {hora(max(l[5] for l in linhas))}.")
    else:
        console.print("[green]Nenhum pedido ficou só na faixa ANTES: tudo que as coletas anteriores gravaram foi visto de novo pela coleta da conta toda.[/]")
    return {"faixas": faixas, "conta_fecha_soma_no_banco": soma, "faixa_antes_detalhe": detalhe}


# ======================================================== 4) os avisos guardados ========================================================

def mostrar_avisos_guardados():
    console.rule("[bold]4) Avisos guardados nas coletas")
    coletas = list(ColetaVendasMercadoLivre.objects.filter(mensagem__contains=MARCADOR_DE_AVISOS).order_by("-iniciado_em")[:AVISOS_NA_LISTA])
    if not coletas:
        console.print("Nenhuma coleta com avisos guardados ainda. (O texto completo dos avisos só passou a ser gravado depois de 12/10/2026; antes disso só o 1º aparecia na mensagem.)")
        return {"coletas_com_aviso": 0, "coletas": []}
    saida = []
    for coleta in coletas:
        alvo = coleta.mlb or (f"{coleta.data_de:%d/%m/%Y}" if coleta.data_de == coleta.data_ate else f"{coleta.data_de:%d/%m/%Y} a {coleta.data_ate:%d/%m/%Y}")
        avisos = [l[2:] for l in coleta.mensagem.split(MARCADOR_DE_AVISOS, 1)[1].splitlines() if l.startswith("- ")]
        console.print(f"[bold]{hora(coleta.iniciado_em)}[/] · {t(coleta.get_escopo_display())} · {t(alvo)} · {len(avisos)} aviso(s)")
        for aviso in avisos:
            console.print(f"   • {t(aviso)}")
        saida.append({"iniciado_em": coleta.iniciado_em.isoformat(), "escopo": coleta.escopo, "alvo": alvo, "avisos": avisos})
    return {"coletas_com_aviso": len(coletas), "coletas": saida}


# ======================================================== leitura em linguagem simples ========================================================

def montar_leitura(coleta, sku, conta):
    linhas = []
    antes = conta["faixas"]["antes"]["pedidos"]
    total = conta["faixas"]["total"]["pedidos"]
    if antes == 0:
        linhas.append("CONTA TODA × PRODUTO CONCORDAM: todo pedido que as coletas anteriores gravaram foi visto de novo pela coleta da conta toda. Nenhum pedido ficou só no caminho por produto.")
    else:
        status = conta["faixa_antes_detalhe"]["por_status"]
        cancelados = status.get("cancelled", 0)
        linhas.append(f"ATENÇÃO: {n(antes)} de {n(total)} pedidos do banco NÃO foram vistos pela coleta da conta toda (só um caminho anterior os gravou).")
        if cancelados:
            linhas.append(f"   {n(cancelados)} desses são 'cancelled'. Se for a maioria, a busca por vendedor (coleta da conta) pode NÃO estar devolvendo pedidos cancelados, e o caminho por produto devolve: é a pergunta em aberto do vault sobre cancelados.")
        if cancelados < antes:
            linhas.append(f"   {n(antes - cancelados)} NÃO são cancelados: veja os meses, SKUs e MLBs acima para achar o padrão (dia específico, anúncio específico, janela da borda de 12 meses).")
    if sku is not None:
        d = sku["diferenca_para_a_coleta_por_produto"]
        if d == 0:
            linhas.append("SKU DE TESTE: o banco tem exatamente os pedidos que a coleta por produto leu. A coleta da conta toda não achou nenhum pedido a mais nos MLBs do produto.")
        elif d > 0:
            linhas.append(f"SKU DE TESTE: o banco tem {n(d)} pedidos A MAIS que a coleta por produto leu. Alguns podem ser vendas novas entre as duas coletas (uns 10 minutos); se forem mais que isso, o caminho por produto perdeu pedidos.")
        else:
            linhas.append(f"SKU DE TESTE: o banco tem {n(-d)} pedidos A MENOS que a coleta por produto leu: investigar (a mensagem da tela soma pedidos por trecho).")
        if sku["fora_do_produto"]["pedidos"]:
            linhas.append(f"   O SKU tem {n(sku['fora_do_produto']['pedidos'])} pedidos em MLBs que NÃO estão ligados ao produto no cadastro: só a coleta da conta toda enxerga essas vendas.")
        so_antes = sku["faixas"]["antes"]["pedidos"]
        if so_antes:
            linhas.append(f"   {n(so_antes)} pedidos do SKU só foram vistos pelo caminho por produto (veja a tabela por MLB).")
    return linhas


def main():
    console.print(f"\n[bold]Conferência: coleta da conta toda × coleta por produto[/] · conta {CONTA} · SKU {t(SKU)} · só leitura (SELECT no banco; nenhuma chamada à API)\n")
    coleta = ler_a_coleta_da_conta()
    if coleta is None:
        console.print("[bold red]Não achei nenhuma coleta de PERÍODO concluída na tabela de execuções. Rode o 'Coletar período da conta' ou informe INICIO_DA_COLETA_DA_CONTA no topo do script.[/]")
        return
    mostrar_a_coleta_da_conta(coleta)
    base = VendaItemMercadoLivre.objects.filter(dia_venda__gte=coleta["de"], dia_venda__lte=coleta["ate"])
    sku = conferir_o_sku(base, coleta)
    conta = conferir_a_conta_toda(base, coleta)
    avisos = mostrar_avisos_guardados()
    console.rule("[bold]Leitura")
    leitura = montar_leitura(coleta, sku, conta)
    for linha in leitura:
        if linha.startswith("   "):
            console.print(f"    {t(linha.strip())}")
        else:
            console.print(f"• {t(linha)}")
    saida = {"conta": CONTA, "sku": SKU, "coleta_da_conta": {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in coleta.items()},
             "sku_de_teste": sku, "conta_toda": conta, "avisos_guardados": avisos, "leitura": leitura}
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem chamada à API e sem dado de comprador (o banco não guarda).")


if __name__ == "__main__":
    main()
