# scripts_exploracao_ML/investigar_envios_full_inbound.py
# ============================================================================================================================
# Objetivo: descobrir, com dado real, QUANTO da tela "Gestão de envios Full -> Detalhe do envio" o Mercado Livre entrega pela
# API PÚBLICA. A tela mostra: Envio N.º, nome do envio, status da coleta, transportador / placa / transportadora / endereço,
# a linha do tempo das etapas e, por produto, as colunas Declaradas / Processadas / Diferenças / Aptos para o Full / Resultado
# do processamento.
#
# DE ONDE VEIO A IDEIA (e o que NÃO foi verificado): outra LLM respondeu "só parcialmente" e citou 4 caminhos. Eu (Claude) não
# consegui ler a doc oficial "Envios Fulfillment" (o site bloqueou a leitura), então NADA abaixo é fato confirmado — cada item
# é uma hipótese que este script testa:
#   H1  GET /stock/fulfillment/operations/search aceita type=INBOUND_RECEPTION (a entrada de mercadoria no Full);
#   H2  a operação traz o número do envio em external_references (type = "inbound_id");
#   H3  o "Envio N.º" da tela (ENVIOS_DA_TELA) aparece nessas referências;
#   H4  GET /inventories/{inventory_id}/stock/fulfillment?include_attributes=conditions devolve algo a mais que a chamada simples;
#   H5  algum valor que você VÊ na tela (OUTROS_VALORES_DA_TELA: placa, transportadora...) aparece em ALGUMA resposta.
# O tópico de notificação "fbm_stock_operations" e o endpoint /replenishment que a outra LLM citou NÃO são testados aqui:
# o tópico exige uma URL pública para receber o aviso (não é script de exploração) e o /replenishment você já usa
# (investigar_full_reposicao.py) — ele é a tela "Planejamento de envios", não esta.
#
# O QUE O SCRIPT FAZ (poucas chamadas, só GET):
#   Passo 1  1 chamada com um "type" INVENTADO (limit=1, janela de 1 dia). Se a API validar o campo, a mensagem de erro pode listar
#            os tipos aceitos — é a forma mais barata de descobrir se existe outro tipo ligado a envio além de INBOUND_RECEPTION.
#   Passo 2  por Código ML: 2 chamadas de estoque (simples e com include_attributes=conditions) e a diferença de campos entre elas.
#   Passo 3  1 chamada de operações type=INBOUND_RECEPTION para TODOS os Códigos de uma vez (limit=1000, janela de DIAS_DA_JANELA).
#            NÃO pagina (o scroll já deu 404 no seu histórico de vendas): se houver mais de uma página, o script avisa.
#   Passo 4  inventário de campos: todos os caminhos JSON que vieram, com quantas vezes apareceram e um exemplo.
#   Passo 5  procura cada valor da tela dentro de TODAS as respostas e diz em qual caminho achou (ou que não achou).
#   Passo 6  tabela de fatos medidos (H1 a H5), sem conclusão: a conclusão é sua, olhando a tela ao lado.
#
# COMO LER O RESULTADO:
#   - 0 operações INBOUND_RECEPTION NÃO prova que a API não tem o dado. Um envio com "coleta pendente" ainda não foi recebido pelo
#     Full, então provavelmente não existe entrada registrada. Rode DE NOVO com um envio JÁ PROCESSADO: coloque o número dele em
#     ENVIOS_DA_TELA e um Código ML dele em CODIGOS_ML (e, se quiser, a placa/transportadora dele em OUTROS_VALORES_DA_TELA).
#   - "Não apareceu em nenhuma resposta" vale só para as chamadas feitas nesta execução.
#   - Mesmo que o número do envio apareça, as colunas Declaradas / Diferenças / Resultado do processamento e os dados de coleta
#     (transportador, placa, etapas) só contam como "existem na API" se o Passo 4/5 mostrar um campo com esse conteúdo.
#
# REGRAS: só leitura (GET), nunca escreve no Mercado Livre nem no banco. O token e o seller_id NÃO vão para a tela nem para o JSON
# (o seller_id é trocado por *** em tudo que é gravado). Nenhum dado de comprador é pedido. UMA tentativa por chamada, exceto
# quando vier 429: aí repete até TENTATIVAS_SE_429 vezes com pausa, MOSTRANDO cada tentativa (o seu histórico mostrou 429
# "over_quota" em rajadas, sem Retry-After — por isso nada de varredura grande com este endpoint).
#
# * [EXPLICAÇÃO] → Por que não usa chamar_api(): ele repete sozinho no 429 e esconde os cabeçalhos da resposta; aqui eu quero ver
#                  cada resposta como ela é. Por isso usa a MESMA sessão HTTP e o MESMO gerenciador de token do cliente, mas
#                  controla as tentativas. Só vale para exploração (igual ao sondar_limite_operacoes_full.py).
#
# Arquivo de saída (o .gitignore já cobre pela regra "scripts_exploracao_ML/*.json"):
#   investigacao_envios_full_inbound_<CONTA>.json -> retorno CRU de todas as chamadas + os fatos medidos.
#
# Como rodar:
#   poetry run python scripts_exploracao_ML/investigar_envios_full_inbound.py

import json
import os
import shutil
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

# Permite rodar este script direto, de qualquer diretório, sem depender do CWD pra achar o pacote api_mercado_livre.
_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.auth.gerenciador_token import obter_token_valido
from api_mercado_livre.core.estrutura_api.cliente_api import BASE_URL, TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS, _sessao

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                                    # "MB" (Magazine) ou "SV" (Samvale)
# Códigos ML (inventory_id) dos produtos do envio. A coluna "Código ML" da tela de envio traz esse código. COMECE COM 1 SÓ
# (menos chamadas); se der resultado, coloque os outros. O código abaixo é o que eu li no seu print — CONFIRA na tela.
CODIGOS_ML = ["BVJZ25515"]
# "Envio N.º" como aparece na tela (só os dígitos). Pode pôr mais de um (ex.: um pendente e um já processado).
ENVIOS_DA_TELA = ["79130258"]
# Qualquer outro texto que você VÊ na tela e quer procurar nas respostas. Descomente e preencha o que quiser.
OUTROS_VALORES_DA_TELA = {
    "nome do envio": "EXPEDICIONÁRIOS - GRANDE",
    # "placa": "AAA0A00",
    # "transportadora": "NOME COMO NA TELA",
    # "motorista": "NOME COMO NA TELA",
}
DIAS_DA_JANELA = 55                             # a doc limita a 60 dias por chamada (conforme os seus scripts); 55 deixa folga
SONDAR_LISTA_DE_TIPOS = True                    # Passo 1 (1 chamada com type inventado). Ponha False para pular
PAUSA_ENTRE_CHAMADAS_S = 2                      # silêncio entre uma chamada e a próxima
TENTATIVAS_SE_429 = 3                           # só repete se vier 429 (e mostra cada tentativa)
PAUSA_SE_429_S = 20
LINHAS_NA_TELA = 25                             # máximo de operações listadas na tela (todas vão pro JSON)
# ========================================

ENDPOINT_OPERACOES = "/stock/fulfillment/operations/search"
ENDPOINT_ESTOQUE = "/inventories/{inventory_id}/stock/fulfillment"
TIPO_ENTRADA = "INBOUND_RECEPTION"
TIPO_INVENTADO = "TIPO_INEXISTENTE_TESTE"
LIMITE_POR_PAGINA = 1000
FUSO = ZoneInfo("America/Sao_Paulo")
PADROES_DE_CABECALHO_DE_LIMITE = ("rate", "limit", "retry", "remaining", "reset", "quota", "throttl", "wait")
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"investigacao_envios_full_inbound_{CONTA}.json"

console = Console(highlight=False, width=max(shutil.get_terminal_size(fallback=(80, 24)).columns - 1, 20))
t = escape
user_id = None
chamadas = []                                   # 1 dict por chamada (vai para o JSON)
ultimo_fim = {"t": None}


# ---------- utilidades ----------
def sem_id(texto):
    """Troca o seller_id por *** antes de mostrar/gravar qualquer texto que veio da API."""
    texto = str(texto)
    return texto.replace(str(user_id), "***") if user_id else texto


def mascarar(objeto):
    """Troca o seller_id por *** DENTRO do objeto (texto ou número), sem mexer na estrutura do JSON.
    (O seller_id vem como NÚMERO nas operações; trocar no texto já serializado deixaria `"seller_id": ***` e o JSON ficaria inválido.)"""
    if isinstance(objeto, dict):
        return {chave: mascarar(valor) for chave, valor in objeto.items()}
    if isinstance(objeto, list):
        return [mascarar(valor) for valor in objeto]
    if isinstance(objeto, str):
        return sem_id(objeto)
    if isinstance(objeto, (int, float)) and not isinstance(objeto, bool) and str(objeto) == str(user_id):
        return "***"
    return objeto


def normalizar(texto):
    """Minúsculo e sem acento, para comparar o que está na tela com o que veio da API."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return sem_acento.casefold().strip()


def cabecalhos_de_interesse(resposta):
    """Só os cabeçalhos que falam de limite/espera. Nunca o resto dos valores."""
    achados = {}
    for nome, valor in resposta.headers.items():
        if any(p in nome.lower() for p in PADROES_DE_CABECALHO_DE_LIMITE):
            achados[nome] = str(valor)[:120]
    return achados


def erro_curto(corpo):
    """A mensagem curta do erro da API (message/error/status/cause), sem o seller_id."""
    if isinstance(corpo, dict):
        partes = {k: str(corpo[k])[:300] for k in ("message", "error", "status", "cause") if k in corpo}
        if partes:
            return sem_id(json.dumps(partes, ensure_ascii=False))
    return sem_id(str(corpo)[:300])


def esperar(segundos):
    if ultimo_fim["t"] is None:
        return
    falta = segundos - (time.perf_counter() - ultimo_fim["t"])
    if falta > 0:
        time.sleep(falta)


def percorrer(objeto, prefixo=""):
    """Gera (caminho, valor) de todas as folhas do JSON. Lista vira 'caminho[]' (todos os itens contam no mesmo caminho)."""
    if isinstance(objeto, dict):
        for chave, valor in objeto.items():
            yield from percorrer(valor, f"{prefixo}.{chave}" if prefixo else str(chave))
    elif isinstance(objeto, list):
        for item in objeto:
            yield from percorrer(item, f"{prefixo}[]")
    else:
        yield prefixo, objeto


def inventario_de_caminhos(corpo):
    """{caminho: [quantas vezes apareceu, 1º exemplo]} — o 'raio-x' dos campos que a API devolveu."""
    inventario = {}
    for caminho, valor in percorrer(corpo):
        if caminho not in inventario:
            inventario[caminho] = [0, valor]
        inventario[caminho][0] += 1
    return inventario


# ---------- chamada HTTP ----------
def chamar(rotulo, endpoint, params=None):
    """1 GET (repete só no 429, mostrando cada tentativa). Registra tudo em `chamadas` e devolve o registro."""
    registro = {
        "n": len(chamadas) + 1, "rotulo": rotulo, "endpoint": endpoint,
        "params": {k: ("***" if k == "seller_id" else v) for k, v in (params or {}).items()},
        "http": None, "tentativas": [], "corpo": None,
    }
    chamadas.append(registro)
    for tentativa in range(1, TENTATIVAS_SE_429 + 1):
        esperar(PAUSA_ENTRE_CHAMADAS_S)
        inicio = time.perf_counter()
        try:
            resposta = _sessao.get(
                f"{BASE_URL}{endpoint}", params=params,
                headers={"Authorization": f"Bearer {obter_token_valido(CONTA)}"},
                timeout=(TIMEOUT_CONEXAO_SEGUNDOS, TIMEOUT_LEITURA_SEGUNDOS),
            )
        except requests.exceptions.RequestException as erro:
            ultimo_fim["t"] = time.perf_counter()
            registro["tentativas"].append({"http": None, "ms": round((time.perf_counter() - inicio) * 1000), "erro": f"{type(erro).__name__} (sem resposta)"})
            console.print(f"  #{registro['n']:<2} {t(rotulo):<46} [bold red]sem resposta ({type(erro).__name__})[/]")
            break
        ultimo_fim["t"] = time.perf_counter()
        ms = round((time.perf_counter() - inicio) * 1000)
        try:
            corpo = resposta.json()
        except ValueError:
            corpo = {"_texto_nao_json": sem_id(resposta.text[:300])}
        registro["http"] = resposta.status_code
        registro["corpo"] = corpo
        registro["tentativas"].append({"http": resposta.status_code, "ms": ms, "cabecalhos_de_limite": cabecalhos_de_interesse(resposta)})
        cor = {200: "green", 429: "red", 404: "yellow"}.get(resposta.status_code, "magenta")
        detalhe = "" if resposta.status_code == 200 else t(erro_curto(corpo)[:140])
        console.print(f"  #{registro['n']:<2} {t(rotulo):<46} [{cor}]HTTP {resposta.status_code}[/]  {ms} ms  {detalhe}")
        if resposta.status_code != 429 or tentativa == TENTATIVAS_SE_429:
            break
        console.print(f"      429: esperando {PAUSA_SE_429_S}s para a tentativa {tentativa + 1}/{TENTATIVAS_SE_429}...")
        time.sleep(PAUSA_SE_429_S)
        ultimo_fim["t"] = time.perf_counter()
    return registro


# ---------- leitura das operações ----------
def referencias_da_operacao(operacao):
    """[(tipo, valor)] de external_references, sem supor nomes: o que vier é mostrado."""
    saida = []
    for ref in (operacao.get("external_references") or []):
        if isinstance(ref, dict):
            saida.append((str(ref.get("type")), "" if ref.get("value") is None else str(ref.get("value"))))
    return saida


def referencia_de_envio(operacao):
    """A referência que parece ser a do envio ao Full: tipo que contém 'inbound'. None se não houver."""
    for tipo, valor in referencias_da_operacao(operacao):
        if "inbound" in tipo.casefold():
            return f"{tipo}={valor}"
    return None


def unidades(operacao):
    detalhe = operacao.get("detail") or {}
    valor = detalhe.get("available_quantity")
    return abs(valor) if isinstance(valor, (int, float)) else None


def instante(texto):
    if not texto:
        return None
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).astimezone(FUSO)
    except ValueError:
        return None


def detalhe_numerico(operacao):
    """Os números de 'detail' em uma linha curta (ex.: available_quantity=12 not_available_quantity=0)."""
    detalhe = operacao.get("detail") or {}
    partes = [f"{k}={v}" for k, v in detalhe.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return " ".join(partes) or "-"


# ---------- passos ----------
def passo_tipo_inventado(codigo, hoje):
    console.print("[bold]Passo 1 — a API lista os tipos de operação quando recebe um type inventado?[/]")
    params = {
        "seller_id": user_id, "inventory_id": codigo, "type": TIPO_INVENTADO,
        "date_from": (hoje - timedelta(days=1)).isoformat(), "date_to": hoje.isoformat(), "limit": 1,
    }
    registro = chamar(f"operações com type inventado ({codigo})", ENDPOINT_OPERACOES, params)
    console.print()
    return registro


def passo_estoque():
    console.print("[bold]Passo 2 — estoque por Código ML (simples x include_attributes=conditions)[/]")
    pares = {}
    for codigo in CODIGOS_ML:
        endpoint = ENDPOINT_ESTOQUE.format(inventory_id=codigo)
        simples = chamar(f"estoque {codigo}", endpoint)
        com_conditions = chamar(f"estoque {codigo} + conditions", endpoint, {"include_attributes": "conditions"})
        pares[codigo] = (simples, com_conditions)
    console.print()
    return pares


def campos_a_mais(simples, com_conditions):
    """Caminhos que só existem na resposta com include_attributes=conditions (ou None se uma das duas falhou)."""
    if simples["http"] != 200 or com_conditions["http"] != 200:
        return None
    return sorted(set(inventario_de_caminhos(com_conditions["corpo"])) - set(inventario_de_caminhos(simples["corpo"])))


def passo_operacoes(hoje):
    console.print(f"[bold]Passo 3 — operações {TIPO_ENTRADA} dos Códigos ML ({DIAS_DA_JANELA} dias, 1 chamada, sem scroll)[/]")
    params = {
        "seller_id": user_id, "inventory_id": ",".join(CODIGOS_ML), "type": TIPO_ENTRADA,
        "date_from": (hoje - timedelta(days=DIAS_DA_JANELA)).isoformat(), "date_to": (hoje + timedelta(days=1)).isoformat(),
        "limit": LIMITE_POR_PAGINA,
    }
    registro = chamar(f"operações {TIPO_ENTRADA}", ENDPOINT_OPERACOES, params)
    corpo = registro["corpo"] if isinstance(registro["corpo"], dict) else {}
    operacoes = corpo.get("results") if registro["http"] == 200 and isinstance(corpo.get("results"), list) else []
    paging = corpo.get("paging") if isinstance(corpo.get("paging"), dict) else {}
    console.print(f"  janela: date_from={params['date_from']}  date_to={params['date_to']} (exclusivo)  |  recebidas={len(operacoes)}  total segundo a API={paging.get('total')}  scroll={'sim' if paging.get('scroll') else 'não'}")
    if paging.get("scroll") and isinstance(paging.get("total"), int) and paging["total"] > len(operacoes):
        console.print(f"  [yellow]Há mais páginas ({paging['total']} no total) e este script NÃO pagina. Reduza DIAS_DA_JANELA ou os Códigos.[/]")
    if registro["http"] == 200 and not operacoes:
        console.print(f"  [yellow]Nenhuma operação {TIPO_ENTRADA} nesta janela para estes Códigos. Se o envio é o pendente da tela, isso é o esperado "
                      "(ver 'COMO LER' no topo do arquivo): teste com um envio já processado.[/]")
    console.print()
    return registro, operacoes


def mostrar_operacoes(operacoes):
    if not operacoes:
        return
    ordenadas = sorted(operacoes, key=lambda o: o.get("date_created") or "", reverse=True)
    tabela = Table(box=box.SIMPLE_HEAVY, title=f"Operações {TIPO_ENTRADA} (mais recentes primeiro; até {LINHAS_NA_TELA})", title_justify="left")
    for coluna in ("data (Brasília)", "Código ML", "referências (external_references)", "números de detail"):
        tabela.add_column(coluna)
    for op in ordenadas[:LINHAS_NA_TELA]:
        quando = instante(op.get("date_created"))
        referencias = " ".join(f"{tipo}={valor}" for tipo, valor in referencias_da_operacao(op)) or "-"
        tabela.add_row(
            quando.strftime("%d/%m/%Y %H:%M") if quando else "-",
            t(str(op.get("inventory_id") or op.get("seller_product_id") or "-")),
            t(referencias), t(detalhe_numerico(op)),
        )
    console.print(tabela)
    if len(ordenadas) > LINHAS_NA_TELA:
        console.print(f"  ... e mais {len(ordenadas) - LINHAS_NA_TELA} no JSON.\n")

    grupos = {}
    for op in operacoes:
        chave = referencia_de_envio(op) or "(sem referência com 'inbound')"
        g = grupos.setdefault(chave, {"ops": 0, "codigos": set(), "unidades": 0, "tem_unidades": False, "datas": []})
        g["ops"] += 1
        g["codigos"].add(str(op.get("inventory_id") or op.get("seller_product_id") or "-"))
        u = unidades(op)
        if u is not None:
            g["unidades"] += u
            g["tem_unidades"] = True
        quando = instante(op.get("date_created"))
        if quando:
            g["datas"].append(quando)
    numeros_da_tela = {normalizar(e) for e in ENVIOS_DA_TELA}
    tabela = Table(box=box.SIMPLE_HEAVY, title="Envios vistos nas operações (agrupados pela referência com 'inbound')", title_justify="left")
    for coluna, alinhamento in (("referência", "left"), ("operações", "right"), ("Códigos", "right"), ("unidades (soma de |detail.available_quantity|)", "right"),
                                ("primeira", "left"), ("última", "left"), ("é o da tela?", "left")):
        tabela.add_column(coluna, justify=alinhamento)
    for chave, g in sorted(grupos.items()):
        valor = chave.split("=", 1)[1] if "=" in chave else ""
        eh_da_tela = "SIM" if normalizar(valor) in numeros_da_tela else "não"
        tabela.add_row(
            t(chave), str(g["ops"]), str(len(g["codigos"])), str(g["unidades"]) if g["tem_unidades"] else "-",
            min(g["datas"]).strftime("%d/%m/%Y") if g["datas"] else "-", max(g["datas"]).strftime("%d/%m/%Y") if g["datas"] else "-",
            f"[bold green]{eh_da_tela}[/]" if eh_da_tela == "SIM" else eh_da_tela,
        )
    console.print(tabela)


def passo_inventario(registros_com_corpo):
    console.print("[bold]Passo 4 — raio-x dos campos que a API devolveu (caminho | vezes | 1º exemplo)[/]")
    for registro in registros_com_corpo:
        if registro["http"] != 200:
            continue
        inventario = inventario_de_caminhos(registro["corpo"])
        if not inventario:
            continue
        tabela = Table(box=box.SIMPLE, title=f"#{registro['n']} {registro['rotulo']}", title_justify="left")
        tabela.add_column("caminho")
        tabela.add_column("vezes", justify="right")
        tabela.add_column("exemplo")
        for caminho, (vezes, exemplo) in sorted(inventario.items()):
            tabela.add_row(t(sem_id(caminho)), str(vezes), t(sem_id(repr(exemplo))[:60]))
        console.print(tabela)
    console.print()


def passo_procurar_valores(registros_com_corpo):
    console.print("[bold]Passo 5 — os valores que você vê na tela aparecem em alguma resposta?[/]")
    alvos = [(f"Envio N.º {e}", e) for e in ENVIOS_DA_TELA] + list(OUTROS_VALORES_DA_TELA.items())
    achados = {}
    tabela = Table(box=box.SIMPLE_HEAVY)
    tabela.add_column("o que é")
    tabela.add_column("valor da tela")
    tabela.add_column("onde apareceu")
    for rotulo, valor in alvos:
        procurado = normalizar(valor)
        so_digitos = procurado.isdigit()
        onde = []
        for registro in registros_com_corpo:
            if registro["http"] != 200:
                continue
            for caminho, folha in percorrer(registro["corpo"]):
                if folha is None or isinstance(folha, bool):
                    continue
                candidato = normalizar(folha)
                if (candidato == procurado) if so_digitos else (procurado in candidato):
                    onde.append(f"#{registro['n']} {caminho}")
        unicos = sorted(set(onde))
        achados[rotulo] = {"valor": valor, "onde": unicos}
        tabela.add_row(t(rotulo), t(str(valor)), t(", ".join(unicos[:4]) + (f" (+{len(unicos) - 4})" if len(unicos) > 4 else "")) if unicos else "[red]não apareceu em nenhuma resposta[/]")
    console.print(tabela)
    console.print()
    return achados


def fatos_medidos(r_tipo, pares, r_ops, operacoes, achados):
    """H1 a H5 só com o que foi medido. Sem conclusão."""
    fatos = []
    if r_ops["http"] is None:
        fatos.append(("H1  type=INBOUND_RECEPTION aceito", "não medido: a chamada de operações não chegou a ser feita ou não teve resposta"))
    elif r_ops["http"] == 200:
        fatos.append(("H1  type=INBOUND_RECEPTION aceito", f"sim (HTTP 200, {len(operacoes)} operação(ões) na janela)"))
    else:
        corpo = r_ops["corpo"]
        fatos.append(("H1  type=INBOUND_RECEPTION aceito", f"não: HTTP {r_ops['http']} {erro_curto(corpo)[:120]}"))
    com_ref = [op for op in operacoes if referencias_da_operacao(op)]
    tipos_de_ref = sorted({tipo for op in operacoes for tipo, _ in referencias_da_operacao(op)})
    inbound = sorted({referencia_de_envio(op) for op in operacoes if referencia_de_envio(op)})
    if not operacoes:
        fatos.append(("H2  operação traz o envio em external_references", "não medido: nenhuma operação voltou"))
    else:
        fatos.append(("H2  operação traz o envio em external_references",
                      f"{len(com_ref)}/{len(operacoes)} operações têm external_references; tipos vistos: {', '.join(tipos_de_ref) or '-'}; "
                      f"envios distintos (referência com 'inbound'): {len(inbound)}"))
    for e in ENVIOS_DA_TELA:
        achou_em_ref = any(normalizar(valor) == normalizar(e) for op in operacoes for _, valor in referencias_da_operacao(op))
        if not operacoes:
            fatos.append((f"H3  Envio N.º {e} nas referências", "não medido: nenhuma operação voltou"))
        else:
            fatos.append((f"H3  Envio N.º {e} nas referências", "SIM" if achou_em_ref else "não"))
    if not pares:
        fatos.append(("H4  include_attributes=conditions muda a resposta", "não medido"))
    for codigo, (simples, com_conditions) in pares.items():
        extra = campos_a_mais(simples, com_conditions)
        if extra is None:
            fatos.append((f"H4  conditions muda o estoque de {codigo}", f"não medido (HTTP {simples['http']} / {com_conditions['http']})"))
        else:
            fatos.append((f"H4  conditions muda o estoque de {codigo}", ("sim, campos a mais: " + ", ".join(extra)) if extra else "não: mesmos campos"))
    aparece = [rotulo for rotulo, dado in achados.items() if dado["onde"]]
    ausente = [rotulo for rotulo, dado in achados.items() if not dado["onde"]]
    fatos.append(("H5  valores da tela achados nas respostas", f"achou: {', '.join(aparece) or 'nenhum'} | não achou: {', '.join(ausente) or 'nenhum'}"))
    if r_tipo is not None:
        fatos.append(("Extra  resposta a um type inventado", f"HTTP {r_tipo['http']} {erro_curto(r_tipo['corpo'])[:260]}"))
    return fatos


def salvar_json(fatos, achados, interrompido):
    saida = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "conta": CONTA, "interrompido_pelo_usuario": interrompido,
        "configuracao": {
            "codigos_ml": CODIGOS_ML, "envios_da_tela": ENVIOS_DA_TELA, "outros_valores_da_tela": OUTROS_VALORES_DA_TELA,
            "dias_da_janela": DIAS_DA_JANELA, "tipo_buscado": TIPO_ENTRADA,
        },
        "fatos_medidos": [{"item": a, "resultado": b} for a, b in fatos],
        "valores_da_tela_procurados": achados,
        "chamadas": chamadas,
    }
    CAMINHO_SAIDA.write_text(json.dumps(mascarar(saida), ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    global user_id
    load_dotenv(dotenv_path=_RAIZ_DO_PROJETO / ".env")
    user_id = os.getenv(f"{CONTA}_USER_ID")
    if not user_id:
        console.print(f"[bold red]{CONTA}_USER_ID não encontrado no .env da raiz do repo.[/]")
        sys.exit(1)
    if not CODIGOS_ML or DIAS_DA_JANELA > 59:
        console.print("[bold red]Configuração inválida:[/] CODIGOS_ML não pode ficar vazio e DIAS_DA_JANELA deve ser no máximo 59.")
        sys.exit(1)

    hoje = datetime.now(FUSO).date()
    chamadas_previstas = (1 if SONDAR_LISTA_DE_TIPOS else 0) + 2 * len(CODIGOS_ML) + 1
    console.print(
        f"Conta [bold]{CONTA}[/] | Códigos ML: {', '.join(CODIGOS_ML)} | Envio(s) da tela: {', '.join(ENVIOS_DA_TELA) or '-'} | hoje = {hoje:%d/%m/%Y}\n"
        f"Só GET. [bold]{chamadas_previstas}[/] chamada(s) previstas (mais até {TENTATIVAS_SE_429 - 1} repetição(ões) por chamada se vier 429, com {PAUSA_SE_429_S}s de pausa):\n"
        f"  {'1 de operações com type inventado; ' if SONDAR_LISTA_DE_TIPOS else ''}{2 * len(CODIGOS_ML)} de estoque (2 por Código); 1 de operações {TIPO_ENTRADA}.\n"
    )

    interrompido = False
    r_tipo, pares, r_ops, operacoes, achados = None, {}, {"http": None, "corpo": None}, [], {}
    try:
        obter_token_valido(CONTA)                # falha cedo se a conta não estiver autenticada (o token nunca é mostrado)
        if SONDAR_LISTA_DE_TIPOS:
            r_tipo = passo_tipo_inventado(CODIGOS_ML[0], hoje)
        pares = passo_estoque()
        r_ops, operacoes = passo_operacoes(hoje)
        mostrar_operacoes(operacoes)
        com_corpo = [r for r in chamadas if r["http"] == 200]
        passo_inventario(com_corpo)
        achados = passo_procurar_valores(com_corpo)
    except KeyboardInterrupt:
        interrompido = True
        console.print("\n[yellow]Interrompido por você. O que já foi medido será resumido e salvo.[/]")
    except Exception as erro:                     # exploração: mostra o erro (sem seller_id) e ainda salva o que já foi coletado
        console.print(f"\n[bold red]Erro: {t(sem_id(type(erro).__name__ + ': ' + str(erro))[:300])}[/]")
    finally:
        if chamadas:
            fatos = fatos_medidos(r_tipo, pares, r_ops, operacoes, achados)
            console.print("[bold]Passo 6 — fatos medidos (sem conclusão)[/]")
            tabela = Table(box=box.SIMPLE_HEAVY, show_header=False)
            tabela.add_column("item")
            tabela.add_column("resultado")
            for item, resultado in fatos:
                tabela.add_row(t(item), t(sem_id(resultado)))
            console.print(tabela)
            salvar_json(fatos, achados, interrompido)
            console.print(f"JSON salvo em: {CAMINHO_SAIDA.name} ({len(chamadas)} chamada(s)). Sem seller_id e sem token.")


if __name__ == "__main__":
    main()
