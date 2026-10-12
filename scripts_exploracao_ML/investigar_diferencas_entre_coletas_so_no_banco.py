# scripts_exploracao_ML/investigar_diferencas_entre_coletas_so_no_banco.py
#
# Função Objetivo: SEPARAR, só com o que já está no banco, as explicações possíveis para 3 diferenças que a conferência de 12/10/2026
# (conferir_coleta_da_conta_toda_contra_coleta_por_produto.py) deixou SEM resposta:
#   A) A CONTA NÃO FECHA: a coleta da conta toda de 1 ano leu 84.510 pedidos, mas o banco tem só 83.437 pedidos distintos tocados por ela (−1.073).
#   B) O SKU DE TESTE TEM −7: a coleta por produto leu 16.876 pedidos e o banco tem 16.869 nos MLBs do produto.
#   C) 121 VENDAS DO SKU FICAM EM 3 MLBs QUE NÃO ESTÃO LIGADOS AO PRODUTO (104 / 16 / 1): por que não estão ligados?
# E ainda olha o único pedido que só o caminho por produto tinha (de 11/10/2025, o 1º dia da janela de 12 meses).
#
# O script NÃO afirma a causa: ele mede, cada teste descarta ou mantém uma hipótese, e a "Leitura" no fim diz o que COMBINA e o que NÃO explica.
#   1) A conta de CADA coleta de período fecha? (a do ano e a da semana). A da semana é um teste pequeno e limpo: se ela fecha e a do ano não, o
#      problema mora nos dias mais antigos; se as duas têm a mesma proporção, é algo sistemático (borda do filtro de datas).
#   2) Teste da HORA 0: o filtro de data do ML IGNORA minutos, segundos e milissegundos (medido em 10/10/2026, ver o cabeçalho de api_mercado_livre/pedidos_ml.py).
#      Então "até 00:00 do dia seguinte" vira "até 00:59:59 do dia seguinte": todo pedido criado entre 00:00 e 00:59 seria lido 2 vezes, na busca do
#      dia anterior e na do próprio dia (o banco junta por pedido+posição e guarda 1, mas a contagem de "lidos" sobe). A seção mostra quantos são.
#   3) Linhas tocadas pela coleta do ano que têm dia_venda FORA da janela (fuso ou borda do dia desencontrados, que também faria a conta não fechar).
#   4) Perfil por dia: dia sem nenhum pedido, os menores e os maiores dias, e o 1º dia da janela por faixa (ANTES/DURANTE/DEPOIS) e por hora.
#   5) O SKU, trecho a trecho: cada trecho da coleta por produto guardou quantos pedidos leu; aqui cada um é comparado com o banco (MLB + datas do trecho).
#   6) Os MLBs do SKU que NÃO estão ligados ao produto: existem na tabela de anúncios? As variações deles estão ligadas a qual SKU (ou a nenhum)?
#   7) A HIPÓTESE DA HORA 0, CONFERIDA NÚMERO A NÚMERO (acrescentada em 12/10/2026): para cada coleta de período e para cada TRECHO da coleta por produto,
#      o script PREVÊ a diferença (pedidos da hora 0 lidos 2 vezes, menos os pedidos que a coleta não releu) e compara com a diferença observada.
#      Se a previsão bater em (quase) todos os trechos, a hipótese está confirmada só com o banco, sem nenhuma chamada.
#
# DEPOIS DA CORREÇÃO (12/10/2026): o coletor passou a mandar `fim − 1 hora` ao ML, então as coletas feitas DEPOIS de a correção subir no servidor NÃO repetem mais a hora 0.
# Preencha CORRECAO_DA_HORA_0_APLICADA_EM com o momento em que subiu: as coletas que começaram depois disso são previstas SEM repetição (previsto = só os não relidos).
# Numa coleta nova do ano, a conta deve fechar (sobra 0); sobra negativa = pedido que o ML anunciou e não entregou (o aviso da coleta diz a janela).
#
# REGRAS: SÓ LEITURA e SÓ BANCO. Nenhuma chamada ao Mercado Livre, nada é gravado no banco. O JSON de saída (sem dado de comprador: o banco nem guarda)
# é sobrescrito a cada execução.
#
# * [EXPLICAÇÃO] → Faixas, como no script anterior: ANTES = gravada antes da coleta do ano começar e nunca mais mexida; DURANTE = mexida enquanto ela
#                  rodava; DEPOIS = mexida depois que ela terminou. Pedido é contado por order_id distinto (nesta conta cada pedido tem 1 item).
# * [EXPLICAÇÃO] → Horários mostrados no horário de Brasília. O banco guarda em UTC (3 h à frente).

import json
import os
import shutil
import sys
from collections import Counter, defaultdict, namedtuple
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
from gestao_vendas.funcoes_auxiliares.vendas_ml import carregar_produto
from mercado_livre.models import (
    AnuncioMercadoLivre, ColetaVendasMercadoLivre, ExecucaoColetaVendasMercadoLivre, VariacaoAnuncioMercadoLivre, VendaItemMercadoLivre,
)

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                                       # "MB" (Magazine) ou "SV" (Samvale): decide o banco
SKU = "F7908050719121.001"                         # o SKU que foi coletado pelo caminho por produto
PEDIDOS_DA_COLETA_POR_PRODUTO = 16876              # o que a mensagem da tela disse na coleta por produto (11/10/2026, 364 chamadas)
MINUTOS_DO_LOTE_POR_PRODUTO = 20                   # os trechos de 1 clique de "Atualizar produto" começam todos dentro desta janela, a contar do mais novo
LINHAS_NA_LISTA = 15                               # linhas de exemplo na tela
CORRECAO_DA_HORA_0_APLICADA_EM = (2026, 10, 12, 1, 40)    # (ano, mês, dia, hora, minuto) em Brasília: a correção `fim − 1 hora` subiu em 12/10/2026 às 01:40 (runserver reiniciado às 01:39:46). None = ainda NÃO subiu
# ========================================

definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default (Magazine): para CONTA="SV" leria a empresa errada.

CAMINHO_SAIDA = Path(__file__).resolve().parent / f"exploracao_diferencas_entre_coletas_so_no_banco_{CONTA}.json"
FUSO = ZoneInfo("America/Sao_Paulo")

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(110, 24)).columns - 1, 40))

CAMPOS = ("order_id", "posicao", "mlb", "seller_sku", "dia_venda", "criado_em_ml", "atualizado_em", "status")
Linha = namedtuple("Linha", CAMPOS)


def t(texto):
    return escape(str(texto))


def n(valor):
    return f"{valor:,}".replace(",", ".")


def com_sinal(valor):
    return "0" if valor == 0 else f"{valor:+,}".replace(",", ".")


def percentual(parte, todo):
    return "—" if not todo else f"{parte / todo * 100:+.3f}%".replace(".", ",")


def hora(instante):
    return instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M:%S")


def hora_do_dia(instante):
    return instante.astimezone(FUSO).strftime("%H:%M:%S")


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


def carregar_linhas(de, ate):
    # * [EXPLICAÇÃO] → 1 leitura só, na memória (cerca de 85 mil linhas de poucos campos), com 3 dias de folga nas pontas para enxergar desencontro de borda.
    consulta = VendaItemMercadoLivre.objects.filter(dia_venda__gte=de - timedelta(days=3), dia_venda__lte=ate + timedelta(days=3))
    return [Linha(*valores) for valores in consulta.values_list(*CAMPOS).iterator(chunk_size=5000)]


def na_janela(linha, de, ate):
    return de <= linha.dia_venda <= ate


# Função Objetivo: A coleta que COMEÇOU neste instante repete a hora 0 do dia seguinte? Sim, se começou antes de a correção `fim − 1 hora` subir (ou se ainda não subiu).
def repete_a_hora_0(iniciado_em):
    if CORRECAO_DA_HORA_0_APLICADA_EM is None:
        return True
    return iniciado_em < datetime(*CORRECAO_DA_HORA_0_APLICADA_EM, tzinfo=FUSO)


# ======================================================== 1) a conta de cada coleta de período ========================================================

def carregar_execucoes_de_periodo():
    E = ExecucaoColetaVendasMercadoLivre
    return list(E.objects.filter(tipo=E.Tipo.PERIODO, status=E.Status.CONCLUIDA, concluido_em__isnull=False).order_by("-iniciado_em"))


def pedidos_que_existiam(linhas, ex):
    """(mínimo, máximo) de pedidos que a coleta PODIA ter lido. O dia de hoje é lido primeiro (início da coleta); os outros dias já estavam completos."""
    dia_da_execucao = ex.iniciado_em.astimezone(FUSO).date()
    minimo, maximo = set(), set()
    for l in linhas:
        if not na_janela(l, ex.data_de, ex.data_ate):
            continue
        if l.dia_venda == ex.data_ate == dia_da_execucao:
            if l.criado_em_ml <= ex.iniciado_em:
                minimo.add(l.order_id)
            if l.criado_em_ml <= ex.concluido_em:
                maximo.add(l.order_id)
        else:
            minimo.add(l.order_id)
            maximo.add(l.order_id)
    return len(minimo), len(maximo)


def conferir_cada_coleta_de_periodo(execucoes, linhas):
    console.rule("[bold]1) A conta de cada coleta de período fecha com o banco?")
    saida, tab = [], []
    for ex in execucoes:
        minimo, maximo = pedidos_que_existiam(linhas, ex)
        diferenca = minimo - ex.pedidos_lidos
        saida.append({"inicio": ex.iniciado_em.isoformat(), "de": ex.data_de.isoformat(), "ate": ex.data_ate.isoformat(), "dias_total": ex.dias_total,
                      "dias_a_coletar": ex.dias_a_coletar, "chamadas": ex.chamadas, "pedidos_lidos": ex.pedidos_lidos, "no_banco_minimo": minimo,
                      "no_banco_maximo": maximo, "diferenca": diferenca})
        tab.append((hora(ex.iniciado_em), f"{dia_curto(ex.data_de)} a {dia_curto(ex.data_ate)}", f"{n(ex.dias_a_coletar)} de {n(ex.dias_total)}", n(ex.chamadas),
                    n(ex.pedidos_lidos), n(minimo), com_sinal(diferenca), percentual(diferenca, ex.pedidos_lidos)))
    tabela("Pedidos que a coleta leu × pedidos que existem no banco para o mesmo período (criados até o início da coleta)",
           ["Coleta (início)", "Datas de venda", "Dias lidos de total", "Chamadas", "Lidos", "No banco", "Dif.", "Dif. %"], tab, a_direita=(3, 4, 5, 6, 7))
    console.print("Dif. negativa = a coleta LEU mais pedidos do que existem no banco (o mesmo pedido contado 2 vezes, ou gravado com outro dia). Dif. positiva = o banco tem mais.")
    return saida


# ======================================================== 2) teste da hora 0 ========================================================

def pedidos_da_hora_0_repetidos(linhas, ex):
    """Pedidos criados entre 00:00 e 00:59 (Brasília) de um dia DEPOIS do 1º da janela: a busca do dia anterior já os traz (o filtro de data do ML ignora
    minutos), então seriam lidos 2 vezes. Só conta quem já existia quando a coleta começou (o dia de hoje é lido primeiro)."""
    ids = set()
    if not repete_a_hora_0(ex.iniciado_em):
        return ids
    for l in linhas:
        if ex.data_de < l.dia_venda <= ex.data_ate + timedelta(days=1) and l.criado_em_ml <= ex.iniciado_em and l.criado_em_ml.astimezone(FUSO).hour == 0:
            ids.add(l.order_id)
    return ids


def teste_da_hora_0(linhas, ex, diferenca):
    console.rule("[bold]2) Teste da hora 0: a busca do dia traz também a 1ª hora do dia seguinte?")
    por_pedido = {}
    for l in linhas:
        if na_janela(l, ex.data_de, ex.data_ate):
            por_pedido[l.order_id] = l.criado_em_ml.astimezone(FUSO)
    na_hora_0 = sum(1 for c in por_pedido.values() if c.hour == 0)
    exatos = sum(1 for c in por_pedido.values() if c.hour == 0 and c.minute == 0 and c.second == 0 and c.microsecond == 0)
    com_ms = sum(1 for c in por_pedido.values() if c.microsecond)
    repetidos = len(pedidos_da_hora_0_repetidos(linhas, ex))
    tabela("Pedidos da janela da coleta do ano, pela hora de criação (Brasília)", ["O quê", "Pedidos"], [
        ("Pedidos distintos na janela", n(len(por_pedido))),
        ("Com milissegundos diferentes de zero na hora de criação", n(com_ms)),
        ("Criados na hora 0 (00:00:00 a 00:59:59)", n(na_hora_0)),
        ("  dos quais EXATAMENTE às 00:00:00.000", n(exatos)),
        ("Criados na hora 0 de um dia depois do 1º da janela (lidos 2 vezes, se a hipótese vale)", n(repetidos)),
        ("Diferença da conta do ano (banco − lido), para comparar", com_sinal(diferenca)),
    ], a_direita=(1,))
    console.print("O filtro de data do ML ignora minutos e segundos: 'até 00:00' vira 'até 00:59:59'. Compare os 2 últimos números (a seção 7 faz a conta completa).")
    return {"pedidos_na_janela": len(por_pedido), "com_milissegundos": com_ms, "na_hora_0": na_hora_0, "exatamente_meia_noite": exatos,
            "repetidos_se_a_hipotese_vale": repetidos, "diferenca_da_conta": diferenca}


# ======================================================== 3) linhas tocadas pela coleta do ano fora da janela ========================================================

def linhas_tocadas_fora_da_janela(ex):
    console.rule("[bold]3) Linhas tocadas pela coleta do ano com dia da venda FORA da janela")
    tocadas = VendaItemMercadoLivre.objects.filter(atualizado_em__gte=ex.iniciado_em, atualizado_em__lte=ex.concluido_em)
    fora = tocadas.exclude(dia_venda__gte=ex.data_de, dia_venda__lte=ex.data_ate)
    total_durante = tocadas.values("order_id").distinct().count()
    n_fora = fora.values("order_id").distinct().count()
    depois = VendaItemMercadoLivre.objects.filter(dia_venda__gte=ex.data_de, dia_venda__lte=ex.data_ate, atualizado_em__gt=ex.concluido_em).values("order_id").distinct().count()
    durante_na_janela = total_durante - n_fora
    por_dia = Counter(fora.values_list("dia_venda", flat=True))
    tabela("Pedidos gravados pela coleta do ano", ["O quê", "Pedidos"], [
        ("Gravados DURANTE a coleta (qualquer dia de venda)", n(total_durante)),
        ("  dos quais com dia da venda FORA de " + f"{dia_curto(ex.data_de)} a {dia_curto(ex.data_ate)}", n(n_fora)),
        ("Gravados durante a coleta, DENTRO da janela", n(durante_na_janela)),
        ("Regravados DEPOIS da coleta, dentro da janela (ex.: o 'Atualizar dia')", n(depois)),
        ("Soma: o que a coleta pode ter tocado", n(durante_na_janela + depois)),
        ("A coleta leu (tabela de execuções)", n(ex.pedidos_lidos)),
        ("Lido − soma", com_sinal(ex.pedidos_lidos - durante_na_janela - depois)),
    ], a_direita=(1,))
    console.print("Os regravados DEPOIS podem não ter sido lidos por esta coleta; por isso 'Lido − soma' é um limite, não uma medida exata.")
    if por_dia:
        tabela("Dias de venda fora da janela (mais frequentes)", ["Dia da venda", "Linhas"], [(dia_curto(d), n(q)) for d, q in por_dia.most_common(10)], a_direita=(1,))
    else:
        console.print("Nenhuma linha gravada pela coleta tem dia da venda fora da janela.")
    return {"gravados_durante": total_durante, "fora_da_janela": n_fora, "durante_na_janela": durante_na_janela, "regravados_depois_na_janela": depois,
            "lido_menos_soma": ex.pedidos_lidos - durante_na_janela - depois, "dias_fora": {dia_curto(d): q for d, q in por_dia.most_common(10)}}


# ======================================================== 4) perfil por dia e bordas ========================================================

def faixa_da_linha(l, ex):
    if l.atualizado_em < ex.iniciado_em:
        return "ANTES"
    return "DURANTE" if l.atualizado_em <= ex.concluido_em else "DEPOIS"


def perfil_por_dia_e_bordas(linhas, ex):
    console.rule("[bold]4) Perfil por dia e as bordas da janela")
    por_dia = defaultdict(set)
    for l in linhas:
        if na_janela(l, ex.data_de, ex.data_ate):
            por_dia[l.dia_venda].add(l.order_id)
    dias = [ex.data_de + timedelta(days=i) for i in range((ex.data_ate - ex.data_de).days + 1)]
    contagem = {d: len(por_dia.get(d, ())) for d in dias}
    sem_pedido = [d for d in dias if contagem[d] == 0]
    miolo = dias[1:-1]
    menores = sorted(miolo, key=lambda d: (contagem[d], d))[:8]
    maiores = sorted(miolo, key=lambda d: (-contagem[d], d))[:8]
    mediana = sorted(contagem[d] for d in miolo)[len(miolo) // 2] if miolo else 0
    console.print(f"Dias na janela: {n(len(dias))} · dias sem nenhum pedido: {n(len(sem_pedido))} · mediana de pedidos por dia (sem as 2 pontas): {n(mediana)}")
    if sem_pedido:
        console.print("Dias sem pedido: " + ", ".join(dia_curto(d) for d in sem_pedido[:20]) + (" …" if len(sem_pedido) > 20 else ""))
    tabela("Os 8 menores dias (sem as pontas)", ["Dia", "Pedidos"], [(dia_curto(d), n(contagem[d])) for d in menores], a_direita=(1,))
    tabela("Os 8 maiores dias (sem as pontas)", ["Dia", "Pedidos"], [(dia_curto(d), n(contagem[d])) for d in maiores], a_direita=(1,))
    tabela("As pontas da janela", ["Dia", "Pedidos no banco"], [(dia_curto(dias[0]), n(contagem[dias[0]])), (dia_curto(dias[-1]), n(contagem[dias[-1]]))], a_direita=(1,))

    # O 1º dia da janela, por faixa de gravação: o dia da borda dos 12 meses do ML.
    primeiro = [l for l in linhas if l.dia_venda == ex.data_de]
    por_faixa = defaultdict(list)
    for l in primeiro:
        por_faixa[faixa_da_linha(l, ex)].append(l)
    linhas_da_faixa = []
    for faixa in ("ANTES", "DURANTE", "DEPOIS"):
        ls = por_faixa.get(faixa, [])
        if ls:
            horas = sorted(l.criado_em_ml.astimezone(FUSO) for l in ls)
            linhas_da_faixa.append((faixa, n(len({l.order_id for l in ls})), hora_do_dia(horas[0]), hora_do_dia(horas[-1])))
        else:
            linhas_da_faixa.append((faixa, "0", "—", "—"))
    tabela(f"O 1º dia da janela ({dia_curto(ex.data_de)}) por faixa: horas de criação dos pedidos (Brasília)", ["Faixa", "Pedidos", "Criado mais cedo", "Criado mais tarde"],
           linhas_da_faixa, a_direita=(1,))

    # Todos os pedidos da faixa ANTES na janela (os "só o outro caminho viu").
    antes = sorted((l for l in linhas if na_janela(l, ex.data_de, ex.data_ate) and faixa_da_linha(l, ex) == "ANTES"), key=lambda l: (l.dia_venda, l.order_id))
    if antes:
        tabela(f"Pedidos da faixa ANTES na janela ({n(len(antes))}; mostrando até {LINHAS_NA_LISTA})", ["Pedido", "Criado em (Brasília)", "MLB", "SKU", "Status", "Última gravação"],
               [(str(l.order_id), hora(l.criado_em_ml), l.mlb, l.seller_sku or "(sem SKU)", l.status, hora(l.atualizado_em)) for l in antes[:LINHAS_NA_LISTA]])
    else:
        console.print("[green]Nenhum pedido da janela ficou na faixa ANTES.[/]")
    return {"dias": len(dias), "dias_sem_pedido": [d.isoformat() for d in sem_pedido], "mediana_por_dia": mediana,
            "menores": {d.isoformat(): contagem[d] for d in menores}, "maiores": {d.isoformat(): contagem[d] for d in maiores},
            "primeiro_dia": {"dia": ex.data_de.isoformat(), "faixas": [{"faixa": a, "pedidos": b, "mais_cedo": c, "mais_tarde": d} for a, b, c, d in linhas_da_faixa]},
            "faixa_antes": [{"order_id": l.order_id, "criado_em": l.criado_em_ml.astimezone(FUSO).isoformat(), "mlb": l.mlb, "seller_sku": l.seller_sku, "status": l.status,
                             "atualizado_em": l.atualizado_em.isoformat()} for l in antes[:LINHAS_NA_LISTA]]}


# ======================================================== 5) o SKU, trecho a trecho ========================================================

def ler_lote_da_coleta_por_produto():
    C = ColetaVendasMercadoLivre
    todas = list(C.objects.filter(escopo=C.Escopo.MLB, sku=SKU, status=C.Status.CONCLUIDA).order_by("-iniciado_em"))
    if not todas:
        return []
    corte = todas[0].iniciado_em - timedelta(minutes=MINUTOS_DO_LOTE_POR_PRODUTO)
    return [c for c in todas if c.iniciado_em >= corte]


def conferir_trechos_do_sku(linhas, lote):
    console.rule(f"[bold]5) O SKU {t(SKU)}, trecho a trecho")
    if not lote:
        console.print("[bold red]Nenhuma coleta por produto (escopo MLB, com este SKU) encontrada. Esta parte foi pulada.[/]")
        return None
    pedidos = defaultdict(lambda: defaultdict(set))
    for l in linhas:
        pedidos[l.mlb][l.dia_venda].add(l.order_id)

    def no_banco(mlb, de, ate):
        return sum(len(ids) for d, ids in pedidos.get(mlb, {}).items() if de <= d <= ate)

    linhas_da_tabela, saida = [], []
    soma_lidos = soma_banco = soma_chamadas = 0
    for c in sorted(lote, key=lambda c: (c.mlb, c.data_de)):
        banco = no_banco(c.mlb, c.data_de, c.data_ate)
        soma_lidos += c.pedidos_lidos
        soma_banco += banco
        soma_chamadas += c.chamadas
        saida.append({"mlb": c.mlb, "de": c.data_de.isoformat(), "ate": c.data_ate.isoformat(), "chamadas": c.chamadas, "lidos": c.pedidos_lidos, "no_banco": banco,
                      "diferenca": banco - c.pedidos_lidos})
        linhas_da_tabela.append((c.mlb, f"{dia_curto(c.data_de)} a {dia_curto(c.data_ate)}", n(c.chamadas), n(c.pedidos_lidos), n(banco), com_sinal(banco - c.pedidos_lidos)))
    com_diferenca = [l for l, s in zip(linhas_da_tabela, saida) if s["diferenca"] != 0]
    console.print(f"Trechos desta coleta por produto: {n(len(lote))} · chamadas: {n(soma_chamadas)} · lidos: {n(soma_lidos)} (a mensagem da tela disse {n(PEDIDOS_DA_COLETA_POR_PRODUTO)})")
    if soma_lidos != PEDIDOS_DA_COLETA_POR_PRODUTO:
        console.print(f"[yellow]Atenção: a soma dos trechos ({n(soma_lidos)}) não é a da mensagem da tela ({n(PEDIDOS_DA_COLETA_POR_PRODUTO)}). Talvez o lote tenha pego trechos de outro clique; confira os horários.[/]")
    tabela(f"Trechos com diferença entre o que leram e o que o banco tem hoje (mostrando até {LINHAS_NA_LISTA} de {n(len(com_diferenca))})",
           ["MLB", "Datas", "Chamadas", "Lidos", "No banco", "Dif."], com_diferenca[:LINHAS_NA_LISTA], a_direita=(2, 3, 4, 5))
    if not com_diferenca:
        console.print("[green]Todos os trechos batem com o banco.[/]")
    console.print(f"Soma dos trechos: lidos {n(soma_lidos)} · no banco {n(soma_banco)} · diferença {com_sinal(soma_banco - soma_lidos)}")
    return {"trechos": len(lote), "chamadas": soma_chamadas, "lidos": soma_lidos, "no_banco": soma_banco, "diferenca": soma_banco - soma_lidos,
            "trechos_com_diferenca": len(com_diferenca), "detalhe": saida, "primeiro_inicio": min(c.iniciado_em for c in lote).isoformat()}


# ======================================================== 6) MLBs do SKU fora do produto ========================================================

def conferir_mlbs_de_fora(linhas, mlbs_do_produto):
    console.rule(f"[bold]6) MLBs com vendas do SKU {t(SKU)} que NÃO estão ligados ao produto")
    do_sku_fora = defaultdict(list)
    for l in linhas:
        if l.seller_sku == SKU and l.mlb not in mlbs_do_produto:
            do_sku_fora[l.mlb].append(l)
    if not do_sku_fora:
        console.print("Nenhum MLB fora do produto tem vendas deste SKU.")
        return []
    saida, tab = [], []
    for mlb, ls in sorted(do_sku_fora.items(), key=lambda kv: -len({l.order_id for l in kv[1]})):
        pedidos = len({l.order_id for l in ls})
        dias = sorted(l.dia_venda for l in ls)
        anuncio = AnuncioMercadoLivre.objects.filter(mlb=mlb).select_related("tipo_de_anuncio").first()
        if anuncio is None:
            situacao, titulo, status, ligacoes = "NÃO está na tabela de anúncios", "—", "—", {}
        else:
            skus = Counter(sku or "(variação sem produto ligado)" for sku in VariacaoAnuncioMercadoLivre.objects.filter(anuncio__mlb=mlb).values_list("produto__sku", flat=True))
            ligacoes = dict(skus)
            situacao = "está na tabela de anúncios, SEM variações" if not skus else "está na tabela de anúncios"
            titulo = anuncio.titulo_anuncio or "—"
            status = anuncio.tipo_de_anuncio.status if anuncio.tipo_de_anuncio else "—"
        ligacao_texto = ", ".join(f"{k}: {q}" for k, q in ligacoes.items()) or "—"
        tab.append((mlb, n(pedidos), f"{dia_curto(dias[0])} a {dia_curto(dias[-1])}", situacao, status, ligacao_texto, titulo[:60]))
        saida.append({"mlb": mlb, "pedidos": pedidos, "primeira_venda": dias[0].isoformat(), "ultima_venda": dias[-1].isoformat(), "situacao": situacao,
                      "status_do_anuncio": status, "variacoes_ligadas_a": ligacoes, "titulo": titulo})
    tabela("Por MLB (quem tem mais pedidos primeiro)", ["MLB", "Pedidos", "Vendas de … a …", "Na tabela de anúncios?", "Status", "Variações ligadas a (SKU: quantas)", "Título"], tab, a_direita=(1,))
    return saida


# ======================================================== 7) a hipótese da hora 0, número a número ========================================================

def pedidos_nao_relidos(linhas, ex):
    """Pedidos da janela criados antes da coleta começar e que ela (e nenhuma coleta depois) NÃO regravou: a faixa ANTES, os que a coleta não leu."""
    return {l.order_id for l in linhas if na_janela(l, ex.data_de, ex.data_ate) and l.criado_em_ml <= ex.iniciado_em and l.atualizado_em < ex.iniciado_em}


def testar_a_hora_0_do_dia_seguinte(linhas, execucoes, por_coleta, lote, ano):
    console.rule("[bold]7) A hipótese da hora 0, número a número")
    console.print("Previsto = (pedidos da hora 0 que a busca do dia anterior já trouxe) com sinal negativo + (pedidos que a coleta não releu) com sinal positivo. Sobra = observado − previsto.")
    saida = {"coletas_de_periodo": [], "trechos_do_sku": None}
    tab = []
    for ex, registro in zip(execucoes, por_coleta):
        repetidos = len(pedidos_da_hora_0_repetidos(linhas, ex))
        nao_relidos = len(pedidos_nao_relidos(linhas, ex))
        previsto = nao_relidos - repetidos
        sobra = registro["diferenca"] - previsto
        tab.append((f"{dia_curto(ex.data_de)} a {dia_curto(ex.data_ate)}", com_sinal(registro["diferenca"]), n(repetidos), n(nao_relidos), com_sinal(previsto), com_sinal(sobra)))
        saida["coletas_de_periodo"].append({"de": ex.data_de.isoformat(), "ate": ex.data_ate.isoformat(), "pedidos_lidos": ex.pedidos_lidos, "observado": registro["diferenca"],
                                            "repetidos_da_hora_0": repetidos, "nao_relidos": nao_relidos, "previsto": previsto, "sobra": sobra})
    tabela("Coletas de período", ["Datas", "Dif. observada", "Pedidos da hora 0 lidos 2×", "Não relidos (borda)", "Previsto", "Sobra"], tab, a_direita=(1, 2, 3, 4, 5))

    if lote:
        por_mlb = defaultdict(list)
        mlbs = {c.mlb for c in lote}
        for l in linhas:
            if l.mlb in mlbs:
                por_mlb[l.mlb].append(l)
        linhas_dos_trechos, detalhe = [], []
        soma_obs = soma_prev = bate = 0
        for c in sorted(lote, key=lambda c: (c.mlb, c.data_de)):
            ls = por_mlb.get(c.mlb, [])
            proximo = c.data_ate + timedelta(days=1)
            banco = len({l.order_id for l in ls if c.data_de <= l.dia_venda <= c.data_ate})
            hora_0 = len({l.order_id for l in ls if l.dia_venda == proximo and l.criado_em_ml.astimezone(FUSO).hour == 0}) if repete_a_hora_0(c.iniciado_em) else 0
            nao_relidos = len({l.order_id for l in ls if c.data_de <= l.dia_venda <= c.data_ate and l.atualizado_em < ano.iniciado_em})
            observado, previsto = banco - c.pedidos_lidos, nao_relidos - hora_0
            soma_obs += observado
            soma_prev += previsto
            bate += observado == previsto
            detalhe.append({"mlb": c.mlb, "de": c.data_de.isoformat(), "ate": c.data_ate.isoformat(), "observado": observado, "hora_0_do_dia_seguinte": hora_0, "nao_relidos": nao_relidos,
                            "previsto": previsto})
            if observado != 0 or previsto != 0:
                linhas_dos_trechos.append((c.mlb, f"{dia_curto(c.data_de)} a {dia_curto(c.data_ate)}", com_sinal(observado), n(hora_0), n(nao_relidos), com_sinal(previsto),
                                           "sim" if observado == previsto else "NÃO"))
        tabela(f"Trechos do SKU com diferença observada ou prevista (mostrando até {LINHAS_NA_LISTA} de {n(len(linhas_dos_trechos))})",
               ["MLB", "Datas", "Dif. observada", "Hora 0 do dia seguinte", "Não relidos", "Previsto", "Bate?"], linhas_dos_trechos[:LINHAS_NA_LISTA], a_direita=(2, 3, 4, 5))
        console.print(f"Trechos: {n(len(lote))} · batem exatamente com a previsão: {n(bate)} · soma observada {com_sinal(soma_obs)} · soma prevista {com_sinal(soma_prev)}")
        saida["trechos_do_sku"] = {"trechos": len(lote), "batem": bate, "soma_observada": soma_obs, "soma_prevista": soma_prev, "detalhe": detalhe}
    return saida


# ======================================================== leitura em linguagem simples ========================================================

def montar_leitura(execucoes_conta, hipotese, fora_da_janela, perfil, trechos, mlbs_fora, ano):
    leitura = []
    for e in execucoes_conta:
        proporcao = abs(e["diferenca"]) / e["pedidos_lidos"] * 100 if e["pedidos_lidos"] else 0
        quando = f"coleta de {e['de'][8:10]}/{e['de'][5:7]}/{e['de'][:4]} a {e['ate'][8:10]}/{e['ate'][5:7]}/{e['ate'][:4]}"
        if e["diferenca"] == 0:
            leitura.append(f"A {quando} FECHA com o banco: leu {n(e['pedidos_lidos'])} e o banco tem {n(e['no_banco_minimo'])}.")
        else:
            lado = "leu MAIS pedidos do que o banco tem" if e["diferenca"] < 0 else "o banco tem MAIS pedidos do que ela leu"
            proporcao_texto = f"{proporcao:.2f}".replace(".", ",")
            leitura.append(f"A {quando} NÃO fecha: {lado} (leu {n(e['pedidos_lidos'])}, banco {n(e['no_banco_minimo'])}; dif. {com_sinal(e['diferenca'])}, {proporcao_texto}% dos lidos).")
    if len(execucoes_conta) > 1 and ano is not None:
        outras = [e for e in execucoes_conta if e is not ano]
        if outras and ano["diferenca"] != 0 and all(e["diferenca"] == 0 for e in outras):
            leitura.append("A coleta curta fecha e a do ano não: a diferença mora nos dias mais antigos, não em algo que acontece em toda coleta.")
        elif outras and ano["diferenca"] != 0 and all(e["diferenca"] != 0 for e in outras):
            leitura.append("As duas coletas (curta e do ano) têm diferença: é algo sistemático, não só dos dias antigos.")
    for h in hipotese["coletas_de_periodo"]:
        quando = f"{h['de'][8:10]}/{h['de'][5:7]}/{h['de'][:4]} a {h['ate'][8:10]}/{h['ate'][5:7]}/{h['ate'][:4]}"
        folga = max(2, round(0.0005 * h["pedidos_lidos"]))
        veredito = "a hipótese da hora 0 EXPLICA a diferença" if abs(h["sobra"]) <= folga else "a hipótese da hora 0 NÃO explica tudo"
        depois = " Coleta feita DEPOIS da correção: a hora 0 não é mais repetida, então a sobra é o que faltou ler (veja os avisos da coleta)." if CORRECAO_DA_HORA_0_APLICADA_EM is not None and h["repetidos_da_hora_0"] == 0 else ""
        leitura.append(f"HORA 0, coleta de {quando}: observado {com_sinal(h['observado'])}, previsto {com_sinal(h['previsto'])} ({n(h['repetidos_da_hora_0'])} pedidos da hora 0 lidos 2×, "
                       f"{n(h['nao_relidos'])} não relidos), sobra {com_sinal(h['sobra'])}: {veredito}.{depois}")
    tr = hipotese["trechos_do_sku"]
    if tr is not None:
        leitura.append(f"HORA 0, SKU: {n(tr['batem'])} de {n(tr['trechos'])} trechos batem exatamente com a previsão (soma observada {com_sinal(tr['soma_observada'])}, prevista {com_sinal(tr['soma_prevista'])}).")
    if fora_da_janela["fora_da_janela"] == 0:
        leitura.append("Nenhuma linha gravada pela coleta do ano tem dia da venda fora da janela: fuso ou borda do dia desencontrados NÃO explicam a diferença.")
    else:
        leitura.append(f"{n(fora_da_janela['fora_da_janela'])} pedido(s) gravado(s) pela coleta do ano tem/têm dia da venda FORA da janela (veja a seção 3): isso entra na conta da diferença.")
    primeiro = perfil["primeiro_dia"]["faixas"]
    antes_do_dia = next((f for f in primeiro if f["faixa"] == "ANTES"), None)
    if antes_do_dia and antes_do_dia["pedidos"] not in ("0", 0):
        dia = perfil["primeiro_dia"]["dia"]
        leitura.append(f"No 1º dia da janela ({dia[8:10]}/{dia[5:7]}/{dia[:4]}) há pedido(s) que nenhuma coleta recente regravou; veja as horas na seção 4 para comparar com a hora em que a coleta rodou.")
    if perfil["dias_sem_pedido"]:
        leitura.append(f"{n(len(perfil['dias_sem_pedido']))} dia(s) da janela sem nenhum pedido no banco (seção 4): conferir se é dia sem venda de verdade.")
    if trechos is not None:
        if trechos["trechos_com_diferenca"] == 0:
            leitura.append("SKU: todos os trechos da coleta por produto batem com o banco (MLB + datas). A diferença total do SKU não vem de trecho específico.")
        else:
            leitura.append(f"SKU: {n(trechos['trechos_com_diferenca'])} de {n(trechos['trechos'])} trechos não batem com o banco; soma da diferença {com_sinal(trechos['diferenca'])} (veja a tabela da seção 5 para o MLB e as datas).")
    for m in mlbs_fora:
        if m["situacao"].startswith("NÃO está"):
            leitura.append(f"{m['mlb']} ({n(m['pedidos'])} pedido(s)) NÃO está hoje na tabela de anúncios (nunca foi importado ou foi apagado de lá), por isso não pode estar ligado a produto.")
        elif not m["variacoes_ligadas_a"]:
            leitura.append(f"{m['mlb']} ({n(m['pedidos'])} pedido(s)) está na tabela de anúncios mas sem variações: não há como ligá-lo ao produto.")
        elif SKU in m["variacoes_ligadas_a"]:
            leitura.append(f"{m['mlb']} ({n(m['pedidos'])} pedido(s)) tem variação ligada a ESTE SKU e mesmo assim ficou fora da lista do produto: investigar (carregar_produto lê VariacaoAnuncio por produto__sku).")
        else:
            ligado = ", ".join(f"{k} ({q})" for k, q in m["variacoes_ligadas_a"].items())
            leitura.append(f"{m['mlb']} ({n(m['pedidos'])} pedido(s)): as variações estão ligadas a: {ligado}. A venda saiu com o SKU deste produto, mas o anúncio está ligado a outro cadastro.")
    return leitura


def main():
    console.print(f"\n[bold]Diferenças entre as coletas, só no banco[/] · conta {CONTA} · SKU {t(SKU)} · só leitura (SELECT no banco; nenhuma chamada à API)\n")
    execucoes = carregar_execucoes_de_periodo()
    if not execucoes:
        console.print("[bold red]Não achei nenhuma coleta de PERÍODO concluída na tabela de execuções. Nada a conferir.[/]")
        return
    ano = max(execucoes, key=lambda e: (e.dias_total, e.iniciado_em))
    lote = ler_lote_da_coleta_por_produto()
    de = min([e.data_de for e in execucoes] + [c.data_de for c in lote])
    ate = max([e.data_ate for e in execucoes] + [c.data_ate for c in lote])
    linhas = carregar_linhas(de, ate)
    console.print(f"Linhas lidas do banco (de {dia_curto(de)} a {dia_curto(ate)}, com 3 dias de folga): {n(len(linhas))}\n")

    por_coleta = conferir_cada_coleta_de_periodo(execucoes, linhas)
    registro_do_ano = next(r for r, e in zip(por_coleta, execucoes) if e is ano)
    hora_0 = teste_da_hora_0(linhas, ano, registro_do_ano["diferenca"])
    fora = linhas_tocadas_fora_da_janela(ano)
    perfil = perfil_por_dia_e_bordas(linhas, ano)

    trechos = conferir_trechos_do_sku(linhas, lote)
    produto = carregar_produto(SKU)
    mlbs_fora = conferir_mlbs_de_fora(linhas, set(produto["mlbs"])) if produto is not None else []
    if produto is None:
        console.print(f"[bold red]SKU {t(SKU)} não encontrado em Produto: a seção 6 foi pulada.[/]")

    hipotese = testar_a_hora_0_do_dia_seguinte(linhas, execucoes, por_coleta, lote, ano)
    console.rule("[bold]Leitura")
    leitura = montar_leitura(por_coleta, hipotese, fora, perfil, trechos, mlbs_fora, registro_do_ano)
    for linha in leitura:
        console.print(f"• {t(linha)}")
    saida = {"conta": CONTA, "sku": SKU, "coletas_de_periodo": por_coleta, "hora_0": hora_0, "fora_da_janela": fora, "perfil_por_dia": perfil,
             "sku_trechos": trechos, "mlbs_fora_do_produto": mlbs_fora, "hipotese_hora_0": hipotese, "leitura": leitura}
    CAMINHO_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    console.print(f"\nJSON salvo em: {CAMINHO_SAIDA.name}. Sem chamada à API e sem dado de comprador (o banco não guarda).")


if __name__ == "__main__":
    main()
