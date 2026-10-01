# scripts_exploracao_ML/gerar_planilha_llm_inventario.py
#
# Gera a PLANILHA ÚNICA da empresa (um .xlsx) que a LLM vai preencher em
# massa: contexto do produto (ERP + títulos), fila de campos por SKU (com
# limite, opções válidas e valores atuais nos MLBs) e abas de apoio.
# Estrutura validada no mockup: LEIA-ME, INSTRUCOES_LLM, SKUS, CAMPOS,
# LISTAS, MLBS (+ RESUMO com os números da geração).
#
# Regra de desenho (Matheus): a ficha é do SKU. Cada SKU recebe a UNIÃO dos
# campos "Características principais" pedidos pelas categorias de todos os
# seus MLBs, com 1 linha por campo. Metadados são fundidos entre categorias
# (obrigatório se qualquer uma exigir; lista = interseção por id; texto
# livre = menor limite) e toda divergência vira "Avisos".
#
# Só leitura: só GET na API, nada gravado no banco, nenhuma LLM chamada.
#
# Como roda:
#   1) LIMITE_SKUS = 30  -> teste rápido (~1-2 min), confere o formato
#   2) LIMITE_SKUS = None -> inventário inteiro (~4.000 chamadas à API)
# As respostas da API ficam em cache (cache_planilha_llm_*.json, já
# ignorados pelo .gitignore): rodar de novo não baixa tudo outra vez.
# Pra forçar download novo, apague os 2 arquivos de cache ou ponha
# USAR_CACHE = False.
#
# Pré-requisito: banco atualizado (rodar a sincronização antes, como de
# costume).

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, TextColumn,
    TimeElapsedColumn, TimeRemainingColumn,
)

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"  # "MB" (Magazine) ou "SV" (Samvale)
LIMITE_SKUS = None  # None = inventário inteiro. Número = amostra espalhada por categoria (teste rápido).
STATUS_ACEITOS = {"active", "paused"}  # status que entram na planilha (os demais ficam de fora, igual ao script de contexto)
TAMANHO_LOTE = 25  # SKUs por lote (coluna Lote), agrupados por categoria
THREADS = 40  # chamadas simultâneas à API (o pool do projeto aguenta 50; 30 deixa folga e respeita o rate limit do ML)
USAR_CACHE = True  # False = baixa tudo de novo da API
VINCULAR_PELO_EAN = True  # SKU sem Produto, mas no formato F+EAN13.NNN: tenta achar o Produto pelo EAN (marcado como "inferido" na planilha)
LIMITE_OPCOES_NA_CELULA = 40  # lista com mais opções que isso vai pra aba LISTAS
# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
PASTA_LOGS = PASTA_SCRIPT / "logs"
NOME_LOG = "gerar_planilha_llm_inventario"
CAMINHO_CACHE_ITENS = PASTA_SCRIPT / f"cache_planilha_llm_itens_{CONTA}.json"
CAMINHO_CACHE_CATEGORIAS = PASTA_SCRIPT / "cache_planilha_llm_categorias.json"

console = Console()

REGEX_SKU_COM_EAN = re.compile(r"^F(\d{13})\.\d{3}$")
CARACTERES_ILEGAIS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
LIMITE_CELULA_EXCEL = 32000


# ──────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO DO DJANGO (dentro de função: o resto do arquivo é "puro")
# ──────────────────────────────────────────────────────────────────────

def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, "manage.py")):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError("Não foi possível encontrar manage.py subindo a partir deste script.")


def iniciar_django():
    _adicionar_raiz_do_projeto_ao_path()
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "projeto_sistema_interno_mb_sv.settings")
    django.setup()

    from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
    definir_empresa_ativa({"MB": EMPRESA_MAGAZINE, "SV": EMPRESA_SAMVALE}[CONTA])
    # * [EXPLICAÇÃO] → Sem isso o Django cai no banco default. A empresa
    #                  ativa é thread-local: todas as consultas ao banco
    #                  rodam na thread principal; as threads só chamam a API.


# ──────────────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ──────────────────────────────────────────────────────────────────────

def limpar_texto(valor):
    if valor is None:
        return None
    texto = CARACTERES_ILEGAIS.sub("", str(valor))
    if len(texto) > LIMITE_CELULA_EXCEL:
        texto = texto[:LIMITE_CELULA_EXCEL] + " […cortado]"
    return texto


def texto_ou_none(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def numero_ou_none(valor):
    # * [EXPLICAÇÃO] → Medida 0 no ERP = "nunca cadastrada" -> vira vazio.
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def tem_tag(attr, nome_tag):
    tags = attr.get("tags")
    if isinstance(tags, dict):
        return bool(tags.get(nome_tag))
    if isinstance(tags, list):
        return nome_tag in tags
    return False


def extrair_sku(item_ou_variacao):
    # Mesma lógica de api_mercado_livre/detalhes_ml.py: SELLER_SKU nos
    # atributos; se não houver, seller_custom_field.
    for attr in item_ou_variacao.get("attributes") or []:
        if attr.get("id") == "SELLER_SKU":
            return attr.get("value_name")
    return item_ou_variacao.get("seller_custom_field")


def formatar_valor_atual(attr):
    """value_name; senão o nome do 1º item de values; senão, se só existir id (ex.: marcado N/A), mostra o id pra não perder a informação."""
    valor = attr.get("value_name")
    if valor is None:
        for item in attr.get("values") or []:
            if item.get("name"):
                valor = item["name"]
                break
    if isinstance(valor, str):
        valor = valor.strip() or None
    if valor is None:
        value_id = attr.get("value_id")
        if value_id is None:
            ids = [i.get("id") for i in attr.get("values") or [] if i.get("id") is not None]
            value_id = ids[0] if ids else None
        if value_id is not None:
            return f"[sem nome; id={value_id}]"
    return valor


def eh_marcador_sem_nome(valor):
    return isinstance(valor, str) and valor.startswith("[sem nome")


# ──────────────────────────────────────────────────────────────────────
# CACHE EM DISCO
# ──────────────────────────────────────────────────────────────────────

def carregar_cache(caminho):
    if USAR_CACHE and caminho.exists():
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            console.print(f"[yellow]Cache ilegível ({caminho.name}) — ignorando e baixando de novo.[/yellow]")
    return {}


def salvar_cache(caminho, dados):
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    os.replace(temporario, caminho)


# ──────────────────────────────────────────────────────────────────────
# API DO MERCADO LIVRE (só GET)
# ──────────────────────────────────────────────────────────────────────

def buscar_item(mlb):
    """GET /items/{mlb}: valores atuais + identidade do anúncio no ML (tudo da mesma chamada)."""
    from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api

    resposta = chamar_api(
        "GET", f"/items/{mlb}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={"include_internal_attributes": "true"},
        nome_log=NOME_LOG,
    )
    corpo = resposta.json()

    valores = {}
    for attr in corpo.get("attributes") or []:
        attr_id = attr.get("id")
        if attr_id:
            valores[attr_id] = formatar_valor_atual(attr)

    variacoes = [
        {
            "id": var.get("id"),
            "sku": extrair_sku(var),
            "atributos": " / ".join(
                c.get("value_name", "") for c in var.get("attribute_combinations", []) if c.get("value_name")
            ) or None,
        }
        for var in corpo.get("variations") or []
    ]

    return {
        "category_id": corpo.get("category_id"),
        "status_ml": corpo.get("status"),
        "sku_no_ml": extrair_sku(corpo),
        "family_id": corpo.get("family_id"),
        "variacoes": variacoes,
        "valores": valores,
    }


def buscar_categoria(category_id):
    """Card 'Características principais' (grupo MAIN menos allow_variations) + definições (tipo, limite, opções) só dos atributos do card."""
    from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api

    resposta_specs = chamar_api(
        "GET", f"/categories/{category_id}/technical_specs/input",
        pasta_logs=PASTA_LOGS, conta=CONTA, nome_log=NOME_LOG,
    )
    card = {}
    for grupo in resposta_specs.json().get("groups", []):
        if grupo.get("id") != "MAIN":
            continue
        for componente in grupo.get("components", []):
            for attr in componente.get("attributes", []):
                attr_id = attr.get("id")
                if not attr_id or tem_tag(attr, "allow_variations"):
                    continue
                card[attr_id] = {
                    "label": attr.get("label") or attr.get("name") or attr_id,
                    "required": tem_tag(attr, "required"),
                }

    resposta_attrs = chamar_api(
        "GET", f"/categories/{category_id}/attributes",
        pasta_logs=PASTA_LOGS, conta=CONTA, nome_log=NOME_LOG,
    )
    definicoes = {}
    for attr in resposta_attrs.json():
        attr_id = attr.get("id")
        if not attr_id or attr_id not in card:
            continue
        definicoes[attr_id] = {
            "value_type": attr.get("value_type"),
            "value_max_length": attr.get("value_max_length"),
            "values": [{"id": o.get("id"), "name": o.get("name")} for o in attr.get("values") or []],
            "allowed_units": [{"id": u.get("id"), "name": u.get("name")} for u in attr.get("allowed_units") or []],
        }

    return {"card": card, "defs": definicoes}


def buscar_em_paralelo(descricao, chaves, funcao, cache, caminho_cache):
    """Baixa em threads o que ainda não está no cache. Devolve {chave: mensagem de erro} das que falharam."""
    falhas = {}
    faltantes = [c for c in chaves if c not in cache]
    console.print(f"{descricao}: {len(chaves)} no total, {len(chaves) - len(faltantes)} já no cache, "
                  f"[bold]{len(faltantes)} a baixar[/bold].")
    if not faltantes:
        return falhas

    pool = ThreadPoolExecutor(max_workers=THREADS)
    desde_o_ultimo_salvamento = 0
    try:
        futuros = {pool.submit(funcao, chave): chave for chave in faltantes}
        with Progress(
            TextColumn("[bold]{task.description}"), BarColumn(), MofNCompleteColumn(),
            TimeElapsedColumn(), TimeRemainingColumn(), console=console,
        ) as progresso:
            tarefa = progresso.add_task(descricao, total=len(faltantes))
            for futuro in as_completed(futuros):
                chave = futuros[futuro]
                try:
                    cache[chave] = futuro.result()
                except Exception as erro:  # uma falha não derruba o lote inteiro
                    falhas[chave] = f"{type(erro).__name__}: {erro}"[:300]
                progresso.advance(tarefa)
                desde_o_ultimo_salvamento += 1
                if desde_o_ultimo_salvamento >= 400:
                    salvar_cache(caminho_cache, cache)
                    desde_o_ultimo_salvamento = 0
    except KeyboardInterrupt:
        console.print("[yellow]Interrompido — salvando o que já foi baixado...[/yellow]")
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        pool.shutdown(wait=True)
        salvar_cache(caminho_cache, cache)

    if falhas:
        console.print(f"[yellow]{len(falhas)} falha(s) em '{descricao}' (primeiras 3):[/yellow]")
        for chave, mensagem in list(falhas.items())[:3]:
            console.print(f"  {chave}: {mensagem}")
    return falhas


# ──────────────────────────────────────────────────────────────────────
# LEITURA DO BANCO
# ──────────────────────────────────────────────────────────────────────

def carregar_do_banco():
    """
    Agrupa as variações elegíveis por SKU (produto.sku -> sku_ml -> MLB, mesma
    ordem de fallback de carregar_variacoes_por_sku) e por MLB. Mesmos filtros
    do script de contexto: fora anúncio "fóssil", fora catálogo, só STATUS_ACEITOS
    (MLB sem tipo_de_anuncio entra, igual ao fluxo anterior).
    Query própria (e não carregar_variacoes_por_sku) porque aquela carrega
    qualidade/promoções/recomendações da base inteira, o que aqui não é usado.
    """
    from django.db.models import Q
    from mercado_livre.models import TipoDeAnuncioMercadoLivre, VariacaoAnuncioMercadoLivre

    classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo
    consulta = (
        VariacaoAnuncioMercadoLivre.objects
        .select_related("anuncio", "anuncio__tipo_de_anuncio", "produto")
        .exclude(anuncio__eh_fossil_migracao=True)
        .exclude(anuncio__tipo_de_anuncio__classificacao_catalogo=classificacao.CATALOGO)
        .filter(
            Q(anuncio__tipo_de_anuncio__status__in=STATUS_ACEITOS)
            | Q(anuncio__tipo_de_anuncio__isnull=True)
        )
    )

    grupos = {}
    for variacao in consulta:
        anuncio = variacao.anuncio
        tipo = anuncio.tipo_de_anuncio
        produto = variacao.produto
        chave = (produto.sku if produto is not None and produto.sku else None) or variacao.sku_ml or anuncio.mlb

        grupo = grupos.setdefault(chave, {
            "sku": chave, "produto": None, "vinculo": None,
            "mlbs": {}, "categorias_db": Counter(),
        })
        if produto is not None and grupo["produto"] is None:
            grupo["produto"] = produto
            grupo["vinculo"] = "SKU"

        mlb = grupo["mlbs"].setdefault(anuncio.mlb, {
            "mlb": anuncio.mlb,
            "titulo": anuncio.titulo_anuncio,
            "status": tipo.status if tipo else None,
            "status_txt": tipo.get_status_display() if tipo else "—",
            "tipo_txt": tipo.get_classificacao_catalogo_display() if tipo else "—",
            "permalink": anuncio.permalink,
            "variacoes_banco": [],
        })
        mlb["variacoes_banco"].append({
            "variacao_id": variacao.variacao_id,
            "sku_ml": variacao.sku_ml,
            "produto_sku": produto.sku if produto is not None else None,
        })
        if variacao.categoria_id:
            grupo["categorias_db"][variacao.categoria_id] += 1

    return grupos


def vincular_erp_pelo_ean(grupos):
    """
    O importador do ERP liga anúncio -> Produto SÓ pelo SKU. Aqui, só pra esta
    planilha (nada é gravado), SKUs sem Produto no formato F+EAN13.NNN tentam
    achar o Produto pelo EAN. O vínculo fica marcado como "EAN (inferido)".
    """
    if not VINCULAR_PELO_EAN:
        return
    from produtos.models import Produto

    ean_por_chave = {}
    for chave, grupo in grupos.items():
        if grupo["produto"] is None:
            achado = REGEX_SKU_COM_EAN.match(chave)
            if achado:
                ean_por_chave[chave] = achado.group(1)
    if not ean_por_chave:
        return

    produto_por_ean = {p.ean: p for p in Produto.objects.filter(ean__in=set(ean_por_chave.values()))}
    for chave, ean in ean_por_chave.items():
        produto = produto_por_ean.get(ean)
        if produto is not None:
            grupos[chave]["produto"] = produto
            grupos[chave]["vinculo"] = "EAN"


def carregar_ficha_tecnica(mlbs):
    """Status do critério 'Ficha Técnica' (grupo UP_TECHNICAL_SPECIFICATIONS_MAIN) por MLB."""
    from mercado_livre.models import CriterioQualidade, QualidadeAnuncioCriterio

    status_por_mlb = defaultdict(set)
    linhas = (
        QualidadeAnuncioCriterio.objects
        .filter(criterio__grupo=CriterioQualidade.Grupo.TECH_SPECS)
        .values_list("qualidade__variacao__anuncio__mlb", "status")
    )
    for mlb, status in linhas.iterator():
        if mlb in mlbs:
            status_por_mlb[mlb].add(status)

    resultado = {}
    for mlb in mlbs:
        status = status_por_mlb.get(mlb, set())
        if "nao_aprovado" in status:
            resultado[mlb] = "Não aprovado"
        elif "aprovado" in status:
            resultado[mlb] = "Aprovado"
        elif status:
            resultado[mlb] = "Não aplicável"
        else:
            resultado[mlb] = "Sem dado"
    return resultado


def carregar_caminhos_de_categoria(category_ids):
    from mercado_livre.models import CategoriaMercadoLivre

    return dict(
        CategoriaMercadoLivre.objects
        .filter(category_id__in=list(category_ids))
        .values_list("category_id", "caminho_completo")
    )


def ordenar_e_limitar(grupos):
    """Ordena por categoria principal (lotes coerentes) e, se LIMITE_SKUS, pega uma amostra espalhada."""
    def categoria_principal(grupo):
        if grupo["categorias_db"]:
            return grupo["categorias_db"].most_common(1)[0][0]
        return ""

    chaves = sorted(grupos, key=lambda k: (categoria_principal(grupos[k]), k))
    if LIMITE_SKUS and LIMITE_SKUS < len(chaves):
        passo = len(chaves) / LIMITE_SKUS
        chaves = [chaves[int(i * passo)] for i in range(LIMITE_SKUS)]
    return chaves


# ──────────────────────────────────────────────────────────────────────
# FUSÃO DOS METADADOS DE UM CAMPO ENTRE AS CATEGORIAS DO SKU
# ──────────────────────────────────────────────────────────────────────

def fundir_metadados(attr_id, categorias, cards, definicoes):
    """
    A ficha é do SKU: o mesmo campo pode vir de mais de 1 categoria, e o valor
    escolhido precisa servir em TODAS as que pedem o campo.
      - obrigatório   = qualquer categoria exigir;
      - lista fechada = interseção (por id) entre as categorias que têm lista;
      - texto livre   = menor tamanho máximo.
    Divergência relevante entre categorias vira linha em "avisos".
    """
    metas = {c: cards[c][attr_id] for c in categorias}
    defs = {c: definicoes[c].get(attr_id, {}) for c in categorias}
    avisos = []

    obrigatorias = [c for c in categorias if metas[c]["required"]]
    if obrigatorias and len(obrigatorias) < len(categorias):
        avisos.append(f"obrigatório só em {', '.join(obrigatorias)} (nas outras categorias do SKU é opcional).")

    resultado = {
        "label": metas[categorias[0]]["label"],
        "obrigatorio": bool(obrigatorias),
        "limite": None, "opcoes": None, "unidades": None,
    }

    opcoes_por_categoria = {c: d.get("values") or [] for c, d in defs.items()}
    com_lista = [c for c, opcoes in opcoes_por_categoria.items() if opcoes]

    if com_lista:
        resultado["tipo"] = "Lista fechada"
        if len(com_lista) < len(categorias):
            sem_lista = [c for c in categorias if c not in com_lista]
            avisos.append(f"lista fechada em {', '.join(com_lista)} e texto livre em {', '.join(sem_lista)}; "
                          f"a lista vale só como restrição nas categorias que têm lista.")
        conjuntos = [frozenset(o.get("id") for o in opcoes_por_categoria[c]) for c in com_lista]
        ids_comuns = set.intersection(*[set(conjunto) for conjunto in conjuntos])
        comuns = [
            {"id": o.get("id"), "name": o.get("name")}
            for o in opcoes_por_categoria[com_lista[0]] if o.get("id") in ids_comuns
        ]
        if len(set(conjuntos)) > 1:
            avisos.append(f"as opções diferem entre as categorias; lista = interseção ({len(comuns)} opção(ões) em comum).")
        if not comuns:
            avisos.append("ATENÇÃO: nenhuma opção em comum entre as categorias — nenhum valor da lista serve para todas.")
        resultado["opcoes"] = comuns
    else:
        tipos_api = {d.get("value_type") for d in defs.values() if d.get("value_type")}
        if "number_unit" in tipos_api:
            resultado["tipo"] = "Número + unidade"
        elif "number" in tipos_api:
            resultado["tipo"] = "Número"
        else:
            resultado["tipo"] = "Texto livre"
        if len(tipos_api) > 1:
            avisos.append(f"o tipo do campo difere entre as categorias ({', '.join(sorted(tipos_api))}).")

        tamanhos = {c: d["value_max_length"] for c, d in defs.items() if d.get("value_max_length")}
        if tamanhos:
            resultado["limite"] = min(tamanhos.values())
            if len(set(tamanhos.values())) > 1:
                avisos.append(f"tamanho máximo difere entre as categorias ({tamanhos}); usando o menor.")

        unidades_por_categoria = {c: d.get("allowed_units") or [] for c, d in defs.items()}
        com_unidades = [c for c, unidades in unidades_por_categoria.items() if unidades]
        if com_unidades:
            ids_comuns = set.intersection(*[set(u.get("id") for u in unidades_por_categoria[c]) for c in com_unidades])
            resultado["unidades"] = [
                u.get("name") for u in unidades_por_categoria[com_unidades[0]] if u.get("id") in ids_comuns
            ]

    resultado["avisos"] = avisos
    return resultado


def montar_alertas(sku, status_banco, dados):
    """Compara o que o banco acha do MLB com o que o ML devolveu agora (pai com variações, SKU divergente, status)."""
    alertas = []
    variacoes = dados["variacoes"]
    skus_das_variacoes = sorted({v["sku"] for v in variacoes if v["sku"]})

    if len(variacoes) > 1:
        alertas.append(f"MLB com {len(variacoes)} variações no ML.")
    if len(skus_das_variacoes) > 1:
        alertas.append(f"variações com SKUs diferentes no ML: {skus_das_variacoes}.")
    if skus_das_variacoes and sku not in skus_das_variacoes:
        alertas.append(f"o SKU do grupo ({sku}) não aparece entre os SKUs das variações no ML: {skus_das_variacoes}.")
    if dados["sku_no_ml"] and dados["sku_no_ml"] != sku:
        alertas.append(f"SKU gravado no anúncio no ML ({dados['sku_no_ml']}) difere do SKU do grupo ({sku}).")
    if status_banco and dados["status_ml"] and status_banco != dados["status_ml"]:
        alertas.append(f"status difere: banco '{status_banco}', ML '{dados['status_ml']}'.")
    return alertas


# ──────────────────────────────────────────────────────────────────────
# MONTAGEM DAS LINHAS (puro: não toca em banco, API nem arquivo)
# ──────────────────────────────────────────────────────────────────────

def texto_qtd_mlbs(mlbs):
    ativos = sum(1 for m in mlbs if m["status"] == "active")
    pausados = sum(1 for m in mlbs if m["status"] == "paused")
    outros = len(mlbs) - ativos - pausados
    texto = f"{len(mlbs)} (ativos: {ativos} / pausados: {pausados}"
    if outros:
        texto += f" / outros: {outros}"
    return texto + ")"


def montar_tudo(grupos, chaves, itens, categorias, caminhos_categoria, ficha_por_mlb):
    cards = {c: dados["card"] for c, dados in categorias.items()}
    definicoes = {c: dados["defs"] for c, dados in categorias.items()}

    skus_linhas, campos_linhas, mlbs_linhas, listas_linhas = [], [], [], []
    ids_de_lista = {}
    estat = Counter()
    campos_por_attr = Counter()
    rotulo_por_attr = {}
    conjuntos_de_campos = Counter()
    codigos_de_aviso = Counter()
    skus_por_mlb = defaultdict(set)
    skus_sem_dados = []
    cobertura_erp = Counter()
    multi_categoria = 0
    maior_lista = 0
    lote_atual = 0
    contador_no_lote = 0

    for chave in chaves:
        grupo = grupos[chave]
        todos_mlbs = [grupo["mlbs"][m] for m in sorted(grupo["mlbs"])]
        mlbs_ok = [m for m in todos_mlbs
                   if m["mlb"] in itens and itens[m["mlb"]].get("category_id") in cards]
        mlbs_ok_ids = {m["mlb"] for m in mlbs_ok}

        for m in todos_mlbs:
            skus_por_mlb[m["mlb"]].add(chave)

        if not mlbs_ok:
            skus_sem_dados.append(chave)
            for m in todos_mlbs:
                mlbs_linhas.append([m["mlb"], chave, m["titulo"], "(sem leitura da API)", m["status_txt"],
                                    m["tipo_txt"], ficha_por_mlb.get(m["mlb"], "Sem dado"),
                                    "não foi possível ler este MLB (ou a categoria dele) na API.", m["permalink"]])
            continue

        if contador_no_lote == 0 or contador_no_lote >= TAMANHO_LOTE:
            lote_atual += 1
            contador_no_lote = 0
        contador_no_lote += 1

        produto = grupo["produto"]
        categorias_do_sku = [c for c, _ in Counter(itens[m["mlb"]]["category_id"] for m in mlbs_ok).most_common()]
        if len(categorias_do_sku) > 1:
            multi_categoria += 1

        # ---- aba SKUS
        if produto is None:
            vinculo_txt, ativo_txt = "Não", "—"
        else:
            vinculo_txt = "Sim (SKU)" if grupo["vinculo"] == "SKU" else "Sim (EAN inferido)"
            ativo_txt = "Sim" if produto.ativo_no_erp else "Não"

        aprovados = sum(1 for m in todos_mlbs if ficha_por_mlb.get(m["mlb"]) == "Aprovado")
        sem_dado = sum(1 for m in todos_mlbs if ficha_por_mlb.get(m["mlb"], "Sem dado") == "Sem dado")
        ficha_txt = f"{aprovados}/{len(todos_mlbs)} aprovados" + (f" ({sem_dado} sem dado)" if sem_dado else "")

        titulo_produto = texto_ou_none(produto.titulo) if produto is not None else None
        medidas = [numero_ou_none(getattr(produto, campo, None)) if produto is not None else None
                   for campo in ("altura_produto_sem_embalar", "largura_produto_sem_embalar",
                                 "comprimento_produto_sem_embalar", "peso_produto_sem_embalar")]

        if produto is not None:
            cobertura_erp["com_erp"] += 1
            cobertura_erp["via_" + grupo["vinculo"]] += 1
            if not produto.ativo_no_erp:
                cobertura_erp["inativo_no_erp"] += 1
            if texto_ou_none(produto.marca):
                cobertura_erp["marca"] += 1
            if texto_ou_none(produto.cod_fabricante):
                cobertura_erp["cod_fabricante"] += 1
            if texto_ou_none(produto.descricao):
                cobertura_erp["descricao"] += 1
            if texto_ou_none(produto.ncm):
                cobertura_erp["ncm"] += 1
            if texto_ou_none(produto.imagem_url):
                cobertura_erp["imagem"] += 1
            preenchidas = sum(1 for x in medidas if x is not None)
            cobertura_erp["medidas_4_de_4" if preenchidas == 4 else ("medidas_parciais" if preenchidas else "medidas_nenhuma")] += 1
        else:
            cobertura_erp["sem_erp"] += 1

        caminho_ml = "\n".join(f"{c} · {caminhos_categoria.get(c, '(nome não encontrado)')}" for c in categorias_do_sku)
        titulos_mlbs = "\n".join(f"{m['mlb']} · {m['titulo']}" for m in todos_mlbs)

        skus_linhas.append([
            chave, lote_atual, titulo_produto,
            texto_ou_none(produto.marca) if produto is not None else None,
            texto_ou_none(produto.cod_fabricante) if produto is not None else None,
            texto_ou_none(produto.categoria) if produto is not None else None,
            caminho_ml,
            texto_ou_none(produto.ncm) if produto is not None else None,
            texto_ou_none(produto.ean) if produto is not None else None,
            medidas[0], medidas[1], medidas[2], medidas[3],
            texto_ou_none(produto.descricao) if produto is not None else None,
            titulos_mlbs,
            texto_ou_none(produto.imagem_url) if produto is not None else None,
            vinculo_txt, ativo_txt, texto_qtd_mlbs(todos_mlbs), ", ".join(categorias_do_sku), ficha_txt,
        ])

        # ---- aba MLBS
        for m in todos_mlbs:
            if m["mlb"] in mlbs_ok_ids:
                dados = itens[m["mlb"]]
                alertas = montar_alertas(chave, m["status"], dados)
                if len(dados["variacoes"]) > 1:
                    estat["mlbs_com_varias_variacoes"] += 1
                if alertas:
                    estat["mlbs_com_alerta"] += 1
                mlbs_linhas.append([m["mlb"], chave, m["titulo"], dados["category_id"], m["status_txt"],
                                    m["tipo_txt"], ficha_por_mlb.get(m["mlb"], "Sem dado"),
                                    "\n".join(alertas), m["permalink"]])
            else:
                mlbs_linhas.append([m["mlb"], chave, m["titulo"], "(sem leitura da API)", m["status_txt"],
                                    m["tipo_txt"], ficha_por_mlb.get(m["mlb"], "Sem dado"),
                                    "não foi possível ler este MLB (ou a categoria dele) na API.", m["permalink"]])

        # ---- aba CAMPOS: união dos campos pedidos pelas categorias do SKU
        campos_do_sku = []
        for categoria in categorias_do_sku:
            for attr_id in cards[categoria]:
                if attr_id not in campos_do_sku:
                    campos_do_sku.append(attr_id)
        conjuntos_de_campos[frozenset(campos_do_sku)] += 1
        if not campos_do_sku:
            estat["skus_sem_campos"] += 1

        produto_para_campos = titulo_produto or ("(sem ERP) " + (mlbs_ok[0]["titulo"] or mlbs_ok[0]["mlb"]))

        for attr_id in campos_do_sku:
            categorias_do_campo = [c for c in categorias_do_sku if attr_id in cards[c]]
            meta = fundir_metadados(attr_id, categorias_do_campo, cards, definicoes)
            avisos = list(meta["avisos"])
            codigos = []

            linhas_atuais = []
            valores_pedidos = []
            for m in mlbs_ok:
                if attr_id in cards[itens[m["mlb"]]["category_id"]]:
                    valor = itens[m["mlb"]]["valores"].get(attr_id)
                    valores_pedidos.append(valor)
                    linhas_atuais.append(f"{m['mlb']}: {valor if valor is not None else '(vazio)'}")
                else:
                    linhas_atuais.append(f"{m['mlb']}: —")

            if meta["avisos"]:
                codigos.append("diferença entre categorias")
            distintos = {v for v in valores_pedidos if v is not None}
            vazios = sum(1 for v in valores_pedidos if v is None)
            if len(distintos) > 1:
                avisos.append(f"{len(distintos)} valores diferentes entre os MLBs.")
                codigos.append("valores diferentes entre MLBs")
            if vazios and distintos:
                avisos.append(f"vazio em {vazios} de {len(valores_pedidos)} MLB(s).")
                codigos.append("vazio em parte dos MLBs")
            if vazios and not distintos:
                avisos.append("vazio em todos os MLBs.")
                codigos.append("vazio em todos os MLBs")
            if meta["tipo"] == "Lista fechada" and meta["opcoes"]:
                nomes_validos = {str(o["name"]).strip().lower() for o in meta["opcoes"]}
                fora = sorted(v for v in distintos
                              if not eh_marcador_sem_nome(v) and v.strip().lower() not in nomes_validos)
                if fora:
                    avisos.append("valor atual fora da lista: " + ", ".join(f"'{v}'" for v in fora) + ".")
                    codigos.append("valor atual fora da lista")
            if any(eh_marcador_sem_nome(v) for v in distintos):
                codigos.append("valor sem nome (ex.: N/A)")
            for codigo in codigos:
                codigos_de_aviso[codigo] += 1

            # ---- opções válidas (inline ou aba LISTAS)
            id_lista = None
            if meta["tipo"] == "Lista fechada":
                if not meta["opcoes"]:
                    texto_opcoes = "(nenhuma opção em comum entre as categorias)"
                elif len(meta["opcoes"]) <= LIMITE_OPCOES_NA_CELULA:
                    texto_opcoes = "; ".join(str(o["name"]) for o in meta["opcoes"])
                else:
                    chave_lista = (attr_id, tuple(o["id"] for o in meta["opcoes"]))
                    if chave_lista not in ids_de_lista:
                        ids_de_lista[chave_lista] = f"L{len(ids_de_lista) + 1:03d}"
                        for opcao in meta["opcoes"]:
                            listas_linhas.append([ids_de_lista[chave_lista], attr_id, opcao["id"], opcao["name"]])
                        maior_lista = max(maior_lista, len(meta["opcoes"]))
                    id_lista = ids_de_lista[chave_lista]
                    texto_opcoes = f"ver LISTAS: {id_lista} ({len(meta['opcoes'])} opções)"
            elif meta["unidades"]:
                texto_opcoes = "Unidades: " + "; ".join(str(u) for u in meta["unidades"])
            else:
                texto_opcoes = None

            campos_por_attr[attr_id] += 1
            rotulo_por_attr.setdefault(attr_id, meta["label"])

            campos_linhas.append({
                "id": f"{chave}|{attr_id}", "lote": lote_atual, "sku": chave, "produto": produto_para_campos,
                "campo": meta["label"], "attr_id": attr_id,
                "obrigatorio": "Sim" if meta["obrigatorio"] else "Não",
                "tipo": meta["tipo"], "limite": meta["limite"], "opcoes": texto_opcoes,
                "atuais": "\n".join(linhas_atuais), "avisos": "\n".join(avisos),
                "categorias": ", ".join(categorias_do_campo),
                "n_mlbs": len(valores_pedidos), "id_lista": id_lista,
            })

    estat["skus_total"] = len(skus_linhas)
    estat["campos_linhas"] = len(campos_linhas)
    estat["mlbs_linhas"] = len(mlbs_linhas)
    estat["listas_linhas"] = len(listas_linhas)
    estat["listas_distintas"] = len(ids_de_lista)
    estat["maior_lista"] = maior_lista
    estat["skus_multi_categoria"] = multi_categoria
    estat["skus_sem_dados"] = len(skus_sem_dados)
    estat["lotes"] = lote_atual
    estat["mlbs_em_mais_de_um_sku"] = sum(1 for skus in skus_por_mlb.values() if len(skus) > 1)
    estat["conjuntos_de_campos_distintos"] = len(conjuntos_de_campos)

    return {
        "skus": skus_linhas, "campos": campos_linhas, "mlbs": mlbs_linhas, "listas": listas_linhas,
        "estat": estat, "campos_por_attr": campos_por_attr, "rotulo_por_attr": rotulo_por_attr,
        "codigos_de_aviso": codigos_de_aviso, "cobertura_erp": cobertura_erp,
        "conjuntos_de_campos": conjuntos_de_campos, "skus_sem_dados": skus_sem_dados,
    }


def montar_resumo(dados, contexto):
    """Lista de (rótulo, valor) pra imprimir no console e gravar na aba RESUMO. rótulo None + valor = linha de seção."""
    e = dados["estat"]
    c = dados["cobertura_erp"]
    total = max(e["skus_total"], 1)
    com_erp = c["com_erp"]

    def pct(parte, base):
        return f"{parte} ({parte / base * 100:.0f}%)" if base else "0"

    linhas = [
        (None, "ESCOPO"),
        ("Conta", CONTA),
        ("Status incluídos", ", ".join(sorted(STATUS_ACEITOS))),
        ("SKUs elegíveis no banco", contexto["skus_no_banco"]),
        ("SKUs nesta planilha", f"{e['skus_total']}" + (f" (amostra: LIMITE_SKUS={LIMITE_SKUS})" if LIMITE_SKUS else " (inventário inteiro)")),
        ("MLBs lidos na API / falhas", f"{contexto['mlbs_lidos']} / {contexto['mlbs_falhos']}"),
        ("Categorias distintas lidas / falhas", f"{contexto['categorias_lidas']} / {contexto['categorias_falhas']}"),
        ("SKUs sem leitura da API (ficaram de fora)", e["skus_sem_dados"]),
        ("Lotes (de até %d SKUs)" % TAMANHO_LOTE, e["lotes"]),
        (None, "TAMANHO DA PLANILHA"),
        ("Linhas em SKUS", e["skus_total"]),
        ("Linhas em CAMPOS (fila da LLM)", e["campos_linhas"]),
        ("Linhas em MLBS", e["mlbs_linhas"]),
        ("Listas longas em LISTAS (nº / maior)", f"{e['listas_distintas']} / {e['maior_lista']} opções"),
        (None, "COMPORTAMENTO"),
        ("SKUs com mais de 1 categoria ML", pct(e["skus_multi_categoria"], total)),
        ("SKUs cujas categorias não têm nenhum campo no card", e["skus_sem_campos"]),
        ("Conjuntos de campos distintos entre os SKUs", e["conjuntos_de_campos_distintos"]),
        ("MLBs que aparecem em mais de 1 SKU", e["mlbs_em_mais_de_um_sku"]),
        ("MLBs com mais de 1 variação no ML", e["mlbs_com_varias_variacoes"]),
        ("MLBs com alerta de identidade (aba MLBS)", e["mlbs_com_alerta"]),
        (None, "COBERTURA DO ERP (por SKU)"),
        ("Com Produto no ERP", pct(com_erp, total)),
        ("   vínculo oficial (pelo SKU)", c["via_SKU"]),
        ("   vínculo inferido (pelo EAN do SKU)", c["via_EAN"]),
        ("Sem Produto no ERP", pct(c["sem_erp"], total)),
        ("Produto inativo no ERP (dentre os com ERP)", pct(c["inativo_no_erp"], com_erp)),
        ("Marca preenchida (dentre os com ERP)", pct(c["marca"], com_erp)),
        ("Cód. fabricante preenchido", pct(c["cod_fabricante"], com_erp)),
        ("Descrição preenchida", pct(c["descricao"], com_erp)),
        ("NCM preenchido", pct(c["ncm"], com_erp)),
        ("Imagem 1 preenchida", pct(c["imagem"], com_erp)),
        ("Medidas: as 4 preenchidas", pct(c["medidas_4_de_4"], com_erp)),
        ("Medidas: parciais", pct(c["medidas_parciais"], com_erp)),
        ("Medidas: nenhuma", pct(c["medidas_nenhuma"], com_erp)),
        (None, "AVISOS EM CAMPOS (nº de linhas)"),
    ]
    for codigo, quantidade in dados["codigos_de_aviso"].most_common():
        linhas.append((codigo, quantidade))
    linhas.append((None, "CAMPOS MAIS FREQUENTES (nº de linhas)"))
    for attr_id, quantidade in dados["campos_por_attr"].most_common(15):
        linhas.append((f"{attr_id} ({dados['rotulo_por_attr'].get(attr_id, '')})", quantidade))
    linhas.append((None, "TEMPO"))
    linhas.append(("Duração da geração", f"{contexto['duracao_s']:.0f} s"))
    return linhas


# ──────────────────────────────────────────────────────────────────────
# ESCRITA DA PLANILHA (openpyxl)
# ──────────────────────────────────────────────────────────────────────

COR_MARINHO, COR_AZUL, COR_AMBAR, COR_VERDE, COR_CINZA = "1F3A5F", "2E75B6", "B7791F", "4C7C3A", "6B7280"
FUNDO_ENTRADA, FUNDO_CHECAGEM, FUNDO_APOIO, FUNDO_ROTULO = "FFF4D6", "E6F0DF", "F3F4F6", "EAF2FA"

FONTE = Font(name="Arial", size=10)
FONTE_NEGRITO = Font(name="Arial", size=10, bold=True)
FONTE_CABECALHO = Font(name="Arial", size=10, bold=True, color="FFFFFF")
LADO = Side(style="thin", color="D1D5DB")
BORDA = Border(left=LADO, right=LADO, top=LADO, bottom=LADO)
ALINHA_TOPO = Alignment(horizontal="left", vertical="top", wrap_text=True)
ALINHA_CABECALHO = Alignment(horizontal="center", vertical="center", wrap_text=True)
_FILLS = {}


def fundo(cor):
    if cor not in _FILLS:
        _FILLS[cor] = PatternFill("solid", fgColor=cor)
    return _FILLS[cor]


def escrever_celula(ws, linha, coluna, valor, cor_fundo=None, negrito=False, formato=None, formula=False):
    celula = ws.cell(row=linha, column=coluna)
    if isinstance(valor, str) and not formula:
        valor = limpar_texto(valor)
        celula.value = valor
        if valor.startswith("="):
            celula.data_type = "s"  # texto que começa com "=" não pode virar fórmula
    else:
        celula.value = valor
    celula.font = FONTE_NEGRITO if negrito else FONTE
    celula.alignment = ALINHA_TOPO
    celula.border = BORDA
    if cor_fundo:
        celula.fill = fundo(cor_fundo)
    if formato:
        celula.number_format = formato
    return celula


def escrever_cabecalho(ws, colunas):
    for i, (titulo, cor, largura) in enumerate(colunas, start=1):
        celula = ws.cell(row=1, column=i, value=titulo)
        celula.font = FONTE_CABECALHO
        celula.fill = fundo(cor)
        celula.alignment = ALINHA_CABECALHO
        celula.border = BORDA
        ws.column_dimensions[get_column_letter(i)].width = largura
    ws.row_dimensions[1].height = 43.5


def altura_estimada(pares_texto_largura):
    # * [EXPLICAÇÃO] → Excel não calcula altura de linha com texto quebrado
    #                  quando o arquivo é gerado por código; estimativa
    #                  simples por nº de linhas, com teto pra não ter linha gigante.
    linhas = 1
    for texto, largura in pares_texto_largura:
        if not texto:
            continue
        capacidade = max(int(largura), 1)
        total = sum(max(1, -(-len(parte) // capacidade)) for parte in str(texto).split("\n"))
        linhas = max(linhas, total)
    return min(max(15.0, 13.0 * linhas + 3), 150.0)


def formula_checagem(r, ultima_linha_listas):
    n = max(ultima_linha_listas, 2)
    return (
        f'=IF(M{r}="","",IF(AND(ISNUMBER(I{r}),LEN(M{r})>I{r}),"Excede o limite ("&LEN(M{r})&"/"&I{r}&")",'
        f'IF(H{r}="Lista fechada",IF(T{r}<>"",'
        f'IF(SUMPRODUCT((LISTAS!$A$2:$A${n}=T{r})*(LISTAS!$D$2:$D${n}=M{r}))>0,"OK","Fora da lista"),'
        f'IF(ISNUMBER(FIND("; "&M{r}&"; ","; "&J{r}&"; ")),"OK","Fora da lista")),"OK")))'
    )


SKUS_COLUNAS = [
    ("SKU", COR_MARINHO, 22), ("Lote", COR_MARINHO, 6),
    ("Produto (ERP)", COR_AZUL, 36), ("Marca (ERP)", COR_AZUL, 16), ("Cód. Fabricante", COR_AZUL, 14),
    ("Categoria (ERP)", COR_AZUL, 18), ("Categoria ML (caminho)", COR_AZUL, 40), ("NCM", COR_AZUL, 14), ("EAN", COR_AZUL, 15),
    ("Altura (cm) sem embalar", COR_AZUL, 11), ("Largura (cm) sem embalar", COR_AZUL, 11),
    ("Comprimento (cm) sem embalar", COR_AZUL, 13), ("Peso (kg) sem embalar", COR_AZUL, 11),
    ("Descrição (ERP)", COR_AZUL, 44), ("Títulos dos MLBs", COR_AZUL, 58), ("Imagem 1 (URL) — opcional", COR_AZUL, 22),
    ("Produto no ERP?", COR_CINZA, 16), ("Ativo no ERP?", COR_CINZA, 10), ("Qtd. de MLBs", COR_CINZA, 24),
    ("Categorias ML", COR_CINZA, 20), ("Ficha técnica ML", COR_CINZA, 16),
]
CAMPOS_COLUNAS = [
    ("ID (SKU|campo)", COR_MARINHO, 40), ("Lote", COR_MARINHO, 6), ("SKU", COR_MARINHO, 21),
    ("Produto", COR_AZUL, 30), ("Campo", COR_AZUL, 20), ("Campo na API", COR_AZUL, 22), ("Obrigatório", COR_AZUL, 14),
    ("Tipo", COR_AZUL, 15), ("Limite de caracteres", COR_AZUL, 11), ("Opções válidas", COR_AZUL, 32),
    ("Valores atuais nos MLBs", COR_AZUL, 40), ("Avisos", COR_AZUL, 36),
    ("PREENCHER", COR_AMBAR, 30), ("Confiança", COR_AMBAR, 12), ("Observação da LLM", COR_AMBAR, 48),
    ("Checagem automática", COR_VERDE, 24), ("Revisão humana", COR_VERDE, 14),
    ("Categorias que pedem o campo", COR_CINZA, 20), ("Nº de MLBs que pedem", COR_CINZA, 11), ("Lista (apoio)", COR_CINZA, 10),
]
LISTAS_COLUNAS = [("Lista", COR_AZUL, 8), ("Campo na API", COR_AZUL, 24), ("ID da opção", COR_AZUL, 14), ("Nome da opção", COR_AZUL, 30)]
MLBS_COLUNAS = [
    ("MLB", COR_CINZA, 16), ("SKU", COR_CINZA, 22), ("Título do anúncio", COR_CINZA, 58), ("Categoria ML", COR_CINZA, 14),
    ("Status", COR_CINZA, 10), ("Tipo de anúncio", COR_CINZA, 16), ("Ficha técnica ML", COR_CINZA, 15),
    ("Alertas", COR_CINZA, 50), ("Link do anúncio", COR_CINZA, 40),
]


def texto_leia_me(contexto, dados):
    e = dados["estat"]
    c = dados["cobertura_erp"]
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    escopo = (f"{e['skus_total']} SKUs" + (f" (amostra de {LIMITE_SKUS}; o banco tem {contexto['skus_no_banco']})" if LIMITE_SKUS else " (inventário inteiro)")
              + f", {contexto['mlbs_lidos']} MLBs lidos na API ({contexto['mlbs_falhos']} falhas). "
              f"Status incluídos: {', '.join(sorted(STATUS_ACEITOS))}; fora catálogo e fora anúncio 'fóssil'.")
    return [
        ("titulo", f"Planilha de Características Principais — conta {CONTA}", None),
        ("sub", f"Gerada em {agora}. Uma planilha só, com a fila de trabalho da LLM para os anúncios do Mercado Livre da empresa.", None),
        ("vazio", None, None),
        ("secao", "SOBRE ESTA GERAÇÃO", None),
        ("linha", "Escopo", escopo),
        ("linha", "Origem dos dados", "ERP e anúncios: banco do sistema interno. Valores atuais, categorias, limites e listas: API do Mercado Livre (somente leitura). Nada foi escrito no ML."),
        ("linha", "Vínculo com o ERP",
         f"{c['via_SKU']} SKUs com Produto pelo SKU (vínculo oficial), {c['via_EAN']} com Produto inferido pelo EAN contido no SKU "
         f"(confira: coluna 'Produto no ERP?') e {c['sem_erp']} sem Produto no ERP."),
        ("secao", "COMO FUNCIONA", None),
        ("linha", "1. Gerar", "O script monta este arquivo a partir do banco (ERP, anúncios, categorias) e das chamadas à API do ML (valores atuais). Uma linha por SKU na aba SKUS; uma linha por SKU e campo na aba CAMPOS."),
        ("linha", "2. LLM preenche por lote", "Cada lote reúne SKUs da mesma categoria principal. A LLM lê o contexto (SKUS) e preenche PREENCHER, Confiança e Observação na aba CAMPOS, seguindo a aba INSTRUCOES_LLM."),
        ("linha", "3. Checagem automática", "A coluna Checagem automática testa o limite de caracteres e se o valor está na lista (inclusive nas listas longas da aba LISTAS). Linhas fora do padrão ficam vermelhas."),
        ("linha", "4. Revisão humana", "Você filtra por Confiança Baixa, Sem evidência e Checagem diferente de OK, e marca a coluna Revisão humana (Aprovado, Ajustado, Rejeitado)."),
        ("linha", "5. Fase 2 (depois)", "Os valores aprovados são aplicados nos MLBs do SKU (aba MLBS mostra quais). Nada é escrito no ML até esta etapa ser construída e autorizada."),
        ("secao", "ABAS", None),
        ("linha", "INSTRUCOES_LLM", "Contexto e regras que a LLM recebe: objetivo, fontes de evidência, formato, confiança e regras por campo."),
        ("linha", "SKUS", "Contexto do produto, uma linha por SKU: dados do ERP, medidas sem embalar, descrição, caminho da categoria no ML e títulos dos MLBs."),
        ("linha", "CAMPOS", "A fila de trabalho: uma linha por SKU e campo, com limite, opções válidas, valores atuais nos MLBs e avisos automáticos. É onde a LLM escreve."),
        ("linha", "LISTAS", "Opções das listas fechadas longas demais para caber na célula (referenciadas na coluna Opções válidas)."),
        ("linha", "MLBS", "Apoio: qual MLB pertence a qual SKU, com categoria, status, situação da ficha técnica no ML e alertas de identidade."),
        ("linha", "RESUMO", "Números desta geração: tamanho, cobertura do ERP e frequência dos avisos."),
        ("secao", "CORES DO CABEÇALHO", None),
        ("linha", "Azul-marinho", "Chave da linha (não editar)."),
        ("linha", "Azul", "Entrada para a LLM (não editar)."),
        ("linha", "Âmbar (células amarelas)", "A LLM preenche."),
        ("linha", "Verde", "Checagem automática e revisão humana."),
        ("linha", "Cinza", "Apoio para você e para a Fase 2; não precisa ir para a LLM."),
        ("secao", "DECISÕES ABERTAS", None),
        ("linha", "Escopo", "Só MLBs ativos ou ativos e pausados (a coluna Qtd. de MLBs e a aba MLBS permitem filtrar)."),
        ("linha", "Regras por campo", "Linha e demais campos além de Marca e Modelo ainda precisam de regra."),
        ("linha", "SKUs sem ERP", "Regra de preenchimento para SKUs sem Produto no ERP ainda precisa ser definida."),
        ("linha", "Tamanho dos lotes", f"Configurado em {TAMANHO_LOTE} SKUs por lote, agrupados por categoria principal."),
    ]


INSTRUCOES = [
    ("Objetivo", "Para cada linha da aba CAMPOS, preencher o valor correto da característica principal do produto (SKU). O valor vale para todos os MLBs do SKU cuja categoria pede esse campo: todos os MLBs de um SKU são o mesmo produto."),
    ("Como trabalhar em massa", "Processe um Lote por vez (coluna Lote). Para cada SKU do lote, leia a linha da aba SKUS (contexto do produto) e as linhas desse SKU na aba CAMPOS. Preencha somente PREENCHER, Confiança e Observação da LLM. Nunca altere as demais colunas. Não pule linhas do lote."),
    ("Fontes de evidência (prioridade)", "1) ERP, na aba SKUS: Produto, Marca (ERP), Cód. Fabricante, Categoria (ERP), NCM, medidas sem embalar e Descrição (ERP).\n2) Títulos dos MLBs do SKU e Categoria ML (caminho).\n3) Valores atuais nos MLBs (coluna da aba CAMPOS).\nUse apenas o que estiver nessas fontes. Nunca invente."),
    ("Como usar os valores atuais", "Foram preenchidos à mão e muitas vezes estão certos: se concordam com o ERP e os títulos, mantenha. Mas podem ter erro de grafia, estilo inconsistente, campo vazio ou valor fora da lista. Quando divergirem do ERP e dos títulos, prevalece a evidência do produto, e a divergência é explicada na Observação. '(vazio)' = MLB sem valor; '—' = a categoria desse MLB não pede o campo; '[sem nome; id=...]' = o ML guarda um valor sem nome (por exemplo, campo marcado como não se aplica)."),
    ("Avisos", "Alertas calculados pelo sistema (valores diferentes entre MLBs, vazio, valor fora da lista, diferenças entre categorias do SKU). Chamam a atenção; não são ordens."),
    ("Produto no ERP?", "Na aba SKUS: 'Sim (SKU)' = vínculo oficial; 'Sim (EAN inferido)' = o Produto foi achado pelo EAN contido no SKU, sem vínculo oficial no sistema (use, mas desconfie se o título do ERP não bater com os títulos dos MLBs); 'Não' = sem dados do ERP para este SKU."),
    ("Formato: Texto livre", "Respeite o Limite de caracteres (conte espaços e vírgulas). Sem aspas e sem ponto final."),
    ("Formato: Lista fechada", "Escolha exatamente uma das Opções válidas, com a mesma grafia. Se a coluna indicar 'ver LISTAS: Lxxx', use a lista dessa aba. Se nenhuma opção servir, deixe vazio e explique na Observação."),
    ("Formato: Número + unidade", "Escreva o número e uma unidade aceita, por exemplo '20 L'. As medidas do ERP estão em cm e kg; converta se a unidade do campo for outra."),
    ("Sem evidência", "Se as fontes não sustentam um valor, deixe PREENCHER vazio, Confiança = Sem evidência e explique na Observação. Vazio é melhor do que chute."),
    ("Confiança", "Alta: ERP e/ou títulos dizem claramente. Média: inferência razoável. Baixa: ambíguo ou fontes em conflito (a revisão humana olha estas primeiro). Sem evidência: nenhum valor sustentado."),
    ("Observação da LLM", "Uma frase curta: de onde veio o valor e, se houver, o conflito encontrado (exemplo: 'ERP = BRUDDEN; 3 MLBs com Bruden')."),
    ("Regra: BRAND (Marca)", "Marca real/verdadeira do fabricante, nunca palavras-chave. Prefira Marca (ERP) e corrija grafia e caixa conforme o ERP."),
    ("Regra: MODEL (Modelo)", "Palavras-chave separadas por vírgula, otimizadas para busca (SEO), incluindo o código do modelo (Cód. Fabricante ou título) quando existir. Respeite o limite."),
    ("Regra: LINE (Linha)", "A DEFINIR (Matheus): se também segue o estilo de palavras-chave do Modelo."),
    ("Regra: medidas e peso", "Use as medidas do ERP 'sem embalar' (são do produto, não da caixa). Valor 0 ou vazio no ERP significa 'nunca cadastrado': não use."),
    ("Regra: SKU sem ERP", "A DEFINIR (Matheus): o que fazer quando o SKU não tem Produto no ERP."),
    ("Regra: demais campos", "A DEFINIR por campo, conforme os lotes forem sendo revisados."),
]


def escrever_leia_me(wb, contexto, dados):
    ws = wb.active
    ws.title = "LEIA-ME"
    ws.sheet_properties.tabColor = COR_MARINHO
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 112
    linha = 1
    for tipo, a, b in texto_leia_me(contexto, dados):
        if tipo == "titulo":
            ws.cell(row=linha, column=1, value=a).font = Font(name="Arial", size=15, bold=True, color=COR_MARINHO)
            ws.row_dimensions[linha].height = 18.55
        elif tipo == "sub":
            ws.cell(row=linha, column=1, value=a).font = Font(name="Arial", size=10, italic=True, color=COR_CINZA)
        elif tipo == "secao":
            for coluna in (1, 2):
                celula = ws.cell(row=linha, column=coluna)
                celula.fill = fundo(COR_MARINHO)
                celula.font = FONTE_CABECALHO
            ws.cell(row=linha, column=1, value=a)
            ws.row_dimensions[linha].height = 19.5
        elif tipo == "linha":
            escrever_celula(ws, linha, 1, a, cor_fundo=FUNDO_ROTULO, negrito=True)
            escrever_celula(ws, linha, 2, b)
            ws.row_dimensions[linha].height = altura_estimada([(b, 112), (a, 30)])
        linha += 1


def escrever_instrucoes(wb):
    ws = wb.create_sheet("INSTRUCOES_LLM")
    ws.sheet_properties.tabColor = COR_MARINHO
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 120
    for coluna, titulo in ((1, "Tópico"), (2, "Instrução")):
        celula = ws.cell(row=1, column=coluna, value=titulo)
        celula.font = FONTE_CABECALHO
        celula.fill = fundo(COR_MARINHO)
        celula.alignment = ALINHA_CABECALHO
        celula.border = BORDA
    for i, (topico, instrucao) in enumerate(INSTRUCOES, start=2):
        escrever_celula(ws, i, 1, topico, cor_fundo=FUNDO_ROTULO, negrito=True)
        escrever_celula(ws, i, 2, instrucao)
        ws.row_dimensions[i].height = altura_estimada([(instrucao, 120), (topico, 34)])
    ws.freeze_panes = "A2"


def escrever_skus(wb, linhas):
    ws = wb.create_sheet("SKUS")
    ws.sheet_properties.tabColor = COR_AZUL
    escrever_cabecalho(ws, SKUS_COLUNAS)
    larguras = [c[2] for c in SKUS_COLUNAS]
    for i, valores in enumerate(linhas, start=2):
        for j, valor in enumerate(valores, start=1):
            formato = None
            if 10 <= j <= 12:
                formato = "0.0#"
            elif j == 13:
                formato = "0.000"
            escrever_celula(ws, i, j, valor, cor_fundo=FUNDO_APOIO if j >= 17 else None, negrito=(j == 1), formato=formato)
        ws.row_dimensions[i].height = altura_estimada([(valores[2], larguras[2]), (valores[6], larguras[6]), (valores[13], larguras[13]),
                                                       (valores[14], larguras[14]), (valores[18], larguras[18]), (valores[19], larguras[19])])
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(SKUS_COLUNAS))}{max(len(linhas) + 1, 2)}"


def escrever_campos(wb, linhas, ultima_linha_listas):
    ws = wb.create_sheet("CAMPOS")
    ws.sheet_properties.tabColor = COR_AMBAR
    ws.page_setup.orientation = "landscape"
    escrever_cabecalho(ws, CAMPOS_COLUNAS)
    larguras = [c[2] for c in CAMPOS_COLUNAS]
    for i, c in enumerate(linhas, start=2):
        valores = [c["id"], c["lote"], c["sku"], c["produto"], c["campo"], c["attr_id"], c["obrigatorio"], c["tipo"],
                   c["limite"], c["opcoes"], c["atuais"], c["avisos"]]
        for j, valor in enumerate(valores, start=1):
            escrever_celula(ws, i, j, valor, negrito=(j == 5))
        for j in (13, 14, 15):
            escrever_celula(ws, i, j, None, cor_fundo=FUNDO_ENTRADA)
        escrever_celula(ws, i, 16, formula_checagem(i, ultima_linha_listas), cor_fundo=FUNDO_CHECAGEM, formula=True)
        escrever_celula(ws, i, 17, "Pendente", cor_fundo=FUNDO_CHECAGEM)
        escrever_celula(ws, i, 18, c["categorias"], cor_fundo=FUNDO_APOIO)
        escrever_celula(ws, i, 19, c["n_mlbs"], cor_fundo=FUNDO_APOIO)
        escrever_celula(ws, i, 20, c["id_lista"], cor_fundo=FUNDO_APOIO)
        ws.row_dimensions[i].height = altura_estimada([(c["produto"], larguras[3]), (c["opcoes"], larguras[9]),
                                                       (c["atuais"], larguras[10]), (c["avisos"], larguras[11])])
    ultima = max(len(linhas) + 1, 2)
    ws.freeze_panes = "F2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(CAMPOS_COLUNAS))}{ultima}"

    validacao_confianca = DataValidation(type="list", formula1='"Alta,Média,Baixa,Sem evidência"', allow_blank=True, showErrorMessage=False)
    validacao_revisao = DataValidation(type="list", formula1='"Pendente,Aprovado,Ajustado,Rejeitado"', allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(validacao_confianca)
    ws.add_data_validation(validacao_revisao)
    validacao_confianca.add(f"N2:N{ultima}")
    validacao_revisao.add(f"Q2:Q{ultima}")

    ws.conditional_formatting.add(f"P2:P{ultima}", FormulaRule(formula=['OR(LEFT($P2,3)="Exc",LEFT($P2,4)="Fora")'], fill=PatternFill("solid", bgColor="F8D7DA", fgColor="F8D7DA")))
    ws.conditional_formatting.add(f"P2:P{ultima}", FormulaRule(formula=['LEFT($P2,3)="Con"'], fill=PatternFill("solid", bgColor="FFE8B3", fgColor="FFE8B3")))
    ws.conditional_formatting.add(f"P2:P{ultima}", FormulaRule(formula=['$P2="OK"'], fill=PatternFill("solid", bgColor="D7EBD0", fgColor="D7EBD0")))
    ws.conditional_formatting.add(f"N2:N{ultima}", FormulaRule(formula=['$N2="Baixa"'], fill=PatternFill("solid", bgColor="FFE8B3", fgColor="FFE8B3")))
    ws.conditional_formatting.add(f"N2:N{ultima}", FormulaRule(formula=['$N2="Sem evidência"'], fill=PatternFill("solid", bgColor="F8D7DA", fgColor="F8D7DA")))


def escrever_simples(wb, nome, colunas, linhas, cor_aba, apoio=False):
    ws = wb.create_sheet(nome)
    ws.sheet_properties.tabColor = cor_aba
    escrever_cabecalho(ws, colunas)
    larguras = [c[2] for c in colunas]
    for i, valores in enumerate(linhas, start=2):
        for j, valor in enumerate(valores, start=1):
            escrever_celula(ws, i, j, valor, cor_fundo=FUNDO_APOIO if apoio else None)
        ws.row_dimensions[i].height = altura_estimada(list(zip(valores, larguras)))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{max(len(linhas) + 1, 2)}"


def escrever_resumo(wb, linhas_resumo):
    ws = wb.create_sheet("RESUMO")
    ws.sheet_properties.tabColor = COR_CINZA
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 44
    linha = 1
    for rotulo, valor in linhas_resumo:
        if rotulo is None:
            for coluna in (1, 2):
                ws.cell(row=linha, column=coluna).fill = fundo(COR_MARINHO)
            celula = ws.cell(row=linha, column=1, value=valor)
            celula.font = FONTE_CABECALHO
        else:
            escrever_celula(ws, linha, 1, rotulo, cor_fundo=FUNDO_ROTULO, negrito=True)
            escrever_celula(ws, linha, 2, valor if isinstance(valor, (int, float)) else str(valor))
        linha += 1


def escrever_planilha(caminho, dados, contexto, linhas_resumo):
    wb = Workbook()
    escrever_leia_me(wb, contexto, dados)
    escrever_instrucoes(wb)
    escrever_skus(wb, dados["skus"])
    escrever_campos(wb, dados["campos"], len(dados["listas"]) + 1)
    escrever_simples(wb, "LISTAS", LISTAS_COLUNAS, dados["listas"], COR_AZUL)
    escrever_simples(wb, "MLBS", MLBS_COLUNAS, dados["mlbs"], COR_CINZA, apoio=True)
    escrever_resumo(wb, linhas_resumo)
    wb.save(caminho)


# ──────────────────────────────────────────────────────────────────────
# FLUXO PRINCIPAL
# ──────────────────────────────────────────────────────────────────────

def main():
    inicio = time.time()
    iniciar_django()

    console.print(f"\n[bold]1/6 Lendo o banco (conta {CONTA})...[/bold]")
    grupos = carregar_do_banco()
    total_mlbs_banco = sum(len(g["mlbs"]) for g in grupos.values())
    console.print(f"  {len(grupos)} SKUs elegíveis, {total_mlbs_banco} MLBs (ativos/pausados, fora catálogo e fóssil).")
    vincular_erp_pelo_ean(grupos)
    chaves = ordenar_e_limitar(grupos)
    mlbs = sorted({mlb for chave in chaves for mlb in grupos[chave]["mlbs"]})
    console.print(f"  Nesta geração: {len(chaves)} SKUs, {len(mlbs)} MLBs.")

    console.print("\n[bold]2/6 Lendo os anúncios na API (valores atuais)...[/bold]")
    from api_mercado_livre.core.auth.gerenciador_token import obter_token_valido
    obter_token_valido(CONTA)  # renova antes de abrir as threads, pra nenhuma disputar a renovação
    cache_itens = carregar_cache(CAMINHO_CACHE_ITENS)
    falhas_itens = buscar_em_paralelo("MLBs", mlbs, buscar_item, cache_itens, CAMINHO_CACHE_ITENS)
    itens = {mlb: cache_itens[mlb] for mlb in mlbs if mlb in cache_itens}

    console.print("\n[bold]3/6 Lendo as categorias na API (card, tipos, limites, listas)...[/bold]")
    ids_categorias = sorted({i["category_id"] for i in itens.values() if i.get("category_id")})
    cache_categorias = carregar_cache(CAMINHO_CACHE_CATEGORIAS)
    falhas_categorias = buscar_em_paralelo("Categorias", ids_categorias, buscar_categoria, cache_categorias, CAMINHO_CACHE_CATEGORIAS)
    categorias = {c: cache_categorias[c] for c in ids_categorias if c in cache_categorias}

    console.print("\n[bold]4/6 Lendo ficha técnica e nomes de categoria no banco...[/bold]")
    ficha_por_mlb = carregar_ficha_tecnica(set(mlbs))
    caminhos_categoria = carregar_caminhos_de_categoria(ids_categorias)

    console.print("\n[bold]5/6 Montando as linhas...[/bold]")
    dados = montar_tudo(grupos, chaves, itens, categorias, caminhos_categoria, ficha_por_mlb)
    contexto = {
        "skus_no_banco": len(grupos), "mlbs_lidos": len(itens), "mlbs_falhos": len(falhas_itens),
        "categorias_lidas": len(categorias), "categorias_falhas": len(falhas_categorias),
        "duracao_s": time.time() - inicio,
    }
    linhas_resumo = montar_resumo(dados, contexto)

    console.print("\n[bold]6/6 Gravando o Excel...[/bold]")
    nome = f"planilha_llm_{CONTA}_{'amostra' + str(LIMITE_SKUS) if LIMITE_SKUS else 'completa'}_{datetime.now():%Y%m%d_%H%M}.xlsx"
    caminho = PASTA_SCRIPT / nome
    escrever_planilha(caminho, dados, contexto, linhas_resumo)

    console.print(f"\n[green]Pronto: {caminho}[/green]\n")
    for rotulo, valor in linhas_resumo:
        if rotulo is None:
            console.print(f"[bold]{valor}[/bold]")
        else:
            console.print(f"  {rotulo}: {valor}")
    console.print("\n[dim]Cole este resumo na conversa para eu analisar o comportamento.[/dim]")


if __name__ == "__main__":
    main()