# scripts_exploracao_ML/investigar_full_reposicao.py
#
# Função Objetivo: primeiro contato com os dados do Full (Mercado Livre) pela
# API, olhando 1 produto (1 SKU) de ponta a ponta, pra entender como a tela
# "Gestão de estoque Full -> Planejamento de envios" pode virar um relatório.
# Nada é suposto: o script mostra o que a API devolve de verdade, campo a
# campo, pra você comparar com a tela.
#
# Ponto de partida: na tela do ML, buscar o SKU (…/shipment_planning?search=<SKU>)
# devolve 1 linha por anúncio ligado a ele. Cada linha é identificada pelo
# "Código ML" (o inventory_id, quando o produto já esteve no Full) ou por
# "#<número do MLB>" (quando nunca teve estoque no Full). Este script parte do
# mesmo SKU e dos mesmos códigos que aparecem na tela.
#
# O que ele faz, em 2 partes:
#
#   PARTE A — só leitura local, ZERO chamada à API.
#     Lê o detalhes_mlbs.json da conta (integracao_mercado_livre/Arquivos_API/
#     <Magazine|Samvale>/detalhes_mlbs.json, o mesmo que o comando
#     buscar_detalhes gera) e:
#       1) conta o "universo Full" que o seu sistema já conhece (quantos
#          anúncios/variações são Full, quantos têm inventory_id e
#          user_product_id, quantos códigos distintos) — pra comparar com os
#          "4.671 resultados" da tela;
#       2) procura os registros do SKU e os registros dos códigos que aparecem
#          na tela, e mostra quais o seu sistema conhece e quais NÃO (só na
#          tela / só no sistema).
#
#   PARTE B — chamadas à API (só GET, só leitura), só pros registros achados.
#     Pra cada user_product_id distinto:
#       GET /marketplace/fbm/user-products/{user_product_id}/replenishment?country=BR
#       (doc "Planejamento de reposição": urgência, mínimo, vendas, sugestão,
#       estrela, estoque antigo...)
#     Pra cada inventory_id distinto:
#       GET /inventories/{inventory_id}/stock/fulfillment
#       (doc "Envios Fulfillment": estoque apto e não apto, com o motivo)
#     O script conta e mostra quantas chamadas vai fazer ANTES da primeira.
#     Pra rodar SÓ a parte A, troque CONSULTAR_API pra False.
#
# O que sai na tela: o resumo do universo Full, o cruzamento tela x sistema,
# os campos da API (um quadro por produto que já esteve no Full), um quadro
# resumo com todos os registros lado a lado e a conta de conferência
# (total_stock - aptas) pra testar a ideia de "a caminho". Também mostra
# qualquer campo que a API mandou e que a doc NÃO cita.
#
# Arquivo de saída (o .gitignore já cobre pela regra "scripts_exploracao_ML/*.json"):
#   investigacao_full_<SKU>.json -> universo local + cruzamento + retorno CRU da API
#                                   de cada registro (sem filtrar nem renomear campo).
#                                   Dos registros locais guarda só alguns campos
#                                   (mlb, variação, sku, status, título, códigos).
#
# Só leitura. Não toca no banco. Não faz nenhuma chamada automática: só roda
# quando VOCÊ executa o script.
#
# Como rodar:
#   poetry run python scripts_exploracao_ML/investigar_full_reposicao.py

import json
import re
import sys
from collections import Counter, defaultdict
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
CONTA = "MB"                    # "MB" (Magazine) ou "SV" (Samvale)
SKU = "F7908050719121.001"      # o mesmo SKU digitado na busca da tela do ML

# Códigos que a tela mostrou ao buscar esse SKU (13 resultados em 06/10/2026).
# "Código ML" = inventory_id; "#número" = MLB sem o prefixo (produto que nunca teve estoque no Full).
# Serve só pra conferir se o seu sistema conhece tudo que a tela mostra. Pode deixar vazio: [].
CODIGOS_DA_TELA = [
    "OPXW24140", "QAVX18725", "RWBD51502",
    "#2616936722", "#4232612385", "#4242628323", "#4269465043", "#5838590006",
    "#5838589786", "#4479289263", "#4479357333", "#4479436313", "#5838414144",
]

# True = faz as chamadas à API (parte B). False = só a leitura local (parte A).
CONSULTAR_API = True
# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
PASTA_LOGS = PASTA_SCRIPT / "logs"
NOME_LOG = "investigar_full_reposicao"
SKU_LIMPO = SKU.strip().upper()
CAMINHO_SAIDA = PASTA_SCRIPT / f"investigacao_full_{re.sub(r'[^A-Za-z0-9]+', '_', SKU_LIMPO)}.json"

# conta (a mesma usada nos outros scripts) -> pasta em integracao_mercado_livre/Arquivos_API/
PASTA_DETALHES_POR_CONTA = {"MB": "Magazine", "SV": "Samvale"}
NOME_COMANDO_POR_CONTA = {"MB": "magazine", "SV": "samvale"}

ENDPOINT_ESTOQUE = "/inventories/{inventory_id}/stock/fulfillment"
ENDPOINT_REPOSICAO = "/marketplace/fbm/user-products/{user_product_id}/replenishment"

# Campos do registro local que vão pro arquivo de saída (o resto do registro fica de fora).
CAMPOS_LOCAIS = (
    "mlb", "variacao_id", "sku", "status", "logistic_type",
    "available_quantity", "user_product_id", "inventory_id", "title",
)

# Chaves que a DOC cita em cada bloco. Tudo que a API mandar fora disso é mostrado
# como "campo novo" — é justamente o tipo de coisa que queremos descobrir.
CHAVES_DOC_REPOSICAO = {
    "(raiz)": {"identifiers", "product", "stock", "sales", "recommendation", "eligibility_benefits"},
    "identifiers": {"user_product_id", "inventory_id", "seller_sku"},
    "product": {"tags", "packages_master_case"},
    "stock": {"total_stock", "shipping_urgency", "minimum_distributable_stock"},
    "sales": {"sales_totals", "sales_history"},
    "recommendation": {"recommendation_type", "suggested_quantity", "replenishment_deadline", "replenishment_frequency"},
}
CHAVES_DOC_ESTOQUE = {
    "(raiz)": {"inventory_id", "total", "available_quantity", "not_available_quantity",
               "not_available_detail", "external_references"},
}


def t(valor) -> str:
    """Texto vindo da API/arquivo pode ter colchetes ("[x]"); o rich leria como formatação — escapa antes de mostrar."""
    return escape(str(valor))


def compacto(valor) -> str:
    return json.dumps(valor, ensure_ascii=False)


def colunas(tabela: Table, *nomes: str) -> None:
    """Adiciona colunas que quebram o texto em vez de cortar com '…' (código e MLB têm que aparecer inteiros)."""
    for nome in nomes:
        tabela.add_column(nome, overflow="fold")


def pega(objeto, *caminho):
    """objeto["a"]["b"]... sem quebrar quando algum nível é null/ausente."""
    for chave in caminho:
        if not isinstance(objeto, dict):
            return None
        objeto = objeto.get(chave)
    return objeto


# ---------------------------------------------------------------------------
# PARTE A — leitura local (detalhes_mlbs.json)
# ---------------------------------------------------------------------------
def caminho_detalhes(conta: str) -> Path:
    return (_RAIZ_DO_PROJETO / "integracao_mercado_livre" / "Arquivos_API"
            / PASTA_DETALHES_POR_CONTA[conta] / "detalhes_mlbs.json")


def carregar_detalhes(conta: str):
    """(registros, gerado_em) do detalhes_mlbs.json da conta, ou (None, None) se o arquivo não existe."""
    caminho = caminho_detalhes(conta)
    if not caminho.exists():
        console.print(
            f"[red]{t(caminho)} não existe neste PC — rode "
            f"'poetry run python manage.py buscar_detalhes --empresa {NOME_COMANDO_POR_CONTA[conta]}' primeiro.[/red]"
        )
        return None, None
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    return dados.get("registros", []), dados.get("gerado_em")


def eh_full(registro: dict) -> bool:
    return str(registro.get("logistic_type") or "").strip().lower() == "fulfillment"


def _user_products_por_status(registros: list) -> dict:
    """{status: quantos user_product_id distintos têm algum registro nesse status} (o mesmo
    user_product_id pode aparecer em mais de um status, ex.: anúncio ativo + clone fechado)."""
    por_status = defaultdict(set)
    for r in registros:
        if r.get("user_product_id"):
            por_status[str(r.get("status"))].add(r["user_product_id"])
    return {status: len(ids) for status, ids in sorted(por_status.items())}


def resumir_universo(registros: list, gerado_em) -> dict:
    full = [r for r in registros if eh_full(r)]

    inventarios = defaultdict(set)   # inventory_id -> {user_product_id}
    contagem_inventario = Counter()
    for r in full:
        inv = r.get("inventory_id")
        if inv:
            contagem_inventario[inv] += 1
            if r.get("user_product_id"):
                inventarios[inv].add(r["user_product_id"])

    return {
        "detalhes_gerado_em": gerado_em,
        "registros_no_arquivo": len(registros),
        "registros_por_logistic_type": dict(Counter(str(r.get("logistic_type")) for r in registros)),
        "full_registros (anuncio ou variacao)": len(full),
        "full_mlbs_distintos": len({r.get("mlb") for r in full}),
        "full_em_anuncio_com_variacoes": sum(1 for r in full if r.get("tem_variacoes")),
        "full_com_inventory_id": sum(1 for r in full if r.get("inventory_id")),
        "full_sem_inventory_id": sum(1 for r in full if not r.get("inventory_id")),
        "full_inventory_ids_distintos": len(contagem_inventario),
        "full_com_user_product_id": sum(1 for r in full if r.get("user_product_id")),
        "full_sem_user_product_id": sum(1 for r in full if not r.get("user_product_id")),
        "full_user_product_ids_distintos": len({r["user_product_id"] for r in full if r.get("user_product_id")}),
        "inventory_id_em_mais_de_um_registro": sum(1 for n in contagem_inventario.values() if n > 1),
        "inventory_id_com_mais_de_um_user_product_id": sum(1 for s in inventarios.values() if len(s) > 1),
        "full_por_status": dict(Counter(str(r.get("status")) for r in full)),
        # A tela lista TAMBÉM produtos que nunca estiveram no Full (os "#MLB…"), então o número dela
        # (4.671) deve se comparar com os user_product_id de TODOS os registros, não só os Full.
        "TODOS_registros_com_user_product_id": sum(1 for r in registros if r.get("user_product_id")),
        "TODOS_user_product_ids_distintos": len({r["user_product_id"] for r in registros if r.get("user_product_id")}),
        "TODOS_user_product_ids_distintos_por_status": _user_products_por_status(registros),
        "TODOS_user_product_ids_distintos_active_ou_paused": len(
            {r["user_product_id"] for r in registros
             if r.get("user_product_id") and str(r.get("status")) in ("active", "paused")}),
    }


def mostrar_universo(resumo: dict) -> None:
    tabela = Table(title=f"Universo Full conhecido pelo seu sistema — conta {CONTA} (detalhes_mlbs.json, sem API)")
    tabela.add_column("Medida")
    tabela.add_column(CONTA, justify="right")
    for medida, valor in resumo.items():
        if isinstance(valor, dict):
            valor = ", ".join(f"{k}={v}" for k, v in valor.items()) or "-"
        tabela.add_row(t(medida), t(valor))
    console.print(tabela)


def normalizar_codigo_da_tela(codigo: str):
    """'#2616936722' -> ('mlb', 'MLB2616936722');  'OPXW24140' -> ('inventory_id', 'OPXW24140')."""
    c = str(codigo).strip().upper()
    if c.startswith("#"):
        digitos = re.sub(r"\D", "", c)
        return ("mlb", f"MLB{digitos}")
    return ("inventory_id", c)


def achar_alvos(registros: list):
    """Registros do SKU + registros dos códigos da tela. Devolve (alvos, codigos_da_tela_sem_registro).
    alvos: lista de {"registro", "motivos"}; motivos = {"sku"} e/ou {"tela:<código>"}."""
    codigos = [(c, *normalizar_codigo_da_tela(c)) for c in CODIGOS_DA_TELA if str(c).strip()]
    achados_por_codigo = {c: False for c, _, _ in codigos}

    alvos = []
    for r in registros:
        motivos = set()
        if str(r.get("sku") or "").strip().upper() == SKU_LIMPO:
            motivos.add("sku")
        inv = str(r.get("inventory_id") or "").strip().upper()
        mlb = str(r.get("mlb") or "").strip().upper()
        for original, tipo, valor in codigos:
            if (tipo == "inventory_id" and inv == valor) or (tipo == "mlb" and mlb == valor):
                motivos.add(f"tela:{original}")
                achados_por_codigo[original] = True
        if motivos:
            alvos.append({"registro": r, "motivos": motivos})

    sem_registro = [c for c, achou in achados_por_codigo.items() if not achou]
    return alvos, sem_registro


def descrever_motivos(motivos: set) -> str:
    tem_sku = "sku" in motivos
    tem_tela = any(m.startswith("tela:") for m in motivos)
    if tem_sku and tem_tela:
        return "SKU + tela"
    if tem_sku:
        return "só SKU (não está nos códigos da tela)"
    return "só tela (SKU diferente)"


def mostrar_alvos(alvos: list, sem_registro: list) -> None:
    tabela = Table(title=f"Registros do seu sistema para o SKU {SKU_LIMPO} e para os códigos da tela")
    colunas(tabela, "mlb", "variacao_id", "sku", "status", "logistic_type", "estoque anúncio",
            "user_product_id", "inventory_id", "achado por")
    for alvo in alvos:
        r = alvo["registro"]
        tabela.add_row(
            t(r.get("mlb")), t(r.get("variacao_id")), t(r.get("sku")), t(r.get("status")),
            t(r.get("logistic_type")), t(r.get("available_quantity")),
            t(r.get("user_product_id")), t(r.get("inventory_id")), t(descrever_motivos(alvo["motivos"])),
        )
    console.print(tabela)
    console.print(f"Registros achados: {len(alvos)}  •  códigos da tela: {len(CODIGOS_DA_TELA)}")
    if sem_registro:
        console.print(f"[yellow]Códigos que aparecem na tela e NÃO estão no seu detalhes_mlbs.json "
                      f"(desta conta): {t(', '.join(sem_registro))}[/yellow]")
    else:
        console.print("[green]Todos os códigos da tela estão no seu detalhes_mlbs.json.[/green]")


# ---------------------------------------------------------------------------
# PARTE B — chamadas à API
# ---------------------------------------------------------------------------
def consultar(endpoint: str, params: dict = None) -> dict:
    """1 chamada GET. Erro da API (404, 403...) NÃO derruba o script: vira um registro com 'erro'.
    Só a autenticação recusada (401) interrompe tudo, porque nenhuma chamada seguinte funcionaria."""
    try:
        resposta = chamar_api(
            "GET", endpoint,
            pasta_logs=PASTA_LOGS, conta=CONTA,
            params=params, nome_log=NOME_LOG,
        )
    except ErroAutenticacaoAPI:
        raise
    except ErroAPI as erro:
        return {"endpoint": endpoint, "params": params, "status_http": None,
                "x_content_missing": None, "erro": str(erro), "corpo": None}

    try:
        corpo = resposta.json()
        texto_se_nao_json = None
    except ValueError:
        corpo = None
        texto_se_nao_json = resposta.text[:500]

    return {
        "endpoint": endpoint, "params": params,
        "status_http": resposta.status_code,
        # 206 = a API devolveu o que tinha; este header diz quais blocos ficaram faltando.
        "x_content_missing": resposta.headers.get("X-Content-Missing"),
        "erro": None, "corpo": corpo, "texto_se_nao_json": texto_se_nao_json,
    }


def campos_novos(corpo, chaves_doc: dict) -> list:
    """Chaves que a API mandou e a doc não cita, como 'bloco.chave'."""
    novos = []
    if not isinstance(corpo, dict):
        return novos
    for bloco, esperadas in chaves_doc.items():
        objeto = corpo if bloco == "(raiz)" else corpo.get(bloco)
        if isinstance(objeto, dict):
            for chave in objeto:
                if chave not in esperadas:
                    novos.append(chave if bloco == "(raiz)" else f"{bloco}.{chave}")
    return novos


def mostrar_status(titulo: str, resultado: dict) -> bool:
    """Imprime o resultado HTTP; devolve True se há corpo pra mostrar."""
    if resultado["erro"]:
        console.print(f"[red]{titulo}: {t(resultado['erro'])}[/red]")
        return False
    linha = f"[green]{titulo}: HTTP {resultado['status_http']}[/green]"
    if resultado.get("x_content_missing"):
        linha += f"  [yellow]X-Content-Missing: {t(resultado['x_content_missing'])}[/yellow]"
    console.print(linha)
    if resultado["corpo"] is None:
        console.print(f"[yellow]  resposta não veio em JSON: {t(resultado.get('texto_se_nao_json'))}[/yellow]")
        return False
    return True


def mostrar_estoque(resultado: dict) -> None:
    if not mostrar_status("Estoque Fulfillment", resultado):
        return
    corpo = resultado["corpo"]
    detalhe = pega(corpo, "not_available_detail")
    if isinstance(detalhe, list) and detalhe:
        texto_detalhe = ", ".join(f"{d.get('status')}={d.get('quantity')}" for d in detalhe if isinstance(d, dict))
    else:
        texto_detalhe = "-"
    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("Campo (da API)")
    tabela.add_column("Valor")
    tabela.add_row("total", t(pega(corpo, "total")))
    tabela.add_row("available_quantity  (= Aptas?)", t(pega(corpo, "available_quantity")))
    tabela.add_row("not_available_quantity", t(pega(corpo, "not_available_quantity")))
    tabela.add_row("not_available_detail", t(texto_detalhe))
    tabela.add_row("external_references", t(compacto(pega(corpo, "external_references"))))
    console.print(tabela)
    novos = campos_novos(corpo, CHAVES_DOC_ESTOQUE)
    if novos:
        console.print(f"[magenta]Campos que a doc não cita: {t(', '.join(novos))}[/magenta]")


def mostrar_reposicao(resultado: dict) -> None:
    if not mostrar_status("Reposição", resultado):
        return
    corpo = resultado["corpo"]
    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("Campo (da API)")
    tabela.add_column("Valor")
    linhas = [
        ("identifiers.user_product_id", pega(corpo, "identifiers", "user_product_id")),
        ("identifiers.inventory_id  (= Código ML)", pega(corpo, "identifiers", "inventory_id")),
        ("identifiers.seller_sku", pega(corpo, "identifiers", "seller_sku")),
        ("product.tags  (star_product = ESTRELA)", compacto(pega(corpo, "product", "tags"))),
        ("stock.total_stock", pega(corpo, "stock", "total_stock")),
        ("stock.shipping_urgency  (= Urgência)", pega(corpo, "stock", "shipping_urgency")),
        ("stock.minimum_distributable_stock  (= Mínimo)", pega(corpo, "stock", "minimum_distributable_stock")),
        ("sales.sales_totals  (= Vendas no Full)", compacto(pega(corpo, "sales", "sales_totals"))),
        ("recommendation.recommendation_type", pega(corpo, "recommendation", "recommendation_type")),
        ("recommendation.suggested_quantity  (= Sugestão)", compacto(pega(corpo, "recommendation", "suggested_quantity"))),
        ("recommendation.replenishment_deadline", pega(corpo, "recommendation", "replenishment_deadline")),
        ("recommendation.replenishment_frequency", pega(corpo, "recommendation", "replenishment_frequency")),
        ("eligibility_benefits  (AGING = estoque antigo?)", compacto(pega(corpo, "eligibility_benefits"))),
    ]
    for campo, valor in linhas:
        tabela.add_row(t(campo), t(valor))

    historico = pega(corpo, "sales", "sales_history")
    if isinstance(historico, list):
        for semana in historico:
            if isinstance(semana, dict):
                tabela.add_row(
                    "sales.sales_history",
                    t(f"{semana.get('start_date')} a {semana.get('end_date')}: "
                      f"{semana.get('units_sold')} un., {semana.get('days_out_of_stock')} dia(s) sem estoque, "
                      f"campanhas={compacto(semana.get('campaigns'))}"),
                )
    console.print(tabela)
    novos = campos_novos(corpo, CHAVES_DOC_REPOSICAO)
    if novos:
        console.print(f"[magenta]Campos que a doc não cita: {t(', '.join(novos))}[/magenta]")


def rotulo_da_tela(registro: dict) -> str:
    """Como a tela chamaria esta linha: o Código ML (inventory_id) ou '#<número do MLB>'."""
    inv = registro.get("inventory_id")
    if inv:
        return str(inv)
    return "#" + re.sub(r"\D", "", str(registro.get("mlb") or ""))


def mostrar_resumo(saida_alvos: list) -> None:
    """1 linha por registro, lado a lado — é o quadro pra comparar com a tela. Dois quadros (estoque e
    recomendação) pra caber na largura do terminal sem espremer as colunas."""
    quadro_estoque = Table(title="Resumo 1/2 — estoque e urgência (tela x API)")
    colunas(quadro_estoque, "tela", "mlb", "HTTP reposição", "tags", "total_stock", "aptas (estoque)",
            "total - aptas", "urgência", "mínimo")
    quadro_reco = Table(title="Resumo 2/2 — vendas e recomendação (tela x API)")
    colunas(quadro_reco, "tela", "vendas 30d (un.)", "tipo da recomendação", "sugestão", "prazo", "benefícios")

    for item in saida_alvos:
        r = item["registro_local"]
        rep = (item.get("reposicao") or {})
        est = (item.get("estoque") or {})
        corpo = rep.get("corpo")
        corpo_est = est.get("corpo")

        if not item.get("reposicao"):
            http = "sem user_product_id"
        elif rep.get("erro"):
            http = "erro"
        else:
            http = str(rep.get("status_http"))

        total_stock = pega(corpo, "stock", "total_stock")
        aptas = pega(corpo_est, "available_quantity")
        diferenca = (total_stock - aptas) if isinstance(total_stock, int) and isinstance(aptas, int) else None

        quadro_estoque.add_row(
            t(rotulo_da_tela(r)), t(r.get("mlb")), t(http),
            t(compacto(pega(corpo, "product", "tags"))),
            t(total_stock), t(aptas), t(diferenca),
            t(pega(corpo, "stock", "shipping_urgency")),
            t(pega(corpo, "stock", "minimum_distributable_stock")),
        )
        quadro_reco.add_row(
            t(rotulo_da_tela(r)),
            t(compacto(pega(corpo, "sales", "sales_totals", "units_sold"))),
            t(pega(corpo, "recommendation", "recommendation_type")),
            t(compacto(pega(corpo, "recommendation", "suggested_quantity"))),
            t(pega(corpo, "recommendation", "replenishment_deadline")),
            t(compacto(pega(corpo, "eligibility_benefits"))),
        )
    console.print(quadro_estoque)
    console.print(quadro_reco)
    console.print("[dim]'total - aptas' = total_stock da reposição menos available_quantity do estoque: "
                  "candidato a 'a caminho' (+ em transferência). Só aparece quando os dois existem.[/dim]")


def salvar_saida(conteudo: dict) -> None:
    with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=2)
    console.print(f"\n[bold]Arquivo salvo:[/bold] {t(CAMINHO_SAIDA)}")


def main() -> None:
    if CONTA not in PASTA_DETALHES_POR_CONTA:
        console.print(f"[red]CONTA inválida: {t(CONTA)}. Use {list(PASTA_DETALHES_POR_CONTA)}.[/red]")
        sys.exit(1)

    # ---------------- PARTE A ----------------
    console.rule("[bold]PARTE A — o que o seu sistema já sabe (sem API)")
    registros, gerado_em = carregar_detalhes(CONTA)
    if registros is None:
        sys.exit(1)

    resumo_universo = resumir_universo(registros, gerado_em)
    mostrar_universo(resumo_universo)
    console.print("[dim]Pra comparar: a tela (conta MB) mostrou 4.671 resultados (linhas), incluindo produtos que nunca "
                  "estiveram no Full. Compare com 'TODOS_user_product_ids_distintos…', não só com os números 'full_…'.[/dim]")

    alvos, sem_registro = achar_alvos(registros)
    mostrar_alvos(alvos, sem_registro)

    saida = {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "conta": CONTA,
        "sku": SKU_LIMPO,
        "codigos_da_tela": CODIGOS_DA_TELA,
        "codigos_da_tela_sem_registro_no_sistema": sem_registro,
        "universo_local": resumo_universo,
        "alvos": [],
    }

    if not alvos:
        console.print("[red]Nenhum registro do SKU nem dos códigos da tela no detalhes_mlbs.json — "
                      "nada pra consultar. Confira SKU/CONTA ou atualize com buscar_detalhes.[/red]")
        salvar_saida(saida)
        sys.exit(1)

    if not CONSULTAR_API:
        for alvo in alvos:
            saida["alvos"].append({
                "registro_local": {c: alvo["registro"].get(c) for c in CAMPOS_LOCAIS},
                "achado_por": sorted(alvo["motivos"]),
            })
        console.print("\n[yellow]CONSULTAR_API = False — parte B não executada (nenhuma chamada à API foi feita).[/yellow]")
        salvar_saida(saida)
        return

    # ---------------- PARTE B ----------------
    inventarios = sorted({a["registro"]["inventory_id"] for a in alvos if a["registro"].get("inventory_id")})
    user_products = sorted({a["registro"]["user_product_id"] for a in alvos if a["registro"].get("user_product_id")})
    total_chamadas = len(inventarios) + len(user_products)

    console.rule("[bold]PARTE B — consulta à API (só GET)")
    console.print(f"user_product_id distintos (reposição): {len(user_products)}  •  "
                  f"inventory_id distintos (estoque): {len(inventarios)}  •  "
                  f"chamadas GET que serão feitas: {total_chamadas}")
    sem_up = [a for a in alvos if not a["registro"].get("user_product_id")]
    if sem_up:
        console.print(f"[yellow]{len(sem_up)} registro(s) sem user_product_id no detalhes_mlbs.json — "
                      f"a API de reposição não tem como ser chamada pra eles.[/yellow]")

    cache_estoque = {}
    cache_reposicao = {}
    abortado = False
    try:
        for inv in inventarios:
            cache_estoque[inv] = consultar(ENDPOINT_ESTOQUE.format(inventory_id=inv))
        for upid in user_products:
            cache_reposicao[upid] = consultar(ENDPOINT_REPOSICAO.format(user_product_id=upid), params={"country": "BR"})
    except ErroAutenticacaoAPI as erro:
        console.print(f"[red]A API recusou o token (401): {t(erro)} — interrompendo as próximas consultas.[/red]")
        abortado = True

    # Monta a saída e mostra os quadros detalhados (só pra quem já esteve no Full — os outros ficam no resumo).
    for alvo in alvos:
        r = alvo["registro"]
        inv = r.get("inventory_id")
        upid = r.get("user_product_id")
        item = {
            "registro_local": {c: r.get(c) for c in CAMPOS_LOCAIS},
            "achado_por": sorted(alvo["motivos"]),
            "estoque": cache_estoque.get(inv) if inv else None,
            "reposicao": cache_reposicao.get(upid) if upid else None,
        }
        saida["alvos"].append(item)

        if inv and (item["estoque"] or item["reposicao"]):
            console.rule(f"[bold]{t(rotulo_da_tela(r))}  (mlb {t(r.get('mlb'))}, user_product_id {t(upid)})")
            if item["estoque"]:
                mostrar_estoque(item["estoque"])
            if item["reposicao"]:
                mostrar_reposicao(item["reposicao"])

    console.rule("[bold]Resumo")
    mostrar_resumo(saida["alvos"])

    salvar_saida(saida)
    if abortado:
        console.print("[red]Execução interrompida por erro de autenticação — o arquivo tem só o que foi consultado até aqui.[/red]")
        sys.exit(1)
    console.print("Suba esse arquivo na conversa pra eu comparar campo a campo com o HTML da tela.")


if __name__ == "__main__":
    main()
