# scripts_exploracao_ML/ficha_full_por_codigo.py
#
# Função Objetivo: montar a "ficha" de UM código da tela "Gestão de estoque Full ->
# Planejamento de envios" (o "Código ML", ex.: OPXW24140), mostrando cada valor
# organizado por assunto e SEMPRE dizendo de onde ele veio:
#   - de qual fonte (REPOS, ESTOQUE, ARQUIVO ou só a TELA),
#   - qual campo exato daquela fonte,
#   - e se o endpoint é NOVO (nenhum outro código do projeto chama) ou JÁ USADO
#     (o script procura nos .py do projeto na hora de rodar e mostra onde achou).
#
# As 3 fontes que este script usa (a 4ª, a TELA, é o HTML que você compara na mão):
#   REPOS   GET /marketplace/fbm/user-products/{user_product_id}/replenishment?country=BR
#           = os dados da própria tela "Planejamento de envios" (vendas, urgência,
#             mínimo, sugestão, Estrela, estoque antigo).
#   ESTOQUE GET /inventories/{inventory_id}/stock/fulfillment
#           = o estoque do Full detalhado: apto, não apto e o motivo.
#   ARQUIVO integracao_mercado_livre/Arquivos_API/<Magazine|Samvale>/detalhes_mlbs.json
#           = NÃO é chamada nova: é o arquivo que o comando buscar_detalhes grava
#             (via GET /items?ids=..., já usado no projeto). É uma FOTO do dia em que
#             você rodou o comando — a coluna "estoque do anúncio" vem daqui.
#
# Quantas chamadas faz: no máximo 1 de estoque + 1 de reposição por user_product_id
# do código (normalmente 2 no total). O script mostra a lista ANTES de chamar.
#
# Só leitura (só GET). Não toca no banco. Só roda quando VOCÊ executa o script.
#
# Arquivo de saída (o .gitignore já cobre pela regra "scripts_exploracao_ML/*.json"):
#   ficha_full_<CODIGO>.json -> retorno CRU das APIs + os registros do arquivo local.
#
# Como rodar:
#   poetry run python scripts_exploracao_ML/ficha_full_por_codigo.py

import json
import os
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
from rich.panel import Panel
from rich.table import Table

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

console = Console()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"            # "MB" (Magazine) ou "SV" (Samvale)
CODIGO = "QAVX18725"    # o "Código ML" da tela. Linha sem Código ML na tela = "#<número do MLB>", ex.: "#5838589786"
# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
PASTA_LOGS = PASTA_SCRIPT / "logs"
NOME_LOG = "ficha_full_por_codigo"

PASTA_DETALHES_POR_CONTA = {"MB": "Magazine", "SV": "Samvale"}
NOME_COMANDO_POR_CONTA = {"MB": "magazine", "SV": "samvale"}

ENDPOINT_ESTOQUE = "/inventories/{inventory_id}/stock/fulfillment"
ENDPOINT_REPOSICAO = "/marketplace/fbm/user-products/{user_product_id}/replenishment"

# Como o script descobre se um endpoint é NOVO ou JÁ USADO: procura estes trechos nos .py do projeto.
# Os 2 scripts de investigação do Full e o cliente_api.py (só o transporte, cujo docstring cita "/items"
# de exemplo) ficam de fora — o que interessa é se OUTRO código do projeto já chama o endpoint.
FONTES = {
    "REPOS": {
        "cor": "cyan",
        "nome": 'API de reposição (os dados da própria tela "Planejamento de envios")',
        "padroes": [r"/marketplace/fbm/"],
    },
    "ESTOQUE": {
        "cor": "green",
        "nome": "API de estoque do Full (apto, não apto e o motivo)",
        "padroes": [r"/inventories/", r"stock/fulfillment"],
    },
    "ARQUIVO": {
        "cor": "yellow",
        "nome": "seu detalhes_mlbs.json (foto gravada pelo comando buscar_detalhes)",
        "padroes": [r"""["']/items["']"""],
    },
}
PASTAS_IGNORADAS = {"venv", "env", "node_modules", "site-packages", "__pycache__", "migrations"}
ARQUIVOS_IGNORADOS = {"investigar_full_reposicao.py", "ficha_full_por_codigo.py", "cliente_api.py"}

# Traduções só pra ajudar a leitura (o valor original da API aparece sempre ao lado).
URGENCIA = {"URGENT": "urgente", "THIS_WEEK": "esta semana", "NEXT_WEEK": "próxima semana",
            "IN_TWO_WEEKS": "em 2 semanas", "NO_URGENCY": "sem urgência", "EXCEDENT": "excedente"}
RECOMENDACAO = {"REPLENISH": "repor", "NO_REPLENISHMENT": "não repor",
                "NO_REPLENISHMENT_BY_RESTRICTION": "não repor, por restrição"}
MOTIVO_INDISPONIVEL = {"damaged": "danificada", "lost": "perdida", "withdrawal": "em retirada",
                       "internal_process": "em processo interno", "transfer": "em transferência",
                       "noFiscalCoverage": "sem cobertura fiscal", "not_supported": "não suportada"}

# Chaves que a DOC cita em cada resposta. Tudo que a API mandar fora disso aparece como "campo fora da doc".
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

# Campos do registro do arquivo que vão pro JSON de saída.
CAMPOS_LOCAIS = (
    "mlb", "variacao_id", "variacao_atributos", "sku", "status", "logistic_type",
    "available_quantity", "user_product_id", "inventory_id", "title",
)


# ---------------------------------------------------------------------------
# Apoio: formatação
# ---------------------------------------------------------------------------
def t(valor) -> str:
    """Texto vindo da API/arquivo pode ter colchetes; o rich leria como formatação — escapa antes de mostrar."""
    return escape(str(valor))


def vazio() -> str:
    return "[dim]— (vazio)[/dim]"


def v(valor) -> str:
    """Valor pra mostrar numa célula: None vira '— (vazio)'."""
    return vazio() if valor is None else t(valor)


def n_br(valor) -> str:
    """1234 -> '1.234'   |   88848.09 -> '88.848,09'"""
    if isinstance(valor, bool) or valor is None:
        return v(valor)
    if isinstance(valor, int):
        return f"{valor:,}".replace(",", ".")
    if isinstance(valor, float):
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return t(valor)


def compacto(valor) -> str:
    return json.dumps(valor, ensure_ascii=False)


def pega(objeto, *caminho):
    """objeto["a"]["b"]... sem quebrar quando algum nível é null/ausente."""
    for chave in caminho:
        if not isinstance(objeto, dict):
            return None
        objeto = objeto.get(chave)
    return objeto


def primeiro(lista, chave):
    """lista[0][chave] sem quebrar (a API manda gmv e units_sold como [{"full": N}])."""
    if isinstance(lista, list) and lista and isinstance(lista[0], dict):
        return lista[0].get(chave)
    return None


def tag(fonte: str) -> str:
    if fonte == "TELA":
        return "[bold white on grey37] TELA [/]"
    return f"[bold {FONTES[fonte]['cor']}]{fonte}[/]"


def colunas(tabela: Table, *nomes: str) -> None:
    """Colunas que quebram o texto em vez de cortar com '…' (código e MLB têm que aparecer inteiros)."""
    for nome in nomes:
        tabela.add_column(nome, overflow="fold")


# ---------------------------------------------------------------------------
# "Este endpoint é NOVO ou já usado?" — resposta tirada do código do projeto, na hora
# ---------------------------------------------------------------------------
def procurar_uso_no_projeto(padroes: list) -> list:
    """[(arquivo relativo, nº da 1ª linha)] dos .py do projeto que citam algum dos padrões (fora comentários)."""
    achados = []
    for pasta, subpastas, arquivos in os.walk(_RAIZ_DO_PROJETO):
        subpastas[:] = [p for p in subpastas if p not in PASTAS_IGNORADAS and not p.startswith(".")]
        for nome in arquivos:
            if not nome.endswith(".py") or nome in ARQUIVOS_IGNORADOS:
                continue
            caminho = Path(pasta) / nome
            try:
                linhas = caminho.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for numero, linha in enumerate(linhas, 1):
                if linha.lstrip().startswith("#"):
                    continue
                if any(re.search(p, linha) for p in padroes):
                    achados.append((caminho.relative_to(_RAIZ_DO_PROJETO).as_posix(), numero))
                    break
    return sorted(achados)


def descobrir_uso_de_todas_as_fontes() -> dict:
    return {fonte: procurar_uso_no_projeto(info["padroes"]) for fonte, info in FONTES.items()}


def situacao(fonte: str, uso: dict) -> str:
    """Curto, pra coluna 'Endpoint' das tabelas."""
    if fonte == "TELA":
        return "[dim]não é endpoint[/dim]"
    return "[bold green]JÁ USADO[/]" if uso.get(fonte) else "[bold magenta]NOVO[/]"


def situacao_por_extenso(fonte: str, uso: dict) -> str:
    achados = uso.get(fonte) or []
    if not achados:
        return "[bold magenta]NOVO[/] — nenhum .py do projeto (fora estes scripts de investigação) chama esse endpoint"
    lista = ", ".join(f"{t(arq)}:{n}" for arq, n in achados[:3])
    extra = f" (+{len(achados) - 3} outro(s) arquivo(s))" if len(achados) > 3 else ""
    return f"[bold green]JÁ USADO[/] em {lista}{extra}"


# ---------------------------------------------------------------------------
# PASSO 1 — leitura local (ARQUIVO)
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


def interpretar_codigo(codigo: str):
    """'#2616936722' -> ('mlb', 'MLB2616936722');  'OPXW24140' -> ('inventory_id', 'OPXW24140')."""
    c = str(codigo).strip().upper()
    if c.startswith("#"):
        return ("mlb", "MLB" + re.sub(r"\D", "", c))
    return ("inventory_id", c)


def registros_do_codigo(registros: list, tipo: str, valor: str) -> list:
    achados = []
    for r in registros:
        if tipo == "inventory_id" and str(r.get("inventory_id") or "").strip().upper() == valor:
            achados.append(r)
        elif tipo == "mlb" and str(r.get("mlb") or "").strip().upper() == valor:
            achados.append(r)
    return achados


# ---------------------------------------------------------------------------
# PASSO 2 — chamadas à API
# ---------------------------------------------------------------------------
def consultar(endpoint: str, params: dict = None) -> dict:
    """1 chamada GET. Erro da API (404, 403...) NÃO derruba o script: vira um registro com 'erro'.
    Só a autenticação recusada (401) interrompe tudo, porque nenhuma chamada seguinte funcionaria."""
    try:
        resposta = chamar_api("GET", endpoint, pasta_logs=PASTA_LOGS, conta=CONTA,
                              params=params, nome_log=NOME_LOG)
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


def campos_fora_da_doc(corpo, chaves_doc: dict) -> list:
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


def texto_http(resultado) -> str:
    if resultado is None:
        return "[dim]não chamada[/dim]"
    if resultado["erro"]:
        return f"[red]ERRO — {t(resultado['erro'])}[/red]"
    texto = f"[green]HTTP {resultado['status_http']}[/green]"
    if resultado.get("x_content_missing"):
        texto += f"  [yellow]X-Content-Missing: {t(resultado['x_content_missing'])}[/yellow]"
    if resultado["corpo"] is None:
        texto += f"  [yellow]resposta não veio em JSON: {t(resultado.get('texto_se_nao_json'))}[/yellow]"
    return texto


# ---------------------------------------------------------------------------
# A TELA DO SCRIPT
# ---------------------------------------------------------------------------
def mostrar_fontes(uso: dict, endpoint_estoque, endpoints_reposicao: list, res_estoque, res_reposicao: dict,
                   gerado_em, quantos_registros: int) -> None:
    console.rule("[bold]DE ONDE VÊM OS DADOS (as fontes usadas nesta ficha)")

    corpo_rep = [r["corpo"] for r in res_reposicao.values() if r and r.get("corpo")]
    linhas = [
        f"[bold]Fonte[/bold]     {tag('REPOS')}  {FONTES['REPOS']['nome']}",
    ]
    for upid, endpoint in endpoints_reposicao:
        res = res_reposicao.get(upid)
        linhas.append(f"[bold]Endpoint[/bold]  GET {t(endpoint)}?country=BR")
        linhas.append(f"[bold]Resultado[/bold] {texto_http(res)}")
    if not endpoints_reposicao:
        linhas.append("[bold]Endpoint[/bold]  [dim]não chamado: nenhum registro com user_product_id no seu arquivo[/dim]")
    linhas.append(f"[bold]No projeto[/bold] {situacao_por_extenso('REPOS', uso)}")
    novos = sorted({c for corpo in corpo_rep for c in campos_fora_da_doc(corpo, CHAVES_DOC_REPOSICAO)})
    linhas.append("[bold]Fora da doc[/bold] " + (f"[magenta]{t(', '.join(novos))}[/magenta]" if novos else "[dim]nenhum campo[/dim]"))
    console.print(Panel("\n".join(linhas), border_style=FONTES["REPOS"]["cor"], expand=False))

    linhas = [f"[bold]Fonte[/bold]     {tag('ESTOQUE')}  {FONTES['ESTOQUE']['nome']}"]
    if endpoint_estoque:
        linhas.append(f"[bold]Endpoint[/bold]  GET {t(endpoint_estoque)}")
        linhas.append(f"[bold]Resultado[/bold] {texto_http(res_estoque)}")
    else:
        linhas.append("[bold]Endpoint[/bold]  [dim]não chamado: este código não tem inventory_id (nunca esteve no Full)[/dim]")
    linhas.append(f"[bold]No projeto[/bold] {situacao_por_extenso('ESTOQUE', uso)}")
    novos = campos_fora_da_doc((res_estoque or {}).get("corpo"), CHAVES_DOC_ESTOQUE)
    linhas.append("[bold]Fora da doc[/bold] " + (f"[magenta]{t(', '.join(novos))}[/magenta]" if novos else "[dim]nenhum campo[/dim]"))
    console.print(Panel("\n".join(linhas), border_style=FONTES["ESTOQUE"]["cor"], expand=False))

    linhas = [
        f"[bold]Fonte[/bold]     {tag('ARQUIVO')}  {FONTES['ARQUIVO']['nome']}",
        f"[bold]Arquivo[/bold]   {t(caminho_detalhes(CONTA).relative_to(_RAIZ_DO_PROJETO).as_posix())}",
        f"[bold]Endpoint[/bold]  nenhuma chamada agora. O arquivo foi gravado pelo buscar_detalhes com GET /items?ids=MLB1,MLB2,... "
        f"(até 20 por lote)",
        f"[bold]Foto de[/bold]   {t(gerado_em) if gerado_em else '[dim]data não registrada no arquivo[/dim]'}  "
        f"[dim](o que está no arquivo NÃO acompanha o ML sozinho)[/dim]",
        f"[bold]No projeto[/bold] {situacao_por_extenso('ARQUIVO', uso)}",
        f"[bold]Neste código[/bold] {quantos_registros} registro(s) (anúncio ou variação) no arquivo",
    ]
    console.print(Panel("\n".join(linhas), border_style=FONTES["ARQUIVO"]["cor"], expand=False))

    console.print(f"Existe ainda a fonte {tag('TELA')}: o HTML que você salva da página. O script não lê o HTML — "
                  f"as linhas marcadas TELA abaixo dizem o que só existe nele.")


def nova_tabela(titulo: str) -> Table:
    tabela = Table(title=titulo, title_justify="left", header_style="bold", show_lines=False)
    colunas(tabela, "Informação (nome na tela)", "Valor", "Fonte", "Campo exato", "Endpoint (no projeto)")
    return tabela


def linha(tabela: Table, uso: dict, info: str, valor: str, fonte: str, campo: str) -> None:
    tabela.add_row(t(info), valor, tag(fonte), t(campo) if campo else "[dim]—[/dim]", situacao(fonte, uso))


def valor_da_tela(texto: str) -> str:
    return f"[dim]{t(texto)}[/dim]"


def bloco_identificacao(uso, corpo_rep, registros_arquivo) -> None:
    tabela = nova_tabela("BLOCO 1 — Quem é o produto")
    tags = pega(corpo_rep, "product", "tags")
    if isinstance(tags, list):
        estrela = "[bold]SIM[/bold]" if "star_product" in tags else "não"
        valor_estrela = f"{estrela}  [dim](star_product nas tags = {t(compacto(tags))})[/dim]"
    else:
        valor_estrela = vazio()
    ativo = next((r for r in registros_arquivo if str(r.get("status")) == "active"), None)
    base = ativo or (registros_arquivo[0] if registros_arquivo else {})
    variacoes = sorted({str(r.get("variacao_atributos")) for r in registros_arquivo if r.get("variacao_atributos")})

    linha(tabela, uso, "Código ML (inventory_id)", v(pega(corpo_rep, "identifiers", "inventory_id")),
          "REPOS", "identifiers.inventory_id")
    linha(tabela, uso, "Produto do vendedor (user_product_id)", v(pega(corpo_rep, "identifiers", "user_product_id")),
          "REPOS", "identifiers.user_product_id")
    linha(tabela, uso, "SKU", v(pega(corpo_rep, "identifiers", "seller_sku")), "REPOS", "identifiers.seller_sku")
    linha(tabela, uso, "ESTRELA", valor_estrela, "REPOS", "product.tags")
    linha(tabela, uso, "Título do produto", v(base.get("title")), "ARQUIVO", "title")
    linha(tabela, uso, "Variação (ex.: cor)",
          t(" | ".join(variacoes)) if variacoes else "[dim]— (vazio: só existe se o anúncio tem variações)[/dim]",
          "ARQUIVO", "variacao_atributos")
    linha(tabela, uso, "Tamanho do produto",
          valor_da_tela("PEQUENO / MÉDIO / GRANDE / EXTRAGRANDE — só na tela"), "TELA", "")
    linha(tabela, uso, '"+ N identificadores"',
          valor_da_tela("não sei o que são — o texto aparece ao passar o mouse e o HTML salvo não guarda"), "TELA", "")
    console.print(tabela)
    console.print("[dim]O título vem do anúncio ativo (se não houver, do primeiro registro do código).[/dim]")


def bloco_estoque(uso, corpo_rep, corpo_est, registros_arquivo) -> None:
    tabela = nova_tabela("BLOCO 2 — Estoque")
    detalhe = pega(corpo_est, "not_available_detail")
    if isinstance(detalhe, list) and detalhe:
        texto_detalhe = ", ".join(
            f"{d.get('status')}={d.get('quantity')} ({MOTIVO_INDISPONIVEL.get(d.get('status'), 'motivo não traduzido')})"
            for d in detalhe if isinstance(d, dict))
    else:
        texto_detalhe = "nenhuma unidade indisponível"
    por_anuncio = "; ".join(
        f"{r.get('mlb')} ({r.get('status')}) = {r.get('available_quantity')}" for r in registros_arquivo) or None

    linha(tabela, uso, "Aptas e a caminho", n_br(pega(corpo_rep, "stock", "total_stock")),
          "REPOS", "stock.total_stock")
    linha(tabela, uso, "Aptas  /  A caminho (separados)",
          valor_da_tela("só na tela (a API dá só o total)"), "TELA", "")
    linha(tabela, uso, "Total no estoque do Full", n_br(pega(corpo_est, "total")), "ESTOQUE", "total")
    linha(tabela, uso, "Disponível para venda", n_br(pega(corpo_est, "available_quantity")),
          "ESTOQUE", "available_quantity")
    linha(tabela, uso, "Indisponível (total)", n_br(pega(corpo_est, "not_available_quantity")),
          "ESTOQUE", "not_available_quantity")
    linha(tabela, uso, "Indisponível (motivo)", t(texto_detalhe) if corpo_est else vazio(),
          "ESTOQUE", "not_available_detail[].status / .quantity")
    linha(tabela, uso, "Estoque do anúncio", t(por_anuncio) if por_anuncio else vazio(), "ARQUIVO",
          "available_quantity")
    linha(tabela, uso, "Mínimo (un. mínimas para envios rápidos)", n_br(pega(corpo_rep, "stock", "minimum_distributable_stock")),
          "REPOS", "stock.minimum_distributable_stock")
    console.print(tabela)
    console.print("[dim]Não some o 'estoque do anúncio' de vários registros: é o mesmo estoque do Full repetido em cada anúncio "
                  "do código. Para comparar com a tela: 'Aptas e a caminho' deve ser igual a stock.total_stock. O 'Aptas' sozinho "
                  "pode NÃO ser o available_quantity (hipótese: a tela pode contar as unidades indisponíveis) — só se "
                  "confirma salvando o HTML e rodando este script no mesmo momento.[/dim]")


def bloco_vendas(uso, corpo_rep) -> None:
    totais = pega(corpo_rep, "sales", "sales_totals")
    periodo = pega(totais, "period")
    unidades = primeiro(pega(totais, "units_sold"), "full")
    gmv = primeiro(pega(totais, "gmv"), "full")
    moeda = pega(totais, "currency")

    tabela = nova_tabela("BLOCO 3 — Vendas")
    linha(tabela, uso, "Vendas no Full — últ. 30 dias (un.)",
          f"{n_br(unidades)}  [dim](período = {t(periodo)})[/dim]" if unidades is not None else vazio(),
          "REPOS", "sales.sales_totals.units_sold[0].full")
    linha(tabela, uso, "Valor vendido no Full (a tela mostra sem centavos)",
          f"R$ {n_br(gmv)}  [dim]({t(moeda)})[/dim]" if gmv is not None else vazio(),
          "REPOS", "sales.sales_totals.gmv[0].full")
    linha(tabela, uso, "Tendência",
          valor_da_tela('ex.: "Sem tendência identificada" — só na tela'), "TELA", "")
    console.print(tabela)

    historico = pega(corpo_rep, "sales", "sales_history")
    semanas = Table(title=f"Histórico de vendas semanais   (fonte {tag('REPOS')}, campo sales.sales_history[], "
                          f"endpoint {situacao('REPOS', uso)})",
                    title_justify="left", header_style="bold")
    colunas(semanas, "Semana", "Un. vendidas", "Dias sem estoque", "Campanhas")
    if isinstance(historico, list) and historico:
        # A API manda da semana mais NOVA para a mais antiga; a tela mostra da mais antiga para a mais nova.
        for s in sorted((x for x in historico if isinstance(x, dict)), key=lambda x: str(x.get("start_date"))):
            semanas.add_row(t(f"{s.get('start_date')} a {s.get('end_date')}"), n_br(s.get("units_sold")),
                            n_br(s.get("days_out_of_stock")), t(compacto(s.get("campaigns"))))
        console.print(semanas)
        console.print("[dim]O script mostra da semana mais antiga para a mais nova (igual à tela); a API manda na ordem inversa.[/dim]")
    else:
        console.print("[dim]Histórico semanal: a API não mandou semanas para este produto (sales_history vazio/null).[/dim]")


def bloco_decisao(uso, corpo_rep) -> None:
    urgencia = pega(corpo_rep, "stock", "shipping_urgency")
    reco = pega(corpo_rep, "recommendation", "recommendation_type")
    sugestao = pega(corpo_rep, "recommendation", "suggested_quantity")
    beneficios = pega(corpo_rep, "eligibility_benefits")

    if isinstance(sugestao, dict) and sugestao.get("type") == "exact":
        texto_sugestao = f"{n_br(sugestao.get('value'))} un.  [dim](exata)[/dim]"
    elif isinstance(sugestao, dict) and sugestao.get("type") == "range":
        texto_sugestao = f"de {n_br(sugestao.get('min'))} a {n_br(sugestao.get('max'))} un.  [dim](faixa)[/dim]"
    else:
        texto_sugestao = vazio()

    if isinstance(beneficios, list):
        texto_beneficios = (f"{t(compacto(beneficios))}  [dim](lista vazia = nenhum benefício)[/dim]" if not beneficios
                            else t(compacto(beneficios)))
    else:
        texto_beneficios = vazio()

    tabela = nova_tabela("BLOCO 4 — O que fazer")
    linha(tabela, uso, "Urgência de envio",
          f"{t(urgencia)}  [dim](= {t(URGENCIA.get(urgencia, 'valor não traduzido'))})[/dim]" if urgencia else vazio(),
          "REPOS", "stock.shipping_urgency")
    linha(tabela, uso, "Sugestão de envio", texto_sugestao, "REPOS", "recommendation.suggested_quantity")
    linha(tabela, uso, 'Observações (ex.: "Recomendamos não repor…")',
          f"{t(reco)}  [dim](= {t(RECOMENDACAO.get(reco, 'valor não traduzido'))})[/dim]" if reco else vazio(),
          "REPOS", "recommendation.recommendation_type")
    linha(tabela, uso, "Prazo para repor", v(pega(corpo_rep, "recommendation", "replenishment_deadline")),
          "REPOS", "recommendation.replenishment_deadline")
    linha(tabela, uso, "Frequência de reposição (semanas)", v(pega(corpo_rep, "recommendation", "replenishment_frequency")),
          "REPOS", "recommendation.replenishment_frequency")
    linha(tabela, uso, '"Sem isenção em estoque antigo"', texto_beneficios, "REPOS", "eligibility_benefits")
    console.print(tabela)
    console.print("[dim]Hipóteses ainda em teste: a frase 'Sem isenção em estoque antigo' aparece na tela quando a lista "
                  "eligibility_benefits tem AGING; e o texto de 'Observações' ('Recomendamos não repor, pois…') é montado pela "
                  "própria tela a partir de recommendation_type.[/dim]")


def bloco_anuncios(uso, registros_arquivo) -> None:
    tabela = Table(title=f"BLOCO 5 — Anúncios do seu arquivo ligados a este código   (fonte {tag('ARQUIVO')}, "
                         f"endpoint {situacao('ARQUIVO', uso)}: GET /items)",
                   title_justify="left", header_style="bold")
    colunas(tabela, "mlb", "variação", "status", "tipo logístico", "estoque do anúncio", "SKU", "título")
    for r in registros_arquivo:
        tabela.add_row(t(r.get("mlb")), v(r.get("variacao_id")), t(r.get("status")), t(r.get("logistic_type")),
                       n_br(r.get("available_quantity")), v(r.get("sku")), v(r.get("title")))
    console.print(tabela)
    if len(registros_arquivo) > 1:
        console.print("[yellow]Mais de um registro para o mesmo código: eles compartilham o mesmo estoque do Full. "
                      "No relatório, agrupe por Código ML (ou user_product_id) — nunca some anúncio por anúncio.[/yellow]")


def conferir(tabela: Table, verificacao: str, igual, detalhe: str) -> None:
    if igual is None:
        resultado = "[dim]NÃO DÁ PRA CONFERIR[/dim]"
    elif igual:
        resultado = "[bold green]IGUAL[/]"
    else:
        resultado = "[bold red]DIFERENTE[/]"
    tabela.add_row(verificacao, resultado, detalhe)


def bloco_conferencias(codigo_tipo, codigo_valor, corpo_rep, corpo_est, registros_arquivo, gerado_em) -> None:
    tabela = Table(title="BLOCO 6 — Conferências automáticas entre as fontes", title_justify="left", header_style="bold")
    colunas(tabela, "Verificação", "Resultado", "Detalhe")

    inv_rep = pega(corpo_rep, "identifiers", "inventory_id")
    if codigo_tipo == "inventory_id":
        conferir(tabela, f"Código pedido ({t(codigo_valor)}) = {tag('REPOS')} identifiers.inventory_id",
                 None if inv_rep is None else str(inv_rep).upper() == codigo_valor, f"REPOS devolveu {v(inv_rep)}")

    upids_arquivo = {r.get("user_product_id") for r in registros_arquivo if r.get("user_product_id")}
    upid_rep = pega(corpo_rep, "identifiers", "user_product_id")
    conferir(tabela, f"user_product_id: {tag('REPOS')} x {tag('ARQUIVO')}",
             None if (upid_rep is None or not upids_arquivo) else upids_arquivo == {upid_rep},
             f"REPOS {v(upid_rep)}  •  ARQUIVO {t(', '.join(sorted(upids_arquivo))) if upids_arquivo else vazio()}")

    skus_arquivo = {str(r.get("sku")) for r in registros_arquivo if r.get("sku")}
    sku_rep = pega(corpo_rep, "identifiers", "seller_sku")
    conferir(tabela, f"SKU: {tag('REPOS')} x {tag('ARQUIVO')}",
             None if (sku_rep is None or not skus_arquivo) else skus_arquivo == {str(sku_rep)},
             f"REPOS {v(sku_rep)}  •  ARQUIVO {t(', '.join(sorted(skus_arquivo))) if skus_arquivo else vazio()}")

    total_rep = pega(corpo_rep, "stock", "total_stock")
    total_est = pega(corpo_est, "total")
    conferir(tabela, f"Total: {tag('REPOS')} stock.total_stock x {tag('ESTOQUE')} total",
             None if (total_rep is None or total_est is None) else total_rep == total_est,
             f"REPOS {n_br(total_rep)}  •  ESTOQUE {n_br(total_est)}")

    disp = pega(corpo_est, "available_quantity")
    indisp = pega(corpo_est, "not_available_quantity")
    conferir(tabela, f"{tag('ESTOQUE')}: total = disponível + indisponível",
             None if None in (total_est, disp, indisp) else total_est == disp + indisp,
             f"{n_br(total_est)} = {n_br(disp)} + {n_br(indisp)}")

    valores_anuncio = {r.get("available_quantity") for r in registros_arquivo if r.get("available_quantity") is not None}
    if not valores_anuncio or disp is None:
        igual = None
    else:
        igual = valores_anuncio == {disp}
    detalhe = (f"ARQUIVO {t(', '.join(str(x) for x in sorted(valores_anuncio))) if valores_anuncio else vazio()}  •  "
               f"ESTOQUE available_quantity {n_br(disp)}")
    if igual is False:
        detalhe += (f"  [dim](o ARQUIVO é foto de {t(gerado_em) if gerado_em else 'data desconhecida'}; "
                    f"rode o buscar_detalhes de novo para atualizar)[/dim]")
    conferir(tabela, f"Estoque do anúncio ({tag('ARQUIVO')}) x disponível ({tag('ESTOQUE')})", igual, detalhe)
    console.print(tabela)


def bloco_so_na_tela() -> None:
    tabela = Table(title="BLOCO 7 — Só existe na tela (nenhuma das APIs acima entrega)", title_justify="left", header_style="bold")
    colunas(tabela, "Item da tela", "O que sabemos")
    tabela.add_row("Tamanho do produto", "PEQUENO / MÉDIO / GRANDE / EXTRAGRANDE — só no HTML.")
    tabela.add_row("Aptas × A caminho", "A API só dá o total (stock.total_stock). A separação só existe na tela.")
    tabela.add_row("Tendência", 'Texto como "Sem tendência identificada" ou "+25% por alta demanda" — só no HTML.')
    tabela.add_row('Limites "Você pode enviar até N un."',
                   "São da CONTA (um para pequenos/médios, outro para grandes/extragrandes), mudam entre capturas — não são do produto.")
    tabela.add_row("Cartões do topo da página", 'Contagens por urgência ("ENVIE 48 esta semana…") e o resumo de Estrela — só no HTML.')
    console.print(tabela)


def montar_ficha(codigo_tipo, codigo_valor, uso, upid, res_rep, res_est, registros_arquivo, gerado_em) -> None:
    corpo_rep = (res_rep or {}).get("corpo")
    corpo_est = (res_est or {}).get("corpo")
    console.rule(f"[bold]FICHA — {t(CODIGO)}   •   user_product_id {t(upid) if upid else '(sem)'}   •   conta {CONTA}")
    bloco_identificacao(uso, corpo_rep, registros_arquivo)
    bloco_estoque(uso, corpo_rep, corpo_est, registros_arquivo)
    bloco_vendas(uso, corpo_rep)
    bloco_decisao(uso, corpo_rep)
    bloco_anuncios(uso, registros_arquivo)
    bloco_conferencias(codigo_tipo, codigo_valor, corpo_rep, corpo_est, registros_arquivo, gerado_em)


def salvar_saida(caminho: Path, conteudo: dict) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=2)
    console.print(f"\n[bold]Arquivo salvo:[/bold] {t(caminho)}")


def main() -> None:
    if CONTA not in PASTA_DETALHES_POR_CONTA:
        console.print(f"[red]CONTA inválida: {t(CONTA)}. Use {list(PASTA_DETALHES_POR_CONTA)}.[/red]")
        sys.exit(1)

    codigo_tipo, codigo_valor = interpretar_codigo(CODIGO)
    caminho_saida = PASTA_SCRIPT / f"ficha_full_{re.sub(r'[^A-Za-z0-9]+', '_', codigo_valor)}.json"

    console.rule(f"[bold]FICHA DO CÓDIGO {t(CODIGO)} — conta {CONTA} — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    console.print("Como ler: cada linha das tabelas traz o nome como aparece na tela, o valor, a FONTE do valor "
                  f"({tag('REPOS')}, {tag('ESTOQUE')}, {tag('ARQUIVO')} ou {tag('TELA')}), o campo exato dessa fonte "
                  "e se o endpoint é NOVO (nenhum outro código do projeto usa) ou JÁ USADO.")

    # ---------------- PASSO 1: ler o seu arquivo (sem API) ----------------
    registros, gerado_em = carregar_detalhes(CONTA)
    if registros is None:
        sys.exit(1)
    do_codigo = registros_do_codigo(registros, codigo_tipo, codigo_valor)
    console.print(f"Passo 1 — lendo o seu detalhes_mlbs.json (sem API): {len(do_codigo)} registro(s) com o código {t(CODIGO)}.")

    inventarios = sorted({r["inventory_id"] for r in do_codigo if r.get("inventory_id")})
    if codigo_tipo == "inventory_id" and codigo_valor not in {i.upper() for i in inventarios}:
        inventarios.append(codigo_valor)   # a tela mostrou esse Código ML mesmo que o arquivo não conheça: ainda dá pra consultar
    user_products = sorted({r["user_product_id"] for r in do_codigo if r.get("user_product_id")})

    # ---------------- PASSO 2: as chamadas (lista antes de chamar) ----------------
    endpoints_estoque = [ENDPOINT_ESTOQUE.format(inventory_id=i) for i in inventarios]
    endpoints_reposicao = [(u, ENDPOINT_REPOSICAO.format(user_product_id=u)) for u in user_products]
    total_chamadas = len(endpoints_estoque) + len(endpoints_reposicao)
    console.print(f"Passo 2 — chamadas GET que serão feitas agora: {total_chamadas}")
    for e in endpoints_estoque:
        console.print(f"   {tag('ESTOQUE')}  GET {t(e)}")
    for _, e in endpoints_reposicao:
        console.print(f"   {tag('REPOS')}  GET {t(e)}?country=BR")
    if not endpoints_reposicao:
        console.print("[yellow]   Nenhum user_product_id no seu arquivo para este código — a API de reposição não tem como ser chamada.[/yellow]")
    if not endpoints_estoque:
        console.print("[yellow]   Este código não tem inventory_id — a API de estoque não tem como ser chamada.[/yellow]")

    res_estoque_por_inv = {}
    res_reposicao = {}
    abortado = False
    try:
        for inv in inventarios:
            res_estoque_por_inv[inv] = consultar(ENDPOINT_ESTOQUE.format(inventory_id=inv))
        for upid in user_products:
            res_reposicao[upid] = consultar(ENDPOINT_REPOSICAO.format(user_product_id=upid), params={"country": "BR"})
    except ErroAutenticacaoAPI as erro:
        console.print(f"[red]A API recusou o token (401): {t(erro)} — interrompendo as próximas consultas.[/red]")
        abortado = True

    # ---------------- A FICHA ----------------
    uso = descobrir_uso_de_todas_as_fontes()
    inventario_principal = inventarios[0] if inventarios else None
    res_estoque = res_estoque_por_inv.get(inventario_principal) if inventario_principal else None
    endpoint_estoque = ENDPOINT_ESTOQUE.format(inventory_id=inventario_principal) if inventario_principal else None

    mostrar_fontes(uso, endpoint_estoque, endpoints_reposicao, res_estoque, res_reposicao, gerado_em, len(do_codigo))

    for upid in (user_products or [None]):
        registros_do_upid = [r for r in do_codigo if r.get("user_product_id") == upid] if upid else \
                            [r for r in do_codigo if not r.get("user_product_id")]
        montar_ficha(codigo_tipo, codigo_valor, uso, upid, res_reposicao.get(upid), res_estoque,
                     registros_do_upid, gerado_em)
    if len(inventarios) > 1:
        console.print(f"[yellow]Este código ligou {len(inventarios)} inventory_id diferentes: {t(', '.join(inventarios))}. "
                      f"A ficha mostra o estoque do primeiro; os demais estão no arquivo JSON.[/yellow]")

    bloco_so_na_tela()

    salvar_saida(caminho_saida, {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "conta": CONTA,
        "codigo": CODIGO,
        "arquivo_detalhes_gerado_em": gerado_em,
        "uso_no_projeto": {fonte: [f"{a}:{n}" for a, n in achados] for fonte, achados in uso.items()},
        "registros_do_arquivo": [{c: r.get(c) for c in CAMPOS_LOCAIS} for r in do_codigo],
        "estoque": res_estoque_por_inv,
        "reposicao": res_reposicao,
    })
    if abortado:
        console.print("[red]Execução interrompida por erro de autenticação — o arquivo tem só o que foi consultado até aqui.[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
