# scripts_exploracao_ML/foto_do_banco_de_vendas_ml.py
#
# Função Objetivo: tirar uma "FOTO" da tabela de vendas do Mercado Livre (VendaItemMercadoLivre) ANTES de recoletar o ano com o código corrigido
# (modo FOTO) e, depois da recoleta, COMPARAR essa foto com o banco de agora (modo COMPARAR). A recoleta com "Reler" grava por cima dos mesmos
# pedidos (upsert por order_id + posição); sem uma foto de antes, não dá para saber o que ela mudou. Com a foto dá para ver, pedido a pedido:
#   1) PEDIDOS NOVOS que já existiam no ML quando a foto foi tirada e que a coleta antiga NÃO tinha gravado (a perda por empate de `date_closed`
#      na fronteira da página, o "anunciou 202, vieram 201"). O script ainda mede quantos deles fecharam no MESMO segundo que outro pedido e
#      compara com a taxa de empate dos pedidos em geral: se a deles for bem maior, o empate combina com a perda.
#   2) VENDAS NOVAS do dia da foto em diante (não são perda; é só o tempo passando).
#   3) PEDIDOS QUE MUDARAM DE SITUAÇÃO (ex.: paid -> cancelled): cancelamentos que só a releitura pegou.
#   4) LINHAS NÃO TOCADAS pela recoleta: pedidos do período que o ML não devolveu desta vez (o `atualizado_em` continua anterior ao início da
#      recoleta). Esperado hoje: o pedido de 11/10/2025 03:45:38 (o ML corta o começo do dia mais antigo da janela de 12 meses).
#   5) DIAS COM DIFERENÇA: dia a dia, quantos pedidos tinha antes e quantos tem agora.
#
# COMO USAR (2 passos):
#   1) MODO = "FOTO"     -> rode ANTES de recoletar o ano. Grava foto_do_banco_de_vendas_ml_<CONTA>_<data>_<hora>.json (nunca sobrescreve uma foto antiga).
#   2) MODO = "COMPARAR" -> rode DEPOIS que a recoleta do ano terminar. Usa a foto mais recente (ou ARQUIVO_DA_FOTO) e acha sozinho a recoleta:
#      a coleta de PERÍODO concluída depois da foto, a que tem mais dias.
#
# REGRAS: SÓ LEITURA e SÓ BANCO. Nenhuma chamada ao Mercado Livre, nada é gravado no banco. Só os JSONs de saída são gravados nesta pasta.
# Os JSONs não têm dado de comprador (o banco nem guarda).
#
# * [EXPLICAÇÃO] → Horários mostrados no horário de Brasília. O banco guarda em UTC (3 h à frente).
# * [EXPLICAÇÃO] → A foto guarda UMA linha por item de pedido (order_id, posição, dia da venda, situação, quantidade): alguns MB para 1 ano da conta.
# * [EXPLICAÇÃO] → A comparação NUNCA mexe na foto. A saída da comparação (comparacao_com_a_foto_do_banco_de_vendas_ml_<CONTA>.json) é refeita a cada rodada.

import json
import os
import shutil
import sys
from collections import Counter, defaultdict, namedtuple
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

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from mercado_livre.models import ExecucaoColetaVendasMercadoLivre, VendaItemMercadoLivre

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                                       # "MB" (Magazine) ou "SV" (Samvale): decide o banco
MODO = "COMPARAR"                                  # "FOTO" = tira e grava a foto de agora (ANTES de recoletar) | "COMPARAR" = compara a foto com o banco de agora (DEPOIS)
ARQUIVO_DA_FOTO = None                             # só no COMPARAR: None = a foto mais recente da conta; ou o nome exato do arquivo da foto
LINHAS_NA_LISTA = 15                               # linhas de exemplo na tela
# ========================================

if MODO not in ("FOTO", "COMPARAR"):
    raise SystemExit('MODO precisa ser "FOTO" ou "COMPARAR".')

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

FUSO = ZoneInfo("America/Sao_Paulo")
PASTA = Path(__file__).resolve().parent
PREFIXO_DA_FOTO = f"foto_do_banco_de_vendas_ml_{CONTA}_"
CAMINHO_SAIDA_COMPARACAO = PASTA / f"comparacao_com_a_foto_do_banco_de_vendas_ml_{CONTA}.json"

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))

CAMPOS = ("order_id", "posicao", "dia_venda", "status", "quantidade", "criado_em_ml", "fechado_em_ml", "mlb", "seller_sku", "atualizado_em")
Linha = namedtuple("Linha", CAMPOS)
COLUNAS_DA_FOTO = ("order_id", "posicao", "dia_venda", "status", "quantidade")


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def com_sinal(valor):
    return "0" if valor == 0 else f"{valor:+,}".replace(",", ".")


def percentual(parte, todo):
    return "—" if not todo else f"{parte / todo * 100:.1f}%".replace(".", ",")


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


def carregar_linhas():
    # * [EXPLICAÇÃO] → 1 leitura só, na memória (cerca de 85 mil linhas de poucos campos para 1 ano da conta).
    consulta = VendaItemMercadoLivre.objects.all()
    return [Linha(*valores) for valores in consulta.values_list(*CAMPOS).iterator(chunk_size=5000)]


def resumir(linhas):
    """Totais e contagem por dia (pedidos distintos, itens e unidades)."""
    pedidos_por_dia, itens_por_dia, unidades_por_dia = defaultdict(set), Counter(), Counter()
    for l in linhas:
        pedidos_por_dia[l.dia_venda].add(l.order_id)
        itens_por_dia[l.dia_venda] += 1
        unidades_por_dia[l.dia_venda] += l.quantidade or 0
    dias = sorted(pedidos_por_dia)
    por_dia = {d.isoformat(): {"pedidos": len(pedidos_por_dia[d]), "itens": itens_por_dia[d], "unidades": unidades_por_dia[d]} for d in dias}
    resumo = {"itens": len(linhas), "pedidos": len({l.order_id for l in linhas}), "unidades": sum(l.quantidade or 0 for l in linhas), "dias": len(dias),
              "primeiro_dia": dias[0].isoformat() if dias else None, "ultimo_dia": dias[-1].isoformat() if dias else None}
    return resumo, por_dia


# ======================================================== modo FOTO ========================================================

def fazer_a_foto():
    # * [EXPLICAÇÃO] → A hora da foto é marcada ANTES de ler o banco: pedido criado depois dela nunca conta como "perdido pela coleta antiga".
    tirada_em = datetime.now(tz=FUSO)
    linhas = carregar_linhas()
    if not linhas:
        console.print("[bold red]A tabela de vendas está vazia: nada para fotografar.[/]")
        return
    resumo, por_dia = resumir(linhas)
    foto = {
        "conta": CONTA, "tirada_em": tirada_em.isoformat(), "tirada_em_brasilia": hora(tirada_em), "resumo": resumo, "por_dia": por_dia,
        "colunas_das_linhas": list(COLUNAS_DA_FOTO),
        "linhas": [[l.order_id, l.posicao, l.dia_venda.isoformat(), l.status, l.quantidade] for l in sorted(linhas, key=lambda x: (x.order_id, x.posicao))],
    }
    caminho = PASTA / f"{PREFIXO_DA_FOTO}{tirada_em:%Y%m%d_%H%M%S}.json"
    caminho.write_text(json.dumps(foto, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    tabela("Foto do banco de vendas (tirada agora)", ["O quê", "Valor"], [
        ("Hora da foto (Brasília)", hora(tirada_em)),
        ("Itens (linhas da tabela)", n(resumo["itens"])),
        ("Pedidos distintos", n(resumo["pedidos"])),
        ("Unidades vendidas", n(resumo["unidades"])),
        ("Dias com venda", n(resumo["dias"])),
        ("Primeiro e último dia", f"{dia_curto(date.fromisoformat(resumo['primeiro_dia']))} a {dia_curto(date.fromisoformat(resumo['ultimo_dia']))}"),
        ("Arquivo da foto", caminho.name),
        ("Tamanho", f"{caminho.stat().st_size / 1_000_000:.1f} MB".replace(".", ",")),
    ], a_direita=(1,))
    console.print("Foto salva. PRÓXIMO PASSO: recolete o ano na tela e, quando terminar, troque MODO para \"COMPARAR\" e rode este script de novo.")


# ======================================================== modo COMPARAR ========================================================

def carregar_a_foto():
    if ARQUIVO_DA_FOTO:
        caminho = PASTA / ARQUIVO_DA_FOTO
        if not caminho.exists():
            raise SystemExit(f"ARQUIVO_DA_FOTO não existe: {caminho.name}")
    else:
        fotos = sorted(PASTA.glob(f"{PREFIXO_DA_FOTO}*.json"))
        if not fotos:
            raise SystemExit(f"Nenhuma foto da conta {CONTA} nesta pasta. Rode antes com MODO = \"FOTO\".")
        caminho = fotos[-1]
    return caminho, json.loads(caminho.read_text(encoding="utf-8"))


def achar_a_recoleta(tirada_em):
    """A coleta de PERÍODO concluída depois da foto com mais dias (a recoleta do ano). None se ainda não houve."""
    E = ExecucaoColetaVendasMercadoLivre
    candidatas = list(E.objects.filter(tipo=E.Tipo.PERIODO, status=E.Status.CONCLUIDA, concluido_em__isnull=False, iniciado_em__gt=tirada_em))
    return max(candidatas, key=lambda e: (e.dias_total, e.iniciado_em)) if candidatas else None


def exemplo(l):
    return {"order_id": l.order_id, "posicao": l.posicao, "dia_venda": l.dia_venda.isoformat(), "criado_em": hora(l.criado_em_ml), "fechado_em": hora(l.fechado_em_ml),
            "status": l.status, "mlb": l.mlb, "seller_sku": l.seller_sku, "atualizado_em": hora(l.atualizado_em)}


def comparar(foto, linhas, recoleta):
    """Toda a conta da comparação, sem tocar no banco nem na tela: recebe a foto (dict), as linhas de agora e a recoleta (ou None)."""
    tirada_em = datetime.fromisoformat(foto["tirada_em"])
    dia_da_foto = tirada_em.astimezone(FUSO).date()
    antes = {(o, p): (date.fromisoformat(dia), status, qtd) for o, p, dia, status, qtd in foto["linhas"]}
    agora = {(l.order_id, l.posicao): l for l in linhas}

    chaves_novas = sorted(k for k in agora if k not in antes)
    chaves_sumidas = sorted(k for k in antes if k not in agora)

    # * [EXPLICAÇÃO] → "Perdido pela coleta antiga" = pedido de um dia ANTERIOR ao da foto, criado antes da foto, que o banco não tinha.
    #                  Pedido do dia da foto em diante fica de fora: aquele dia ainda estava em andamento (pode ser só venda nova).
    perdidos = [agora[k] for k in chaves_novas if agora[k].dia_venda < dia_da_foto and agora[k].criado_em_ml is not None and agora[k].criado_em_ml <= tirada_em]
    do_dia_da_foto_em_diante = [agora[k] for k in chaves_novas if agora[k].dia_venda >= dia_da_foto]
    outras_novas = len(chaves_novas) - len(perdidos) - len(do_dia_da_foto_em_diante)

    mudou_status, mudou_dia, mudou_quantidade = Counter(), 0, 0
    for chave, (dia, status, quantidade) in antes.items():
        l = agora.get(chave)
        if l is None:
            continue
        if l.status != status:
            mudou_status[(status, l.status)] += 1
        if l.dia_venda != dia:
            mudou_dia += 1
        if (l.quantidade or 0) != (quantidade or 0):
            mudou_quantidade += 1

    pedidos_antes_por_dia, pedidos_agora_por_dia = defaultdict(set), defaultdict(set)
    for (order_id, _), (dia, _, _) in antes.items():
        pedidos_antes_por_dia[dia].add(order_id)
    for l in linhas:
        pedidos_agora_por_dia[l.dia_venda].add(l.order_id)
    dias_com_diferenca = []
    for dia in sorted(set(pedidos_antes_por_dia) | set(pedidos_agora_por_dia)):
        a, b = len(pedidos_antes_por_dia.get(dia, ())), len(pedidos_agora_por_dia.get(dia, ()))
        if a != b:
            dias_com_diferenca.append((dia, a, b))

    # * [EXPLICAÇÃO] → Empate: 2 ou mais pedidos fechados no MESMO segundo (o ML ordena por `date_closed` com precisão de 1 s). Mede-se a taxa nos
    #                  pedidos perdidos e nos pedidos em geral: a perda por empate na fronteira da página só combina se a taxa dos perdidos for bem maior.
    fechamento_por_pedido = {}
    for l in linhas:
        if l.fechado_em_ml is not None:
            fechamento_por_pedido[l.order_id] = l.fechado_em_ml.replace(microsecond=0)
    por_segundo = Counter(fechamento_por_pedido.values())
    perdidos_com_fechamento = [l.order_id for l in perdidos if l.order_id in fechamento_por_pedido]
    empate = {
        "pedidos_com_fechamento": len(fechamento_por_pedido),
        "empatados_em_geral": sum(1 for f in fechamento_por_pedido.values() if por_segundo[f] >= 2),
        "perdidos_com_fechamento": len(set(perdidos_com_fechamento)),
        "perdidos_empatados": len({o for o in perdidos_com_fechamento if por_segundo[fechamento_por_pedido[o]] >= 2}),
    }

    nao_tocadas, fora_da_janela_por_dia = [], Counter()
    if recoleta is not None:
        for l in linhas:
            if recoleta.data_de <= l.dia_venda <= recoleta.data_ate:
                if l.atualizado_em < recoleta.iniciado_em:
                    nao_tocadas.append(l)
            else:
                fora_da_janela_por_dia[l.dia_venda] += 1

    return {
        "tirada_em": tirada_em, "dia_da_foto": dia_da_foto,
        "itens_antes": len(antes), "itens_agora": len(agora),
        "pedidos_antes": len({o for (o, _) in antes}), "pedidos_agora": len({o for (o, _) in agora}),
        "unidades_antes": sum((q or 0) for (_, _, q) in antes.values()), "unidades_agora": sum((l.quantidade or 0) for l in linhas),
        "novas": len(chaves_novas), "perdidos": perdidos, "do_dia_da_foto_em_diante": do_dia_da_foto_em_diante, "outras_novas": outras_novas,
        "sumidas": chaves_sumidas, "mudou_status": mudou_status, "mudou_dia": mudou_dia, "mudou_quantidade": mudou_quantidade,
        "dias_com_diferenca": dias_com_diferenca, "empate": empate,
        "nao_tocadas": nao_tocadas, "fora_da_janela_por_dia": fora_da_janela_por_dia,
        "recoleta_pulou_dias": recoleta is not None and recoleta.dias_a_coletar < recoleta.dias_total,
    }


def montar_leitura(r, recoleta):
    leitura = []
    leitura.append(f"O banco tinha {n(r['itens_antes'])} itens ({n(r['pedidos_antes'])} pedidos) na foto e tem {n(r['itens_agora'])} agora "
                   f"({n(r['pedidos_agora'])} pedidos; itens {com_sinal(r['itens_agora'] - r['itens_antes'])}).")
    if recoleta is None:
        leitura.append("Ainda NÃO há coleta de período concluída depois da foto: recolete o ano e rode de novo. O que aparece abaixo é só o que mudou no banco desde a foto.")
    else:
        leitura.append(f"Recoleta encontrada: {hora(recoleta.iniciado_em)}, {dia_curto(recoleta.data_de)} a {dia_curto(recoleta.data_ate)}, "
                       f"{n(recoleta.dias_a_coletar)} de {n(recoleta.dias_total)} dias lidos, {n(recoleta.chamadas)} chamadas, {n(recoleta.pedidos_lidos)} pedidos lidos.")
        if r["recoleta_pulou_dias"]:
            leitura.append("ATENÇÃO: a recoleta PULOU dias (sem \"Reler tudo\"): as linhas desses dias não foram tocadas por escolha, não por falha do ML.")
    if r["sumidas"]:
        leitura.append(f"ATENÇÃO: {n(len(r['sumidas']))} linha(s) que estavam na foto NÃO existem mais no banco. A recoleta só grava por cima: alguém apagou?")

    perdidos, e = r["perdidos"], r["empate"]
    if perdidos:
        leitura.append(f"{n(len(perdidos))} pedido(s) de dias anteriores ao da foto já existiam no ML quando a foto foi tirada e NÃO estavam no banco: é o que a coleta antiga "
                       f"não tinha gravado. Desses, {n(e['perdidos_empatados'])} de {n(e['perdidos_com_fechamento'])} ({percentual(e['perdidos_empatados'], e['perdidos_com_fechamento'])}) "
                       f"fecharam no MESMO segundo que outro pedido, contra {percentual(e['empatados_em_geral'], e['pedidos_com_fechamento'])} dos pedidos em geral "
                       f"(se o primeiro número for bem maior, o empate de `date_closed` combina com a perda).")
    else:
        leitura.append("Nenhum pedido de dia anterior ao da foto apareceu de novo: a coleta antiga não tinha perdido nada que a nova achasse.")
    leitura.append(f"{n(len(r['do_dia_da_foto_em_diante']))} pedido(s) novos são do dia da foto em diante (vendas novas; não são perda).")
    if r["outras_novas"]:
        leitura.append(f"{n(r['outras_novas'])} pedido(s) novos não se encaixam em nenhum grupo acima (dia anterior ao da foto mas criados depois dela): confira a hora da foto.")
    total_status = sum(r["mudou_status"].values())
    if total_status:
        transicoes = ", ".join(f"{de} -> {para}: {n(q)}" for (de, para), q in r["mudou_status"].most_common())
        leitura.append(f"{n(total_status)} linha(s) mudaram de situação desde a foto ({transicoes}).")
    else:
        leitura.append("Nenhuma linha mudou de situação desde a foto.")
    if r["mudou_dia"] or r["mudou_quantidade"]:
        leitura.append(f"ATENÇÃO: {n(r['mudou_dia'])} linha(s) mudaram de DIA e {n(r['mudou_quantidade'])} mudaram de QUANTIDADE (esperado: 0 nas duas).")
    if recoleta is not None:
        leitura.append(f"{n(len(r['nao_tocadas']))} linha(s) do período da recoleta NÃO foram tocadas por ela: o ML não devolveu esses pedidos desta vez "
                       f"(esperado hoje: 1, o de 11/10/2025 03:45:38).")
        if r["fora_da_janela_por_dia"]:
            leitura.append(f"{n(sum(r['fora_da_janela_por_dia'].values()))} linha(s) ficam em dias que a recoleta nem pediu (antes do 1º dia dela; é a folga da borda de 12 meses).")
    return leitura


def mostrar_comparacao(r, recoleta):
    tabela("Banco: foto × agora", ["O quê", "Foto", "Agora", "Dif."], [
        ("Itens (linhas)", n(r["itens_antes"]), n(r["itens_agora"]), com_sinal(r["itens_agora"] - r["itens_antes"])),
        ("Pedidos distintos", n(r["pedidos_antes"]), n(r["pedidos_agora"]), com_sinal(r["pedidos_agora"] - r["pedidos_antes"])),
        ("Unidades", n(r["unidades_antes"]), n(r["unidades_agora"]), com_sinal(r["unidades_agora"] - r["unidades_antes"])),
    ], a_direita=(1, 2, 3))

    if r["perdidos"]:
        por_dia = Counter(l.dia_venda for l in r["perdidos"])
        tabela(f"Dias em que a recoleta achou pedidos que a coleta antiga não tinha (até {LINHAS_NA_LISTA} dias)", ["Dia", "Pedidos achados"],
               [(dia_curto(d), n(q)) for d, q in sorted(por_dia.items(), key=lambda x: (-x[1], x[0]))[:LINHAS_NA_LISTA]], a_direita=(1,))
        ordenados = sorted(r["perdidos"], key=lambda l: (l.fechado_em_ml is None, l.fechado_em_ml, l.order_id))[:LINHAS_NA_LISTA]
        tabela(f"Exemplos de pedidos achados (até {LINHAS_NA_LISTA}, por hora de fechamento)", ["Pedido", "Criado em", "Fechado em", "Situação", "MLB"],
               [(l.order_id, hora(l.criado_em_ml), hora(l.fechado_em_ml), l.status, l.mlb) for l in ordenados])

    if r["dias_com_diferenca"]:
        tabela(f"Dias com número de pedidos diferente (até {LINHAS_NA_LISTA} de {n(len(r['dias_com_diferenca']))})", ["Dia", "Foto", "Agora", "Dif."],
               [(dia_curto(d), n(a), n(b), com_sinal(b - a)) for d, a, b in r["dias_com_diferenca"][:LINHAS_NA_LISTA]], a_direita=(1, 2, 3))
    else:
        console.print("Nenhum dia mudou de número de pedidos.")

    if r["nao_tocadas"]:
        ordenadas = sorted(r["nao_tocadas"], key=lambda l: (l.dia_venda, l.order_id))[:LINHAS_NA_LISTA]
        tabela(f"Linhas que a recoleta NÃO tocou (até {LINHAS_NA_LISTA} de {n(len(r['nao_tocadas']))})", ["Pedido", "Dia", "Criado em", "Situação", "MLB", "SKU", "Última gravação"],
               [(l.order_id, dia_curto(l.dia_venda), hora(l.criado_em_ml), l.status, l.mlb, l.seller_sku or "—", hora(l.atualizado_em)) for l in ordenadas])
    elif recoleta is not None:
        console.print("Nenhuma linha do período ficou sem ser tocada pela recoleta.")


def fazer_a_comparacao():
    caminho_da_foto, foto = carregar_a_foto()
    tirada_em = datetime.fromisoformat(foto["tirada_em"])
    fotos_existentes = len(list(PASTA.glob(f"{PREFIXO_DA_FOTO}*.json")))
    console.print(f"Foto usada: {t(caminho_da_foto.name)} (tirada em {t(hora(tirada_em))}; {n(foto['resumo']['itens'])} itens). Fotos desta conta na pasta: {fotos_existentes}.\n")
    linhas = carregar_linhas()
    recoleta = achar_a_recoleta(tirada_em)
    r = comparar(foto, linhas, recoleta)
    mostrar_comparacao(r, recoleta)
    console.rule("[bold]Leitura")
    leitura = montar_leitura(r, recoleta)
    for linha in leitura:
        console.print(f"• {t(linha)}")

    saida = {
        "conta": CONTA, "foto": caminho_da_foto.name, "foto_tirada_em": hora(tirada_em),
        "recoleta": None if recoleta is None else {"inicio": hora(recoleta.iniciado_em), "de": recoleta.data_de.isoformat(), "ate": recoleta.data_ate.isoformat(),
                                                   "dias_total": recoleta.dias_total, "dias_a_coletar": recoleta.dias_a_coletar, "chamadas": recoleta.chamadas,
                                                   "pedidos_lidos": recoleta.pedidos_lidos},
        "totais": {"itens_antes": r["itens_antes"], "itens_agora": r["itens_agora"], "pedidos_antes": r["pedidos_antes"], "pedidos_agora": r["pedidos_agora"],
                   "unidades_antes": r["unidades_antes"], "unidades_agora": r["unidades_agora"]},
        "pedidos_achados_que_a_coleta_antiga_nao_tinha": [exemplo(l) for l in sorted(r["perdidos"], key=lambda l: (l.dia_venda, l.order_id))],
        "empate": r["empate"],
        "novas_do_dia_da_foto_em_diante": len(r["do_dia_da_foto_em_diante"]), "outras_novas": r["outras_novas"],
        "linhas_que_sumiram_do_banco": [list(k) for k in r["sumidas"]],
        "mudou_situacao": [{"de": de, "para": para, "linhas": q} for (de, para), q in r["mudou_status"].most_common()],
        "mudou_dia": r["mudou_dia"], "mudou_quantidade": r["mudou_quantidade"],
        "dias_com_diferenca": [{"dia": d.isoformat(), "antes": a, "agora": b, "dif": b - a} for d, a, b in r["dias_com_diferenca"]],
        "linhas_nao_tocadas_pela_recoleta": [exemplo(l) for l in sorted(r["nao_tocadas"], key=lambda l: (l.dia_venda, l.order_id))],
        "linhas_em_dias_que_a_recoleta_nao_pediu": {d.isoformat(): q for d, q in sorted(r["fora_da_janela_por_dia"].items())},
        "leitura": leitura,
    }
    CAMINHO_SAIDA_COMPARACAO.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA_COMPARACAO.name}. Sem chamada à API e sem dado de comprador (o banco não guarda).")


def main():
    console.print(f"\n[bold]Foto do banco de vendas do ML[/] · conta {CONTA} · modo {MODO} · só leitura (SELECT no banco; nenhuma chamada à API)\n")
    if MODO == "FOTO":
        fazer_a_foto()
    else:
        fazer_a_comparacao()


if __name__ == "__main__":
    main()
