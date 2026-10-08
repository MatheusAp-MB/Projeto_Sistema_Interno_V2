# scripts_exploracao_ML/investigar_estoque_flex_full.py
#
# Função Objetivo: descobrir se o Mercado Livre devolve, para o Brasil, o estoque FLEX (o depósito do
# vendedor) separado do estoque FULL — e conferir se essa divisão explica a diferença que a tela
# "Estoque no Full" mostra hoje entre o "Disponível" do Full e o "Estoque" do anúncio
# (ex.: QAVX18725 -> Full disponível 174, anúncio 221).
#
# A dúvida: a doc oficial "Convivência Full e Flex" descreve o recurso
#     GET /user-products/{user_product_id}/stock
# que divide o estoque do produto em dois "locais":
#     meli_facility   = o estoque que está no Full
#     selling_address = o estoque do depósito do vendedor (o Flex)
# mas a doc diz que ele foi liberado para Argentina e Chile (MLA/MLC) — não fala do Brasil. Só um teste
# de verdade responde. Se o ML RECUSAR (400, 403, 404...), a recusa já é a resposta: o script mostra o
# texto exato, e o próximo passo passa a ser a doc "Estoque Multi-origem".
#
# Para cada Código ML da lista CODIGOS, as chamadas (todas GET, só leitura):
#   FLEX     GET /user-products/{user_product_id}/stock         NOVO — é o que estamos testando.
#   ESTOQUE  GET /inventories/{inventory_id}/stock/fulfillment  JÁ USADO na tela "Estoque no Full";
#                                                               serve só para comparar no MESMO instante.
#   ANÚNCIO  GET /items?ids=MLB...,MLB...                       JÁ USADO (comando buscar_detalhes);
#                                                               traz o estoque ATUAL de cada anúncio.
# O script mostra a lista de chamadas ANTES de fazê-las.
#
# O segundo código da lista é um "controle": na tela salva, o "Estoque" do anúncio é IGUAL ao "Disponível"
# do Full (57 e 57). Se a hipótese estiver certa, o Flex dele vem zerado (ou nem aparece).
#
# Só leitura (só GET). Não toca no banco. Só roda quando VOCÊ executa o script.
#
# Arquivo de saída (o .gitignore já cobre pela regra "scripts_exploracao_ML/*.json"):
#   estoque_flex_full_<data>_<hora>.json -> as respostas CRUAS das 3 chamadas de cada código.
#
# Como rodar:
#   poetry run python scripts_exploracao_ML/investigar_estoque_flex_full.py

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Permite rodar este script direto, de qualquer diretório, sem depender do CWD
# pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                          # "MB" (Magazine) ou "SV" (Samvale)
CODIGOS = ["QAVX18725", "QGOL06347"]  # o 1º é o caso com sobra (221 x 174); o 2º é o controle (57 x 57)
# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
PASTA_LOGS = PASTA_SCRIPT / "logs"
NOME_LOG = "investigar_estoque_flex_full"

PASTA_DETALHES_POR_CONTA = {"MB": "Magazine", "SV": "Samvale"}
NOME_COMANDO_POR_CONTA = {"MB": "magazine", "SV": "samvale"}

ENDPOINT_FLEX = "/user-products/{user_product_id}/stock"
ENDPOINT_ESTOQUE = "/inventories/{inventory_id}/stock/fulfillment"
ENDPOINT_ANUNCIOS = "/items"

MAX_ANUNCIOS_POR_CHAMADA = 20   # o /items?ids= aceita até 20 por chamada (mesmo limite do buscar_detalhes)
NOME_DO_LOCAL = {"meli_facility": "no Full (meli_facility)", "selling_address": "no seu depósito — Flex (selling_address)",
                 "seller_warehouse": "em depósito do vendedor (seller_warehouse)"}


# ---------------------------------------------------------------------------
# Apoio: formatação e números
# ---------------------------------------------------------------------------
def t(valor) -> str:
    """Texto vindo da API/arquivo pode ter colchetes; o rich leria como formatação — escapa antes de mostrar."""
    return escape(str(valor))


def n_br(valor) -> str:
    """1146 -> '1.146'; None -> '—'."""
    if valor is None:
        return "—"
    return f"{valor:,}".replace(",", ".")


def inteiro(valor):
    """Número inteiro da resposta, ou None se não for número."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float) and valor == int(valor):
        return int(valor)
    if isinstance(valor, str) and re.fullmatch(r"-?\d+", valor.strip()):
        return int(valor)
    return None


# ---------------------------------------------------------------------------
# PASSO 1 — leitura local (ARQUIVO, sem API)
# ---------------------------------------------------------------------------
def carregar_detalhes(conta: str):
    """(registros, gerado_em) do detalhes_mlbs.json da conta, ou (None, None) se o arquivo não existe."""
    caminho = (_RAIZ_DO_PROJETO / "integracao_mercado_livre" / "Arquivos_API"
               / PASTA_DETALHES_POR_CONTA[conta] / "detalhes_mlbs.json")
    if not caminho.exists():
        console.print(
            f"[red]{t(caminho)} não existe neste PC — rode "
            f"'poetry run python manage.py buscar_detalhes --empresa {NOME_COMANDO_POR_CONTA[conta]}' primeiro.[/red]"
        )
        return None, None
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    return dados.get("registros", []), dados.get("gerado_em")


def registros_do_codigo(registros: list, codigo: str) -> list:
    return [r for r in registros if str(r.get("inventory_id") or "").strip().upper() == codigo.upper()]


# ---------------------------------------------------------------------------
# PASSO 2 — chamadas à API
# ---------------------------------------------------------------------------
def consultar(endpoint: str, params: dict = None) -> dict:
    """1 chamada GET. Erro da API (400, 403, 404...) NÃO derruba o script: vira um registro com 'erro'.
    Só a autenticação recusada (401) interrompe tudo, porque nenhuma chamada seguinte funcionaria."""
    try:
        resposta = chamar_api("GET", endpoint, pasta_logs=PASTA_LOGS, conta=CONTA,
                              params=params, nome_log=NOME_LOG)
    except ErroAutenticacaoAPI:
        raise
    except ErroAPI as erro:
        texto = str(erro)
        achou = re.match(r"Erro (\d+) em", texto)
        return {"endpoint": endpoint, "params": params, "status_http": int(achou.group(1)) if achou else None,
                "erro": texto, "corpo": None}

    try:
        corpo = resposta.json()
    except ValueError:
        return {"endpoint": endpoint, "params": params, "status_http": resposta.status_code,
                "erro": f"A resposta não veio em JSON: {resposta.text[:300]}", "corpo": None}
    return {"endpoint": endpoint, "params": params, "status_http": resposta.status_code, "erro": None, "corpo": corpo}


# ---------------------------------------------------------------------------
# PASSO 3 — ler o que voltou
# ---------------------------------------------------------------------------
def locais_do_flex(resultado: dict):
    """{'meli_facility': 174, 'selling_address': 47} (soma por tipo), ou None se a chamada falhou
    ou a resposta não veio no formato da doc (lista "locations")."""
    corpo = resultado.get("corpo")
    if not isinstance(corpo, dict) or not isinstance(corpo.get("locations"), list):
        return None
    locais = {}
    for local in corpo["locations"]:
        if isinstance(local, dict) and local.get("type") is not None:
            tipo = str(local["type"])
            locais[tipo] = locais.get(tipo, 0) + (inteiro(local.get("quantity")) or 0)
    return locais


def disponivel_do_full(resultado: dict):
    corpo = resultado.get("corpo")
    return inteiro(corpo.get("available_quantity")) if isinstance(corpo, dict) else None


def estoque_dos_anuncios(resultado: dict):
    """{'MLB123': 221, ...} com o estoque ATUAL de cada anúncio (só os que o ML devolveu com code 200),
    ou None se a chamada falhou."""
    corpo = resultado.get("corpo")
    if not isinstance(corpo, list):
        return None
    achados = {}
    for item in corpo:
        dados = item.get("body") if isinstance(item, dict) else None
        if isinstance(item, dict) and item.get("code") == 200 and isinstance(dados, dict) and dados.get("id"):
            achados[str(dados["id"])] = inteiro(dados.get("available_quantity"))
    return achados


# ---------------------------------------------------------------------------
# Apresentação
# ---------------------------------------------------------------------------
def nova_tabela(titulo: str, ultima_coluna: str = "De onde vem") -> Table:
    tabela = Table(title=titulo, title_justify="left", show_lines=False, header_style="bold")
    tabela.add_column("O que é", overflow="fold")
    tabela.add_column("Valor", justify="right", no_wrap=True)
    tabela.add_column(ultima_coluna, overflow="fold")
    return tabela


def conferir(tabela: Table, pergunta: str, rotulo_a: str, a, rotulo_b: str, b, se_faltar: str) -> str:
    """Uma linha de conferência entre dois números. Devolve 'sim', 'nao' ou 'sem_dado' (para o resumo final)."""
    if a is None or b is None:
        tabela.add_row(pergunta, "[yellow]sem dado[/yellow]", t(se_faltar))
        return "sem_dado"
    if a == b:
        tabela.add_row(pergunta, "[green]bate[/green]", t(f"{rotulo_a} {n_br(a)} = {rotulo_b} {n_br(b)}"))
        return "sim"
    tabela.add_row(pergunta, "[red]não bate[/red]",
                   t(f"{rotulo_a} {n_br(a)} · {rotulo_b} {n_br(b)} (diferença de {n_br(abs(a - b))}). "
                     "Diferença pequena pode ser venda ou entrada entre uma chamada e outra."))
    return "nao"


def investigar_codigo(codigo: str, registros_arquivo: list, gerado_em) -> dict:
    """Roda as chamadas de 1 Código ML, mostra o resultado e devolve tudo (para o JSON e para o resumo)."""
    console.rule(f"[bold]CÓDIGO {t(codigo)}")
    do_codigo = registros_do_codigo(registros_arquivo, codigo)
    ativos = [r for r in do_codigo if r.get("status") in ("active", "paused")]
    escolhidos = (ativos or do_codigo)[:MAX_ANUNCIOS_POR_CHAMADA]
    mlbs = sorted({r["mlb"] for r in escolhidos if r.get("mlb")})
    user_products = sorted({r["user_product_id"] for r in escolhidos if r.get("user_product_id")})

    criterio = "" if not escolhidos else (" (ativos/pausados)" if ativos else " (todos, pois nenhum está ativo ou pausado)")
    console.print(f"Passo 1 — o seu detalhes_mlbs.json (gerado em {t(gerado_em)}; sem API): "
                  f"{len(do_codigo)} registro(s) com este Código; vou usar {len(escolhidos)}{criterio}.")
    for r in escolhidos:
        console.print(f"   {t(r.get('mlb'))}  {t(r.get('status'))}  logística={t(r.get('logistic_type'))}  "
                      f"estoque no arquivo={n_br(inteiro(r.get('available_quantity')))}  "
                      f"user_product_id={t(r.get('user_product_id'))}")
    if not do_codigo:
        console.print(f"[yellow]   Nenhum registro do seu arquivo tem o Código {t(codigo)} — "
                      "só dá para chamar o estoque do Full; o Flex e os anúncios ficam sem consulta.[/yellow]")

    chamadas = [("ESTOQUE", ENDPOINT_ESTOQUE.format(inventory_id=codigo), None)]
    chamadas += [("FLEX", ENDPOINT_FLEX.format(user_product_id=u), None) for u in user_products]
    if mlbs:
        chamadas.append(("ANÚNCIOS", ENDPOINT_ANUNCIOS, {"ids": ",".join(mlbs)}))
    console.print(f"Passo 2 — chamadas GET que serão feitas agora: {len(chamadas)}")
    for nome, endpoint, params in chamadas:
        complemento = f"?ids={t(params['ids'])}" if params else ""
        console.print(f"   {nome:<9} GET {t(endpoint)}{complemento}")
    if do_codigo and not user_products:
        console.print("[yellow]   Nenhum user_product_id no seu arquivo para este Código — o Flex não tem como ser chamado.[/yellow]")

    res_estoque = consultar(ENDPOINT_ESTOQUE.format(inventory_id=codigo))
    res_flex = {u: consultar(ENDPOINT_FLEX.format(user_product_id=u)) for u in user_products}
    res_anuncios = consultar(ENDPOINT_ANUNCIOS, {"ids": ",".join(mlbs)}) if mlbs else None

    # ---------- o que voltou ----------
    disponivel = disponivel_do_full(res_estoque)
    total_full = inteiro(res_estoque["corpo"].get("total")) if isinstance(res_estoque.get("corpo"), dict) else None
    anuncios_agora = estoque_dos_anuncios(res_anuncios) if res_anuncios else None

    tabela = nova_tabela(f"Passo 3 — o que o ML respondeu para {t(codigo)}")
    if res_estoque["erro"]:
        tabela.add_row("Full — disponível para venda", "[red]erro[/red]", t(res_estoque["erro"]))
    else:
        tabela.add_row("Full — disponível para venda", n_br(disponivel), "ESTOQUE · available_quantity")
        tabela.add_row("Full — total (disponível + indisponível)", n_br(total_full), "ESTOQUE · total")

    locais_por_produto = {}
    for upid, res in res_flex.items():
        locais = locais_do_flex(res)
        locais_por_produto[upid] = locais
        if res["erro"]:
            tabela.add_row(f"Flex — produto {t(upid)}", "[red]recusado[/red]", t(res["erro"]))
        elif locais is None:
            tabela.add_row(f"Flex — produto {t(upid)}", "[yellow]formato diferente[/yellow]",
                           t(f"HTTP {res['status_http']}: veio sem a lista 'locations'. Resposta: {json.dumps(res['corpo'], ensure_ascii=False)[:300]}"))
        elif not locais:
            tabela.add_row(f"Flex — produto {t(upid)}", "[yellow]vazio[/yellow]", t(f"HTTP {res['status_http']}: 'locations' veio vazia."))
        else:
            for tipo, qtd in sorted(locais.items()):
                tabela.add_row(f"Estoque {t(NOME_DO_LOCAL.get(tipo, tipo))} — produto {t(upid)}", n_br(qtd),
                               t(f"FLEX · locations[type={tipo}].quantity"))
            if "selling_address" not in locais:
                tabela.add_row(f"Estoque {NOME_DO_LOCAL['selling_address']} — produto {t(upid)}", "[dim]não veio[/dim]",
                               "O ML não listou este local (conta como zero nas contas abaixo).")

    if res_anuncios is not None:
        if res_anuncios["erro"]:
            tabela.add_row("Anúncios — estoque agora", "[red]erro[/red]", t(res_anuncios["erro"]))
        else:
            do_arquivo = {r["mlb"]: inteiro(r.get("available_quantity")) for r in escolhidos if r.get("mlb")}
            for mlb in mlbs:
                tabela.add_row(f"Anúncio {t(mlb)} — estoque agora", n_br((anuncios_agora or {}).get(mlb)),
                               t(f"ANÚNCIOS · available_quantity (no arquivo de {gerado_em}: {n_br(do_arquivo.get(mlb))})"))
    console.print(tabela)

    # ---------- as contas ----------
    contas = nova_tabela(f"Passo 4 — as contas para {t(codigo)}", "Detalhe")
    veredictos = []
    for upid, locais in locais_por_produto.items():
        if not locais:   # None (formato diferente / recusado) ou {} (lista vazia): não há o que somar
            continue
        no_full = locais.get("meli_facility")
        soma_locais = sum(locais.values())
        veredictos.append((f"meli_facility = Disponível do Full ({upid})",
                           conferir(contas, f"'meli_facility' é igual ao Disponível do Full? ({t(upid)})",
                                    "Disponível do Full", disponivel, "meli_facility", no_full,
                                    "falta o número do estoque do Full ou o 'meli_facility' do Flex")))
        for mlb in mlbs:
            veredictos.append((f"Soma dos locais = anúncio {mlb}",
                               conferir(contas, f"Full + Flex ({n_br(soma_locais)}) é igual ao estoque do anúncio {t(mlb)} agora?",
                                        "anúncio", (anuncios_agora or {}).get(mlb), "Full + Flex", soma_locais,
                                        "falta o estoque atual do anúncio")))
    if not any(locais_por_produto.values()):
        contas.add_row("Nenhuma conta possível", "[yellow]sem dado[/yellow]",
                       "o Flex não trouxe a lista de locais para este Código (veja o Passo 3)")
    console.print(contas)

    return {
        "codigo": codigo,
        "registros_do_arquivo_usados": [{c: r.get(c) for c in ("mlb", "status", "logistic_type", "available_quantity",
                                                              "user_product_id", "inventory_id", "title")} for r in escolhidos],
        "estoque": res_estoque, "flex": res_flex, "anuncios": res_anuncios,
        "resumo": {"disponivel_full": disponivel, "locais_por_produto": locais_por_produto,
                   "flex_trouxe_locais": any(locais_por_produto.values()),
                   "anuncios_agora": anuncios_agora, "veredictos": veredictos},
    }


def main() -> None:
    if CONTA not in PASTA_DETALHES_POR_CONTA:
        console.print(f"[red]CONTA inválida: {t(CONTA)}. Use {list(PASTA_DETALHES_POR_CONTA)}.[/red]")
        sys.exit(1)

    console.rule(f"[bold]TESTE DO ESTOQUE FLEX — conta {CONTA} — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    console.print("O que este teste responde: o Mercado Livre devolve, para a nossa conta, o estoque do Flex separado "
                  "do estoque do Full? E essa divisão explica a diferença entre o 'Disponível' do Full e o 'Estoque' do anúncio?")

    registros, gerado_em = carregar_detalhes(CONTA)
    if registros is None:
        sys.exit(1)

    resultados = []
    abortado = False
    try:
        for codigo in CODIGOS:
            resultados.append(investigar_codigo(codigo, registros, gerado_em))
    except ErroAutenticacaoAPI as erro:
        console.print(f"[red]A API recusou o token (401): {t(erro)} — interrompendo as próximas consultas.[/red]")
        abortado = True

    # ---------- resumo ----------
    console.rule("[bold]RESUMO")
    for r in resultados:
        flex = list(r["flex"].values())
        recusados = [x for x in flex if x["erro"]]
        if flex and len(recusados) == len(flex):
            console.print(f"{t(r['codigo'])}: o ML RECUSOU a consulta do Flex ({t(recusados[0]['erro'][:160])}). "
                          "Isso já é a resposta: este endpoint não serve para esta conta.")
        elif not flex:
            console.print(f"{t(r['codigo'])}: o Flex não foi consultado (sem user_product_id no seu arquivo).")
        elif not r["resumo"]["flex_trouxe_locais"]:
            console.print(f"{t(r['codigo'])}: o ML respondeu, mas SEM a lista de locais da doc (veio vazia ou em outro formato). "
                          "O texto exato está no Passo 3 e no arquivo salvo.")
        else:
            sim = sum(1 for _, v in r["resumo"]["veredictos"] if v == "sim")
            nao = sum(1 for _, v in r["resumo"]["veredictos"] if v == "nao")
            sem = sum(1 for _, v in r["resumo"]["veredictos"] if v == "sem_dado")
            console.print(f"{t(r['codigo'])}: o Flex respondeu com a lista de locais. "
                          f"Contas que bateram: {sim}; que não bateram: {nao}; sem dado: {sem}.")

    caminho_saida = PASTA_SCRIPT / f"estoque_flex_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump({"gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "conta": CONTA, "codigos": CODIGOS,
                   "arquivo_detalhes_gerado_em": gerado_em, "resultados": resultados},
                  f, ensure_ascii=False, indent=2)
    console.print(f"\n[bold]Arquivo salvo:[/bold] {t(caminho_saida)}")
    console.print("Me mande este arquivo (ou o texto que apareceu na tela) para eu analisar.")
    if abortado:
        console.print("[red]Execução interrompida por erro de autenticação — o arquivo tem só o que foi consultado até aqui.[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
