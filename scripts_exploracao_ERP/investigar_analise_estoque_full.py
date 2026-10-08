# scripts_exploracao_ERP/investigar_analise_estoque_full.py
#
# Função Objetivo: descobrir o que o método novo da Sysemp "listarAnaliseEstoqueFull" devolve — e se ele
# funciona nas DUAS empresas (Magazine = instância /61, Samvale = instância /84) — antes de qualquer código
# do sistema depender dele.
#
# A dúvida: a doc nova (documentacao_api_VSComercio.pdf, gerada em 08/10/2026) lista o método, mas só mostra
# o PEDIDO (POST com {"offset": ""}) — não mostra a RESPOSTA. A hipótese (só hipótese) é que ele traga o
# estoque do ERP ligado ao Full, o que poderia resolver os selos "NÃO CONFERIDO" da tela "Estoque no Full".
# Só uma chamada de verdade responde. Atenção: a doc é do VS Comércio (/84). Na Magazine (/61) o método pode
# nem existir — já aconteceu de um método responder "Metodo não Localizado" em uma das instâncias.
#
# O que o script faz, para cada empresa (só leitura, 1 chamada por empresa):
#   POST {URL_BASE}/listarAnaliseEstoqueFull   corpo: {"offset": "0"}   header: Token
#   - o token vem do .env da raiz do projeto: MB_SYSEMP_API_TOKEN e SV_SYSEMP_API_TOKEN (os mesmos que o
#     sistema já usa nos outros métodos da Sysemp). A URL vem de MB_/SV_SYSEMP_API_URL_BASE ou, se não
#     existir, da instância padrão do projeto (/61 e /84).
#   - se uma empresa der erro (recusa, timeout, token ausente...), o erro vira resultado e a OUTRA empresa
#     é testada do mesmo jeito. Nada interrompe a execução.
#   - o token NUNCA é mostrado: aparece só o tamanho dele e se o das duas empresas é igual ou diferente.
#
# * [EXPLICAÇÃO] → Este script NÃO usa o ClienteApiSysemp do projeto de propósito: ele tem timeout fixo de
#                  30 s e retenta até 4 vezes — num método que ainda não conhecemos (a doc de exemplo usa
#                  "sem limite de tempo"), isso poderia repetir 4x uma consulta pesada. Aqui é UMA chamada,
#                  com timeout configurável, e a resposta crua (status HTTP, tempo, tamanho) fica visível.
#                  Os nomes das variáveis do .env e as URLs padrão são os mesmos do ApiSysemp.
#
# Só leitura. Não toca no banco, não usa Django. Só roda quando VOCÊ executa o script.
#
# Arquivos de saída (a pasta saidas/ já está no .gitignore):
#   saidas/analise_estoque_full_<MB|SV>_<data>_<hora>.json  -> a resposta CRUA, só quando veio com dados
#   saidas/analise_estoque_full_<MB|SV>_<data>_<hora>.txt   -> o texto cru de qualquer outra resposta
#                                                              (erro, vazia, que não é JSON)
# Quando os registros trazem o campo id_empresa (a Samvale traz), o script organiza o resultado por local de
# estoque do ERP, em tabelas: (1) resumo com o significado de cada local (Full, Flex, Flex do 2º barracão,
# VSComercio); (2) uma linha por produto com uma coluna por local (MOSTRAR_TODAS_AS_LINHAS); (3) alerta dos
# locais que não deveriam ter estoque (VSComercio). O significado de cada id está em LOCAIS_DE_ESTOQUE.
#
# O mapear_campos_json.py lê o .json MAIS RECENTE da pasta (se as duas empresas responderem, é o da SV,
# que é gravado por último).
#
# Como rodar (da raiz do projeto):
#   poetry run python scripts_exploracao_ERP/investigar_analise_estoque_full.py

import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Permite rodar este script direto, de qualquer diretório, sem depender do CWD
# pra achar os pacotes api_sysemp e core.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from api_sysemp import URL_BASE_PADRAO_POR_PREFIXO
from core.empresa import (
    EMPRESA_MAGAZINE,
    EMPRESA_SAMVALE,
    NOME_EXIBICAO_POR_EMPRESA,
    PREFIXO_ENV_POR_EMPRESA,
)

console = Console()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EMPRESAS = [EMPRESA_MAGAZINE, EMPRESA_SAMVALE]   # as duas, na mesma execução (a de cima é chamada primeiro)
OFFSET = "0"             # "0" = primeiro bloco. A doc mostra "" (vazio), mas offset vazio já quebrou a API antes
TIMEOUT_SEGUNDOS = 120   # a doc de exemplo usa "sem limite" (CURLOPT_TIMEOUT 0); o cliente do projeto usa 30
MOSTRAR_TODAS_AS_LINHAS = True   # True = mostra a tabela com 1 linha por produto (até 100 linhas por bloco); False = só o resumo e os alertas
# ========================================

METODO = "listarAnaliseEstoqueFull"

# Campos que a Samvale devolveu na primeira chamada (08/10/2026) — todos vêm como texto.
CAMPO_EMPRESA = "id_empresa"
CAMPO_PRODUTO = "id_produto"
CAMPO_SKU = "sku"
CAMPO_DESCRICAO = "descricao"
CAMPO_ESTOQUE = "estoque"

# O que cada id_empresa significa (explicado por Matheus em 08/10/2026). Só vale para a Samvale (/84): o id_empresa
# é o ID do local de estoque na tela de estoque do produto no ERP. A ordem aqui é a ordem das colunas na tabela.
# "equivale" liga o local ao que se vê no Mercado Livre; "alerta_se_positivo" avisa quando um local que não deveria
# ter estoque tem. Os demais locais do ERP (3, 7, 13, 14, 15, 16, Farmácia Depósito 2) não são relevantes.
LOCAIS_DE_ESTOQUE = {
    EMPRESA_SAMVALE: [
        {"id": "4", "coluna": "Full (id 4)", "nome": "MELI FULL SAMVALE STEXPID", "equivale": "Full",
         "significado": "Controle do ERP do estoque que está no Full. Em teoria é sempre igual ao Full do ML."},
        {"id": "2", "coluna": "Flex (id 2)", "nome": "SAMVALE", "equivale": "Flex",
         "significado": "Onde os produtos ficam fisicamente quando não são Full."},
        {"id": "10", "coluna": "Flex 2º barracão (id 10)", "nome": "DEPOSITO INDUSTRIAL SAMVALE", "equivale": "Flex",
         "significado": "Igual ao id 2, mas em outro barracão físico (divisão por falta de espaço). Independente do id 2."},
        {"id": "1", "coluna": "VSComercio (id 1)", "nome": "VSCOMERCIO", "equivale": "—", "alerta_se_positivo": True,
         "significado": "Empresa sem movimentação. NÃO deveria ter estoque."},
    ],
}
PASTA_SAIDAS = Path(__file__).resolve().parent / "saidas"
PAUSA_ENTRE_EMPRESAS_SEGUNDOS = 1.0   # mesma cautela do cliente do projeto: 1 s entre chamadas


# ---------------------------------------------------------------------------
# Apoio: texto, números e tipos
# ---------------------------------------------------------------------------
def t(valor) -> str:
    """Texto vindo da API pode ter colchetes; o rich leria como formatação — escapa antes de mostrar."""
    return escape(str(valor))


def n_br(valor) -> str:
    """1146 -> '1.146'; None -> '—'."""
    if valor is None:
        return "—"
    return f"{valor:,}".replace(",", ".")


def cortar(texto, limite: int) -> str:
    texto = str(texto)
    return texto if len(texto) <= limite else texto[: limite - 3] + "..."


def tipo_simples(valor) -> str:
    """Nome do tipo em português, sem o tamanho (pra poder juntar os tipos vistos num campo)."""
    if valor is None:
        return "vazio (null)"
    if isinstance(valor, bool):
        return "booleano"
    if isinstance(valor, int):
        return "inteiro"
    if isinstance(valor, float):
        return "decimal"
    if isinstance(valor, str):
        return "texto"
    if isinstance(valor, list):
        return "lista"
    if isinstance(valor, dict):
        return "objeto"
    return type(valor).__name__


def valor_curto(valor, limite: int = 70) -> str:
    """O valor como texto curto: objetos e listas viram JSON cortado; None vira null; texto vazio vira \"\"."""
    if isinstance(valor, (dict, list)):
        texto = json.dumps(valor, ensure_ascii=False)
    elif valor is None:
        texto = "null"
    elif valor == "":
        texto = '""'
    else:
        texto = str(valor)
    return cortar(texto, limite)


def nova_tabela(titulo: str) -> Table:
    return Table(title=titulo, title_justify="left", show_lines=False, header_style="bold")


# ---------------------------------------------------------------------------
# PASSO 1 — o que vai ser chamado (antes de chamar)
# ---------------------------------------------------------------------------
def dados_de_acesso(empresa: str):
    """(nome_da_variavel_do_token, token_ou_None, url_completa) — sem nunca mostrar o token."""
    prefixo = PREFIXO_ENV_POR_EMPRESA[empresa]
    nome_variavel = f"{prefixo}_SYSEMP_API_TOKEN"
    token = os.environ.get(nome_variavel) or None
    url_base = os.environ.get(f"{prefixo}_SYSEMP_API_URL_BASE") or URL_BASE_PADRAO_POR_PREFIXO[prefixo]
    return nome_variavel, token, f"{url_base}/{METODO}"


def tokens_sao_iguais_entre_empresas() -> str:
    """'sim', 'não' ou '—' (quando falta o token de alguma). Compara sem mostrar nada do conteúdo."""
    tokens = [dados_de_acesso(empresa)[1] for empresa in EMPRESAS]
    if len(tokens) < 2 or any(token is None for token in tokens):
        return "—"
    return "sim" if len(set(tokens)) == 1 else "não"


def mostrar_plano() -> None:
    caminho_env = _RAIZ_DO_PROJETO / ".env"
    console.print(f"[bold]Método testado:[/bold] {METODO}   (POST, só leitura — nada é gravado em banco)")
    console.print(f"Corpo enviado: {t(json.dumps({'offset': OFFSET}))}   |   timeout: {TIMEOUT_SEGUNDOS} s   |   "
                  f"1 chamada por empresa, sem retentativa")
    console.print(f".env: {t(caminho_env)} — {'encontrado' if caminho_env.exists() else '[red]NÃO encontrado[/red]'}")

    tabela = nova_tabela("O que será chamado")
    tabela.add_column("Empresa", no_wrap=True)
    tabela.add_column("Endereço", overflow="fold")
    tabela.add_column("Token (variável do .env)", overflow="fold")
    for empresa in EMPRESAS:
        nome_variavel, token, url = dados_de_acesso(empresa)
        situacao = f"{nome_variavel} ({len(token)} caracteres)" if token else f"[red]{nome_variavel} NÃO ENCONTRADA[/red]"
        tabela.add_row(t(NOME_EXIBICAO_POR_EMPRESA[empresa]), t(url), situacao)
    console.print(tabela)
    console.print(f"Token igual nas duas empresas? {tokens_sao_iguais_entre_empresas()}   "
                  f"(o valor do token nunca aparece aqui)")


# ---------------------------------------------------------------------------
# PASSO 2 — a chamada (1 por empresa; erro vira resultado, nunca derruba o script)
# ---------------------------------------------------------------------------
def chamar_empresa(empresa: str) -> dict:
    prefixo = PREFIXO_ENV_POR_EMPRESA[empresa]
    nome_variavel, token, url = dados_de_acesso(empresa)
    resultado = {
        "empresa": empresa, "prefixo": prefixo, "url": url,
        "nao_chamou": False, "erro": None,
        "status_http": None, "tempo_segundos": None, "bytes": None, "content_type": "",
        "texto": "", "corpo": None, "arquivo": None,
    }

    if not token:
        resultado["nao_chamou"] = True
        resultado["erro"] = f"A variável {nome_variavel} não está no .env da raiz do projeto — nenhuma chamada foi feita."
        return resultado

    cabecalhos = {"Token": token, "Content-Type": "application/json"}
    inicio = time.monotonic()
    try:
        resposta = requests.post(url, json={"offset": OFFSET}, headers=cabecalhos, timeout=TIMEOUT_SEGUNDOS)
    except requests.exceptions.Timeout:
        resultado["tempo_segundos"] = time.monotonic() - inicio
        resultado["erro"] = (f"Sem resposta em {TIMEOUT_SEGUNDOS} s (timeout). O método pode ser pesado: "
                             f"aumente TIMEOUT_SEGUNDOS no topo do script e rode de novo.")
        return resultado
    except requests.exceptions.RequestException as erro_de_rede:
        resultado["tempo_segundos"] = time.monotonic() - inicio
        resultado["erro"] = f"Falha de rede ({type(erro_de_rede).__name__}): {erro_de_rede}"
        return resultado

    resultado["tempo_segundos"] = time.monotonic() - inicio
    resultado["status_http"] = resposta.status_code
    resultado["content_type"] = resposta.headers.get("Content-Type", "")
    resultado["bytes"] = len(resposta.content)
    # utf-8-sig: se a resposta começar com BOM (marca invisível), ele é descartado em vez de quebrar o JSON.
    resultado["texto"] = resposta.content.decode("utf-8-sig", errors="replace")
    try:
        resultado["corpo"] = json.loads(resultado["texto"])
    except ValueError:
        resultado["corpo"] = None
    return resultado


# ---------------------------------------------------------------------------
# PASSO 3 — entender o que voltou
# ---------------------------------------------------------------------------
def classificar(resultado: dict):
    """(codigo, rotulo, cor) — o veredito curto de uma chamada."""
    if resultado["nao_chamou"]:
        return "nao_chamou", "NÃO CHAMOU (token ausente no .env)", "red"
    if resultado["erro"]:
        return "sem_resposta", "SEM RESPOSTA (rede, timeout ou erro do script)", "red"
    status = resultado["status_http"]
    if status in (401, 403):
        return "sem_permissao", f"SEM PERMISSÃO (HTTP {status})", "red"
    if not 200 <= status < 300:
        return "erro_http", f"ERRO HTTP {status}", "red"
    corpo = resultado["corpo"]
    if corpo is None:
        return "nao_json", "A RESPOSTA NÃO VEIO EM JSON", "red"
    if isinstance(corpo, dict) and corpo.get("status") is False:
        return "recusado_pela_api", "A API RECUSOU (status=False)", "red"
    if isinstance(corpo, dict) and isinstance(corpo.get("retorno"), list):
        if corpo["retorno"]:
            return "com_dados", "RESPONDEU COM DADOS", "green"
        return "sem_registros", "RESPONDEU, MAS SEM REGISTROS", "yellow"
    return "formato_inesperado", "RESPONDEU, MAS FORA DO FORMATO CONHECIDO (sem a lista 'retorno')", "yellow"


def registros_do_corpo(corpo):
    """A lista 'retorno' da resposta, ou None se a resposta não tiver esse formato."""
    if isinstance(corpo, dict) and isinstance(corpo.get("retorno"), list):
        return corpo["retorno"]
    return None


def campos_dos_registros(registros: list):
    """{campo: {'tipos': {...}, 'presente': n}} na ordem em que os campos aparecem, ou None se os itens não forem objetos."""
    if not registros or not all(isinstance(registro, dict) for registro in registros):
        return None
    campos = {}
    for registro in registros:
        for nome, valor in registro.items():
            info = campos.setdefault(nome, {"tipos": set(), "presente": 0})
            info["tipos"].add(tipo_simples(valor))
            info["presente"] += 1
    return campos


# ---------------------------------------------------------------------------
# PASSO 4 — guardar a resposta crua
# ---------------------------------------------------------------------------
def salvar_resposta(resultado: dict, codigo: str):
    """Grava a resposta crua em saidas/. .json só quando veio com dados (é o que o mapear_campos_json.py lê);
    qualquer outra resposta com texto vai para .txt. Devolve o caminho gravado, ou None se não havia o que gravar."""
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_base = f"analise_estoque_full_{resultado['prefixo']}_{carimbo}"

    if codigo in ("com_dados", "formato_inesperado") and resultado["corpo"] is not None:
        caminho = PASTA_SAIDAS / f"{nome_base}.json"
        PASTA_SAIDAS.mkdir(exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as arquivo:
            json.dump(resultado["corpo"], arquivo, ensure_ascii=False, indent=2)
        return caminho

    if resultado["texto"]:
        caminho = PASTA_SAIDAS / f"{nome_base}.txt"
        PASTA_SAIDAS.mkdir(exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as arquivo:
            arquivo.write(resultado["texto"])
        return caminho

    return None


# ---------------------------------------------------------------------------
# Apresentação
# ---------------------------------------------------------------------------
def numero_do_texto(valor):
    """'22.0000' -> 22.0; None se não for número."""
    try:
        numero = float(str(valor).strip())
    except ValueError:
        return None
    return numero if math.isfinite(numero) else None


def qtd_br(valor) -> str:
    """22.0 -> '22'; 1159.5 -> '1.159,5'; None -> '—'."""
    if valor is None:
        return "—"
    if valor == int(valor):
        return n_br(int(valor))
    return f"{valor:,.4f}".rstrip("0").replace(",", "X").replace(".", ",").replace("X", ".")


def chave_empresa(valor):
    """Ordena o id_empresa como número quando der ('2' antes de '10')."""
    texto = str(valor)
    return (0, int(texto)) if texto.isdigit() else (1, texto)


def mostrar_estoque_por_local(registros: list, empresa: str) -> None:
    """Organiza o que veio por local de estoque (id_empresa): resumo com o significado de cada local, uma linha por
    produto com uma coluna por local, e o alerta dos locais que não deveriam ter estoque. Só roda se os registros
    tiverem o campo id_empresa."""
    if not all(CAMPO_EMPRESA in registro for registro in registros):
        return

    locais = LOCAIS_DE_ESTOQUE.get(empresa, [])
    ids_conhecidos = [local["id"] for local in locais]
    locais_flex = [local for local in locais if local["equivale"] == "Flex"]

    # Junta as linhas por produto (a API manda 1 linha por produto E local). Se vier mais de 1 linha para o mesmo
    # produto no mesmo local, as quantidades são somadas e o fato é avisado no fim.
    produtos = {}
    repetidas = []
    estoques_ilegiveis = 0
    for registro in registros:
        id_produto = str(registro.get(CAMPO_PRODUTO))
        id_local = str(registro[CAMPO_EMPRESA])
        quantidade = numero_do_texto(registro.get(CAMPO_ESTOQUE))
        if quantidade is None:
            estoques_ilegiveis += 1
            quantidade = 0.0
        produto = produtos.setdefault(id_produto, {"skus": [], "descricao": "", "quantidades": {}})
        sku = str(registro.get(CAMPO_SKU) or "").strip()
        if sku and sku not in produto["skus"]:
            produto["skus"].append(sku)
        if not produto["descricao"]:
            produto["descricao"] = str(registro.get(CAMPO_DESCRICAO) or "").strip()
        if id_local in produto["quantidades"]:
            repetidas.append((id_produto, id_local))
        produto["quantidades"][id_local] = produto["quantidades"].get(id_local, 0.0) + quantidade

    ids_vistos = {id_local for produto in produtos.values() for id_local in produto["quantidades"]}
    ids_outros = sorted(ids_vistos - set(ids_conhecidos), key=chave_empresa)

    def soma_do_local(id_local):
        return sum(produto["quantidades"].get(id_local, 0.0) for produto in produtos.values())

    def produtos_no_local(id_local):
        return sum(1 for produto in produtos.values() if produto["quantidades"].get(id_local, 0.0) != 0)

    console.print()
    console.print(f"[bold]Estoque por local do ERP[/bold] (só este bloco de {n_br(len(registros))} linhas = "
                  f"{n_br(len(produtos))} produtos diferentes)")
    if not locais:
        console.print(f"[yellow]O significado dos {CAMPO_EMPRESA} só foi mapeado para a Samvale; "
                      f"aqui eles aparecem como \"Outros\", só com o número.[/yellow]")

    # --- Resumo: 1 linha por local, com o significado ---
    resumo = nova_tabela(f"Resumo por local ({CAMPO_EMPRESA})")
    resumo.add_column(CAMPO_EMPRESA, no_wrap=True)
    resumo.add_column("Nome no ERP", overflow="fold")
    resumo.add_column("Equivale no ML", no_wrap=True)
    resumo.add_column("O que é", overflow="fold")
    resumo.add_column("Produtos com estoque", justify="right", no_wrap=True)
    resumo.add_column("Soma do estoque", justify="right", no_wrap=True)
    for local in locais:
        resumo.add_row(
            t(local["id"]), t(local["nome"]), t(local["equivale"]), t(local["significado"]),
            n_br(produtos_no_local(local["id"])), qtd_br(soma_do_local(local["id"])),
        )
    for id_local in ids_outros:
        resumo.add_row(
            t(id_local), "—", "—", "[yellow](sem significado mapeado)[/yellow]",
            n_br(produtos_no_local(id_local)), qtd_br(soma_do_local(id_local)),
        )
    resumo.add_section()
    resumo.add_row(
        "[bold]Total[/bold]", "", "", "", n_br(len(produtos)),
        qtd_br(sum(soma_do_local(id_local) for id_local in ids_vistos)),
    )
    console.print(resumo)

    # --- Uma linha por produto, uma coluna por local ---
    def celula(quantidade, alerta=False) -> str:
        if not quantidade:
            return "[dim]—[/dim]"
        texto = qtd_br(quantidade)
        return f"[bold yellow]{texto} (!)[/bold yellow]" if alerta else texto

    if MOSTRAR_TODAS_AS_LINHAS:
        tabela = nova_tabela("Estoque por produto (uma coluna por local)")
        tabela.add_column(CAMPO_PRODUTO, no_wrap=True)
        tabela.add_column("SKU", no_wrap=True)
        tabela.add_column("Descrição", overflow="fold")
        for local in locais:
            tabela.add_column(local["coluna"], justify="right", no_wrap=True)
            if len(locais_flex) > 1 and local is locais_flex[-1]:
                tabela.add_column("Flex total", justify="right", no_wrap=True)
        if ids_outros:
            tabela.add_column("Outros", overflow="fold")

        total_por_coluna = {local["id"]: 0.0 for local in locais}
        total_flex = 0.0
        for id_produto, produto in produtos.items():
            quantidades = produto["quantidades"]
            sku = " / ".join(produto["skus"])
            celulas = []
            for local in locais:
                quantidade = quantidades.get(local["id"], 0.0)
                total_por_coluna[local["id"]] += quantidade
                celulas.append(celula(quantidade, alerta=local.get("alerta_se_positivo", False) and quantidade > 0))
                if len(locais_flex) > 1 and local is locais_flex[-1]:
                    flex = sum(quantidades.get(item["id"], 0.0) for item in locais_flex)
                    total_flex += flex
                    celulas.append(celula(flex))
            if ids_outros:
                outros = [f"id {id_local}: {qtd_br(quantidades[id_local])}" for id_local in ids_outros
                          if quantidades.get(id_local)]
                celulas.append(t("  |  ".join(outros)) if outros else "[dim]—[/dim]")
            tabela.add_row(
                t(id_produto), t(sku) if sku else "[yellow](sem SKU)[/yellow]",
                t(produto["descricao"]), *celulas,
            )

        tabela.add_section()
        linha_total = ["[bold]Total[/bold]", "", ""]
        for local in locais:
            linha_total.append(qtd_br(total_por_coluna[local["id"]]))
            if len(locais_flex) > 1 and local is locais_flex[-1]:
                linha_total.append(qtd_br(total_flex))
        if ids_outros:
            linha_total.append(qtd_br(sum(soma_do_local(id_local) for id_local in ids_outros)))
        tabela.add_row(*linha_total)
        console.print(tabela)

    # --- Alerta: locais que não deveriam ter estoque ---
    for local in locais:
        if not local.get("alerta_se_positivo"):
            continue
        com_estoque = [(id_produto, produto) for id_produto, produto in produtos.items()
                       if produto["quantidades"].get(local["id"], 0.0) > 0]
        if not com_estoque:
            console.print(f"[green]Nenhum produto com estoque em {t(local['nome'])} (id {t(local['id'])}) — como esperado.[/green]")
            continue
        alerta = nova_tabela(f"ATENÇÃO — estoque em {local['nome']} (id {local['id']}), que não deveria ter")
        alerta.add_column(CAMPO_PRODUTO, no_wrap=True)
        alerta.add_column("SKU", no_wrap=True)
        alerta.add_column("Descrição", overflow="fold")
        alerta.add_column("Estoque", justify="right", no_wrap=True)
        for id_produto, produto in com_estoque:
            sku = " / ".join(produto["skus"])
            alerta.add_row(
                t(id_produto), t(sku) if sku else "[yellow](sem SKU)[/yellow]", t(produto["descricao"]),
                qtd_br(produto["quantidades"][local["id"]]),
            )
        console.print(alerta)

    if repetidas:
        console.print(f"[yellow]Atenção: {n_br(len(repetidas))} caso(s) de mais de 1 linha para o mesmo produto no mesmo "
                      f"local (somados na tabela): {t(', '.join(f'produto {p} / id {i}' for p, i in repetidas[:10]))}[/yellow]")
    if estoques_ilegiveis:
        console.print(f"[yellow]Atenção: {n_br(estoques_ilegiveis)} linha(s) com estoque que não é número "
                      f"(contadas como 0).[/yellow]")


def mostrar_resultado(resultado: dict, codigo: str, rotulo: str, cor: str) -> None:
    nome = NOME_EXIBICAO_POR_EMPRESA[resultado["empresa"]]
    console.print()
    console.rule(f"[bold]{t(nome)} ({resultado['prefixo']})[/bold]")
    console.print(f"[{cor}][bold]{rotulo}[/bold][/{cor}]")

    tabela = nova_tabela("A chamada")
    tabela.add_column("O que", no_wrap=True)
    tabela.add_column("Valor", overflow="fold")
    tabela.add_row("Endereço", t(resultado["url"]))
    if resultado["status_http"] is not None:
        tabela.add_row("Status HTTP", str(resultado["status_http"]))
    if resultado["tempo_segundos"] is not None:
        tabela.add_row("Tempo", f"{resultado['tempo_segundos']:.1f} s")
    if resultado["bytes"] is not None:
        tabela.add_row("Tamanho da resposta", f"{n_br(resultado['bytes'])} bytes")
    if resultado["content_type"]:
        tabela.add_row("Content-Type", t(resultado["content_type"]))
    console.print(tabela)

    if resultado["erro"]:
        console.print(f"[red]{t(resultado['erro'])}[/red]")
        return

    corpo = resultado["corpo"]

    # Tudo que não é "veio com dados": mostra o texto cru (cortado) — a recusa já é a resposta.
    if codigo not in ("com_dados", "formato_inesperado"):
        if codigo == "recusado_pela_api":
            console.print(f"Mensagem da API: {t(corpo.get('message'))}")
        console.print(f"Corpo da resposta (até 500 caracteres): {t(cortar(resultado['texto'], 500))}")
        return

    # Campos do nível de cima da resposta (status, message, retorno, ...).
    if isinstance(corpo, dict):
        topo = nova_tabela("Campos do nível de cima da resposta")
        topo.add_column("Campo", no_wrap=True)
        topo.add_column("Tipo", no_wrap=True)
        topo.add_column("Valor", overflow="fold")
        for nome_campo, valor in corpo.items():
            if isinstance(valor, list):
                resumo = f"{n_br(len(valor))} item(ns)"
            else:
                resumo = valor_curto(valor)
            topo.add_row(t(nome_campo), tipo_simples(valor), t(resumo))
        console.print(topo)
    else:
        console.print(f"A resposta inteira é do tipo: {tipo_simples(corpo)}")

    registros = registros_do_corpo(corpo)
    if registros is None:
        console.print("[yellow]Não tem a lista 'retorno' — veja o arquivo salvo para entender o formato.[/yellow]")
        return

    console.print(f"Registros neste bloco (offset {t(OFFSET)}): [bold]{n_br(len(registros))}[/bold]")
    campos = campos_dos_registros(registros)
    if campos is None:
        tipos = sorted({tipo_simples(registro) for registro in registros})
        console.print(f"Os itens de 'retorno' não são objetos — tipos vistos: {', '.join(tipos)}")
        return

    primeiro = registros[0]
    tabela_campos = nova_tabela(f"Campos de cada registro ({n_br(len(registros))} registro(s) analisado(s))")
    tabela_campos.add_column("Campo", no_wrap=True)
    tabela_campos.add_column("Tipo(s)", overflow="fold")
    tabela_campos.add_column("Em quantos", justify="right", no_wrap=True)
    tabela_campos.add_column("Exemplo (1º registro)", overflow="fold")
    for nome_campo, info in campos.items():
        exemplo = valor_curto(primeiro[nome_campo]) if nome_campo in primeiro else "—"
        tabela_campos.add_row(
            t(nome_campo), t(" | ".join(sorted(info["tipos"]))),
            f"{info['presente']}/{len(registros)}", t(exemplo),
        )
    console.print(tabela_campos)

    mostrar_estoque_por_local(registros, resultado["empresa"])


def mostrar_comparacao(resultados: list, codigos: dict) -> None:
    """Se as duas empresas responderam com dados, diz se os campos dos registros são os mesmos."""
    campos_por_empresa = {}
    for resultado in resultados:
        if codigos[resultado["empresa"]] != "com_dados":
            continue
        campos = campos_dos_registros(registros_do_corpo(resultado["corpo"]) or [])
        if campos is not None:
            campos_por_empresa[resultado["prefixo"]] = set(campos.keys())

    if len(campos_por_empresa) < 2:
        return
    (prefixo_a, campos_a), (prefixo_b, campos_b) = list(campos_por_empresa.items())[:2]
    console.print()
    if campos_a == campos_b:
        console.print(f"[green]Os campos dos registros são os MESMOS nas duas empresas ({len(campos_a)} campos).[/green]")
        return
    console.print("[yellow]Os campos dos registros são DIFERENTES entre as empresas:[/yellow]")
    console.print(f"  só em {prefixo_a}: {t(', '.join(sorted(campos_a - campos_b)) or '—')}")
    console.print(f"  só em {prefixo_b}: {t(', '.join(sorted(campos_b - campos_a)) or '—')}")


def mostrar_resumo(resultados: list, codigos: dict, rotulos: dict, cores: dict) -> None:
    tabela = nova_tabela("RESUMO — é este bloco que vale colar de volta no chat")
    tabela.add_column("Empresa", no_wrap=True)
    tabela.add_column("Veredito", overflow="fold")
    tabela.add_column("HTTP", justify="right", no_wrap=True)
    tabela.add_column("Tempo", justify="right", no_wrap=True)
    tabela.add_column("Registros (1º bloco)", justify="right", no_wrap=True)
    tabela.add_column("Arquivo salvo", overflow="fold")
    for resultado in resultados:
        empresa = resultado["empresa"]
        registros = registros_do_corpo(resultado["corpo"])
        tabela.add_row(
            f"{t(NOME_EXIBICAO_POR_EMPRESA[empresa])} ({resultado['prefixo']})",
            f"[{cores[empresa]}]{rotulos[empresa]}[/{cores[empresa]}]",
            str(resultado["status_http"]) if resultado["status_http"] is not None else "—",
            f"{resultado['tempo_segundos']:.1f} s" if resultado["tempo_segundos"] is not None else "—",
            n_br(len(registros)) if registros is not None else "—",
            t(resultado["arquivo"].name) if resultado["arquivo"] else "—",
        )
    console.print(tabela)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def main() -> None:
    load_dotenv(_RAIZ_DO_PROJETO / ".env")   # caminho absoluto: funciona de qualquer pasta

    console.rule(f"[bold]INVESTIGAÇÃO — {METODO}[/bold]")
    mostrar_plano()

    resultados = []
    codigos, rotulos, cores = {}, {}, {}
    for posicao, empresa in enumerate(EMPRESAS):
        if posicao > 0:
            time.sleep(PAUSA_ENTRE_EMPRESAS_SEGUNDOS)
        console.print(f"\nChamando {t(NOME_EXIBICAO_POR_EMPRESA[empresa])}...")
        try:
            resultado = chamar_empresa(empresa)
        except Exception as erro_inesperado:   # exploração: um erro de uma empresa nunca pode impedir a outra
            resultado = {
                "empresa": empresa, "prefixo": PREFIXO_ENV_POR_EMPRESA[empresa], "url": dados_de_acesso(empresa)[2],
                "nao_chamou": False, "status_http": None, "tempo_segundos": None, "bytes": None,
                "content_type": "", "texto": "", "corpo": None, "arquivo": None,
                "erro": f"Erro inesperado no script ({type(erro_inesperado).__name__}): {erro_inesperado}",
            }
        codigo, rotulo, cor = classificar(resultado)
        resultado["arquivo"] = salvar_resposta(resultado, codigo)
        codigos[empresa], rotulos[empresa], cores[empresa] = codigo, rotulo, cor
        resultados.append(resultado)
        mostrar_resultado(resultado, codigo, rotulo, cor)

    mostrar_comparacao(resultados, codigos)
    console.print()
    mostrar_resumo(resultados, codigos, rotulos, cores)

    console.print(f"\nArquivos gravados em: {t(PASTA_SAIDAS)}")
    console.print("Nada acima mostra o token.")
    if any(codigo == "com_dados" for codigo in codigos.values()):
        console.print("Os exemplos do 1º registro são dados reais da empresa — cole de volta só o que quiser.")
        console.print("Próximo passo (opcional): poetry run python scripts_exploracao_ERP/mapear_campos_json.py "
                      "gera o mapa de campos do JSON mais recente, sem nenhum dado.")


if __name__ == "__main__":
    main()
