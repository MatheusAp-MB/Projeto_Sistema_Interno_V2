# scripts_exploracao_ML/gerar_planilha_llm_inventario.py
#
# Gera a PLANILHA da empresa que a LLM vai preencher em massa (Características
# principais dos anúncios do Mercado Livre) e, depois, CONFERE o que a LLM
# devolveu. Só leitura: só GET na API, nada gravado no banco, nenhuma LLM chamada.
#
# LAYOUT (Variante A): 1 LINHA = 1 PRODUTO (SKU), autocontida.
#   [colunas fixas: identificação + contexto do ERP + títulos] + [1 bloco de 3
#   colunas por campo: Atual | PREENCHER | Conf.]
#   - o nome do campo está na linha 1 do cabeçalho e a regra do campo na linha 2;
#   - bloco sem fundo amarelo = o campo não existe para aquele SKU (ignorar);
#   - listas de opções ficam UMA vez só na aba LISTAS (a coluna "Listas deste
#     SKU" aponta qual lista vale pra cada campo daquele SKU);
#   - a Descrição (ERP) vai SEMPRE na íntegra.
#
# O QUE ESTE SCRIPT CORRIGE (raiz do problema antigo):
#   - "Lista fechada" agora vem do value_type da API (list/boolean) ou de
#     allow_custom_value = false. Campo string/number com opções é TEXTO LIVRE
#     COM SUGESTÕES (o ML aceita valor próprio): não vira mais "fora da lista".
#   - o cache das categorias guarda tags e allow_custom_value;
#   - campos que a LLM não deve preencher (sistema, somente leitura, fixo,
#     inferido) ficam fora; o RESUMO mostra o que saiu e por quê.
#
# DOIS MODOS (variável MODO):
#   "gerar"   -> monta a planilha mestre (+ 1 arquivo por lote, se ligado)
#   "validar" -> confere um arquivo já preenchido pela LLM (sem API, sem banco)
#
# Como roda:
#   1) MODO = "gerar", LIMITE_SKUS = 30  -> teste rápido (~1-2 min)
#   2) MODO = "gerar", LIMITE_SKUS = None -> inventário inteiro
#   3) MODO = "validar" com VALIDAR_ARQUIVO e VALIDAR_MESTRE preenchidos
# As respostas da API ficam em cache (cache_planilha_llm_*.json, já ignorados
# pelo .gitignore). Cache de categoria antigo (sem tags) é baixado de novo
# sozinho; o cache dos anúncios continua valendo.
#
# Pré-requisito do modo "gerar": banco atualizado (sincronização de sempre).

import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
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
STATUS_ACEITOS = {"active", "paused"}  # status que entram na planilha
TAMANHO_LOTE = 50  # SKUs por lote (coluna Lote), agrupados por categoria
THREADS = 40  # chamadas simultâneas à API (o pool do projeto aguenta 50)
USAR_CACHE = True  # False = baixa tudo de novo da API
VINCULAR_PELO_EAN = True  # SKU sem Produto, mas no formato F+EAN13.NNN: tenta achar o Produto pelo EAN ("inferido")
GERAR_ARQUIVOS_POR_LOTE = True  # além da mestre, 1 arquivo enxuto por lote (só as colunas usadas naquele lote)
PASTA_SAIDA = None  # None = pasta "Resultados_LLM" ao lado deste script. Ou o caminho completo de outra pasta, ex.: r"C:\Users\WIN10\...\Resultados_LLM"

# Campos que a LLM NÃO deve preencher (Etapa 2). O RESUMO lista o que saiu e o motivo.
TAGS_QUE_EXCLUEM = ("read_only", "fixed", "inferred")  # tags da API: somente leitura / valor fixo da categoria / valor inferido
CAMPOS_DE_SISTEMA = {"APGID"}  # ids de campo técnico que não são característica do produto
TIPOS_DE_SISTEMA = {"grid_row_id"}  # value_type de guia de tamanhos (SIZE_GRID_ROW_ID)
SEM_SUGESTOES = {"BRAND"}  # campos de texto cujas sugestões da API só atrapalham (a marca vem do ERP)

# Só no MODO = "validar":
VALIDAR_PASTA = ""  # pasta com os arquivos *_preenchido.xlsx (todos de uma vez). Se preenchida, VALIDAR_ARQUIVO é ignorado. Caminho completo ou nome dentro da pasta de resultados.
MODO = "gerar" #Validar ou gerar
VALIDAR_ARQUIVO = r"C:\Users\WIN10\Desktop\Codigos\GITHUB\notas-obsidian-sistema-interno-mb-sv\PLANILHA_LLM\Preenchidos\lote_002_preenchido.xlsx"
VALIDAR_MESTRE = r"C:\Users\WIN10\Desktop\Codigos\GITHUB\notas-obsidian-sistema-interno-mb-sv\PLANILHA_LLM\Resultados_LLM\planilha_llm_MB_amostra30_20261002_1042.xlsx"# ========================================

PASTA_SCRIPT = Path(__file__).resolve().parent
# * [EXPLICAÇÃO] → TUDO o que este script gera fica numa pasta só: planilha mestre, arquivos de lote, arquivos
#                  conferidos (_checado), caches da API e logs. Nada é gravado ao lado do script.
PASTA_RESULTADOS = Path(PASTA_SAIDA) if PASTA_SAIDA else PASTA_SCRIPT / "Resultados_LLM"
PASTA_LOGS = PASTA_RESULTADOS / "logs"
NOME_LOG = "gerar_planilha_llm_inventario"
CAMINHO_CACHE_ITENS = PASTA_RESULTADOS / f"cache_planilha_llm_itens_{CONTA}.json"
CAMINHO_CACHE_CATEGORIAS = PASTA_RESULTADOS / "cache_planilha_llm_categorias.json"
VERSAO_CACHE_CATEGORIAS = 2  # 2 = guarda tags e allow_custom_value. Entrada de versão menor é baixada de novo.

console = Console()

REGEX_SKU_COM_EAN = re.compile(r"^F(\d{13})\.\d{3}$")
CARACTERES_ILEGAIS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
LIMITE_CELULA_EXCEL = 32000  # o Excel aceita 32.767 caracteres por célula
CONFIANCAS = ("Alta", "Média", "Baixa", "Sem evidência")
SUBCOLUNAS = ("Atual", "PREENCHER", "Conf.")
CONFIANCAS_PARA_REVISAR = ("Baixa", "Sem evidência")  # entram na planilha de revisão humana, além dos campos com problema na conferência
# * [EXPLICAÇÃO] → Marca (ERP) que NÃO é de fabricante (nome da própria empresa, origem ou termo genérico), em minúsculas e com
#                  as duas grafias de "genérico". A regra do INSTRUCOES_LLM manda ignorá-las; aqui o validador deixa de acusar
#                  "marca diferente da Marca (ERP)" nesses casos.
MARCAS_ERP_QUE_NAO_SAO_FABRICANTE = {"magazine brasileiro", "importados china", "generico", "genérico"}
SEPARADOR_OPCOES = " | "  # separa as opções dentro da célula da aba LISTAS (nenhum nome de opção do ML tem este texto)


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

def pasta_saida():
    return PASTA_RESULTADOS


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


def numero_br(valor, casas):
    if valor is None:
        return "?"
    return f"{valor:.{casas}f}".rstrip("0").rstrip(".").replace(".", ",")


def texto_medidas(altura, largura, comprimento, peso):
    if all(m is None for m in (altura, largura, comprimento, peso)):
        return None
    dimensoes = " × ".join(numero_br(m, 1) for m in (altura, largura, comprimento))
    return f"{dimensoes} cm (A×L×C) · {numero_br(peso, 3)} kg"


def tags_ativas(attr):
    """Tags da API (dict {tag: true} ou lista) -> lista ordenada só com as ativas."""
    tags = attr.get("tags")
    if isinstance(tags, dict):
        return sorted(str(k) for k, v in tags.items() if v)
    if isinstance(tags, list):
        return sorted(str(t) for t in tags)
    return []


def tem_tag(attr, nome_tag):
    return nome_tag in tags_ativas(attr)


def extrair_sku(item_ou_variacao):
    # Mesma lógica de api_mercado_livre/detalhes_ml.py: SELLER_SKU nos
    # atributos; se não houver, seller_custom_field.
    for attr in item_ou_variacao.get("attributes") or []:
        if attr.get("id") == "SELLER_SKU":
            return attr.get("value_name")
    return item_ou_variacao.get("seller_custom_field")


def formatar_valor_atual(attr):
    """value_name; senão o nome do 1º item de values; senão, se só existir id: "N/A" (id -1) ou o marcador "[sem nome; id=...]"."""
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
            return "N/A" if str(value_id) == "-1" else f"[sem nome; id={value_id}]"
    return valor


def normalizar_valor_atual(valor):
    # * [EXPLICAÇÃO] → O cache de anúncios antigo guardou o N/A como "[sem nome; id=-1]".
    return "N/A" if valor == "[sem nome; id=-1]" else valor


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
    """
    Card 'Características principais' (grupo MAIN menos allow_variations) + definições
    (tipo, limite, opções, unidades, tags) só dos atributos do card.
    allow_custom_value vem do componente de tela (ui_config) do card.
    """
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
            ui_config = componente.get("ui_config") or {}
            for attr in componente.get("attributes", []):
                attr_id = attr.get("id")
                if not attr_id or tem_tag(attr, "allow_variations"):
                    continue
                card[attr_id] = {
                    "label": attr.get("label") or attr.get("name") or attr_id,
                    "required": tem_tag(attr, "required"),
                    "tags": tags_ativas(attr),
                    "allow_custom_value": ui_config.get("allow_custom_value"),  # True / False / None (não informado)
                    "componente": componente.get("component"),
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
            "tags": tags_ativas(attr),
        }

    return {"versao": VERSAO_CACHE_CATEGORIAS, "card": card, "defs": definicoes}


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
    Agrupa as variações elegíveis por SKU (produto.sku -> sku_ml -> MLB) e por MLB.
    Filtros: fora anúncio "fóssil", fora catálogo, só STATUS_ACEITOS
    (MLB sem tipo_de_anuncio entra, igual ao fluxo anterior).
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
# METADADOS DOS CAMPOS (tipo real, exclusões, fusão entre categorias do SKU)
# ──────────────────────────────────────────────────────────────────────

NIVEL_OBRIGATORIEDADE = {"Não": 0, "Condicional": 1, "Sim": 2}


def tags_do_campo(meta_card, definicao):
    return set(meta_card.get("tags") or []) | set(definicao.get("tags") or [])


def motivo_exclusao(attr_id, meta_card, definicao):
    """Devolve o motivo pelo qual a LLM não deve preencher o campo nesta categoria, ou None."""
    if attr_id in CAMPOS_DE_SISTEMA:
        return "campo de sistema"
    if definicao.get("value_type") in TIPOS_DE_SISTEMA:
        return f"tipo {definicao['value_type']}"
    tags = tags_do_campo(meta_card, definicao)
    for tag in TAGS_QUE_EXCLUEM:
        if tag in tags:
            return f"tag {tag}"
    return None


def nivel_obrigatoriedade(meta_card, definicao):
    tags = tags_do_campo(meta_card, definicao)
    if meta_card.get("required") or "required" in tags or "new_required" in tags:
        return "Sim"
    if "conditional_required" in tags:
        return "Condicional"
    return "Não"


def tipo_na_categoria(meta_card, definicao):
    """
    Tipo real do campo numa categoria, pela API (e não por "tem opções"):
      lista            = value_type list/boolean, ou string com opções e allow_custom_value = false
      texto_sugestoes  = string com opções e valor próprio aceito (doc: "só deverá enviar o name")
      numero_unidade / numero / texto
    """
    value_type = definicao.get("value_type")
    tem_opcoes = bool(definicao.get("values"))
    if value_type in ("list", "boolean"):
        return "lista"
    if value_type == "number_unit":
        return "numero_unidade"
    if value_type == "number":
        return "numero"
    if tem_opcoes and meta_card.get("allow_custom_value") is False:
        return "lista"
    if tem_opcoes:
        return "texto_sugestoes"
    return "texto"


def fundir_metadados(attr_id, categorias, cards, definicoes):
    """
    A ficha é do SKU: o mesmo campo pode vir de mais de 1 categoria, e o valor
    escolhido precisa servir em TODAS as que pedem o campo.
      - obrigatório   = o maior nível entre as categorias (Sim > Condicional > Não);
      - lista fechada = interseção (por id) entre as categorias que têm lista;
      - sugestões     = união das opções (por id);
      - limite        = menor tamanho máximo (tipos que não são lista).
    Divergência relevante entre categorias vira linha em "avisos".
    """
    metas = {c: cards[c][attr_id] for c in categorias}
    defs = {c: definicoes[c].get(attr_id, {}) for c in categorias}
    tipos_categoria = {c: tipo_na_categoria(metas[c], defs[c]) for c in categorias}
    avisos = []

    niveis = {c: nivel_obrigatoriedade(metas[c], defs[c]) for c in categorias}
    nivel = max(niveis.values(), key=NIVEL_OBRIGATORIEDADE.get)
    if len(set(niveis.values())) > 1:
        avisos.append("obrigatoriedade difere entre as categorias: "
                      + ", ".join(f"{c}={n}" for c, n in niveis.items()) + ".")

    resultado = {
        "label": metas[categorias[0]]["label"],
        "obrigatorio": nivel,
        "multi": any("multivalued" in tags_do_campo(metas[c], defs[c]) for c in categorias),
        "limite": None, "opcoes": None, "unidades": None,
        "categorias": list(categorias),
    }

    com_lista = [c for c in categorias if tipos_categoria[c] == "lista"]
    com_sugestoes = [c for c in categorias if tipos_categoria[c] == "texto_sugestoes"]

    if com_lista:
        resultado["tipo"] = "Lista fechada"
        if len(com_lista) < len(categorias):
            sem_lista = [c for c in categorias if c not in com_lista]
            avisos.append(f"lista fechada em {', '.join(com_lista)} e sem lista em {', '.join(sem_lista)}; "
                          f"a lista vale como restrição nas categorias que a têm.")
        conjuntos = [frozenset(o.get("id") for o in defs[c].get("values") or []) for c in com_lista]
        ids_comuns = set.intersection(*[set(conjunto) for conjunto in conjuntos])
        resultado["opcoes"] = [
            {"id": o.get("id"), "name": o.get("name")}
            for o in defs[com_lista[0]].get("values") or [] if o.get("id") in ids_comuns
        ]
        if len(set(conjuntos)) > 1:
            avisos.append(f"as opções diferem entre as categorias; lista = interseção ({len(resultado['opcoes'])} em comum).")
        if not resultado["opcoes"]:
            avisos.append("ATENÇÃO: nenhuma opção em comum entre as categorias — nenhum valor da lista serve para todas.")
        return _fechar_resultado(resultado, avisos)

    if any(t == "numero_unidade" for t in tipos_categoria.values()):
        resultado["tipo"] = "Número + unidade"
    elif any(t == "numero" for t in tipos_categoria.values()):
        resultado["tipo"] = "Número"
    elif com_sugestoes:
        resultado["tipo"] = "Texto com sugestões" if attr_id not in SEM_SUGESTOES else "Texto livre"
        if attr_id not in SEM_SUGESTOES:
            vistos = {}
            for c in com_sugestoes:
                for o in defs[c].get("values") or []:
                    vistos.setdefault(o.get("id"), {"id": o.get("id"), "name": o.get("name")})
            resultado["opcoes"] = list(vistos.values())
    else:
        resultado["tipo"] = "Texto livre"
    if len(set(tipos_categoria.values())) > 1:
        avisos.append("o tipo do campo difere entre as categorias (" + ", ".join(sorted(set(tipos_categoria.values()))) + ").")

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
    return _fechar_resultado(resultado, avisos)


def _fechar_resultado(resultado, avisos):
    resultado["avisos"] = avisos
    return resultado

# ──────────────────────────────────────────────────────────────────────
# MONTAGEM DAS LINHAS (puro: não toca em banco, API nem arquivo)
# ──────────────────────────────────────────────────────────────────────

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


def status_aceito(status_ml):
    """Status do MLB na API. Sem status (None) não derruba o MLB; só sai quem o ML diz que está fora (closed, inactive...)."""
    return not status_ml or status_ml in STATUS_ACEITOS


def linha_mlb_fora_da_planilha(m, chave, dados, fora_por_status, ficha_por_mlb):
    """Linha da aba MLBS de um MLB que não entrou na planilha: status no ML fora de STATUS_ACEITOS, ou falha de leitura."""
    if fora_por_status:
        categoria = dados["category_id"]
        alerta = f"FORA DA PLANILHA: no ML o status é '{dados['status_ml']}' (banco: '{m['status']}')."
    else:
        categoria = "(sem leitura da API)"
        alerta = "não foi possível ler este MLB (ou a categoria dele) na API."
    return [m["mlb"], chave, m["titulo"], categoria, m["status_txt"], m["tipo_txt"],
            ficha_por_mlb.get(m["mlb"], "Sem dado"), alerta, m["permalink"]]


def texto_qtd_mlbs(mlbs):
    ativos = sum(1 for m in mlbs if m["status"] == "active")
    pausados = sum(1 for m in mlbs if m["status"] == "paused")
    outros = len(mlbs) - ativos - pausados
    texto = f"{len(mlbs)} (ativos: {ativos} / pausados: {pausados}"
    if outros:
        texto += f" / outros: {outros}"
    return texto + ")"


def texto_atual(valores):
    """Valores atuais dos MLBs do SKU que pedem o campo: 'valor' se todos iguais; senão 'valor (n) | outro (m) | vazio (k)'."""
    contagem = Counter("vazio" if v is None else v for v in valores)
    if not contagem:
        return None
    if len(contagem) == 1:
        return next(iter(contagem))
    return " | ".join(f"{valor} ({n})" for valor, n in contagem.most_common())


def montar_cabecalhos(linhas):
    """Para cada campo usado nas linhas: rótulos, tipos, limite, unidades... (vira linha 2 do cabeçalho)."""
    cab = {}
    for linha in linhas:
        for attr_id, campo in linha["campos"].items():
            meta = campo["meta"]
            info = cab.setdefault(attr_id, {
                "rotulos": [], "tipos": set(), "niveis": set(), "limite": None,
                "unidades": [], "multi": False,
            })
            if meta["label"] not in info["rotulos"]:
                info["rotulos"].append(meta["label"])
            info["tipos"].add(meta["tipo"])
            info["niveis"].add(meta["obrigatorio"])
            if meta["limite"]:
                info["limite"] = meta["limite"] if info["limite"] is None else min(info["limite"], meta["limite"])
            for unidade in meta["unidades"] or []:
                if unidade not in info["unidades"]:
                    info["unidades"].append(unidade)  # união entre os SKUs; a de cada SKU está em 'Campos deste SKU'
            info["multi"] = info["multi"] or meta["multi"]
    return cab


def texto_regra_cabecalho(info):
    tipos = sorted(info["tipos"])
    if len(tipos) == 1:
        descricao_tipo = {
            "Lista fechada": "LISTA FECHADA: só uma opção da lista (ver 'Listas deste SKU')",
            "Texto com sugestões": "texto livre; aceita valor próprio, sugestões em 'Listas deste SKU'",
            "Texto livre": "texto livre",
            "Número": "número",
            "Número + unidade": "número + unidade",
        }[tipos[0]]
    elif set(tipos) <= {"Texto livre", "Texto com sugestões"}:
        descricao_tipo = "texto livre; aceita valor próprio (se 'Listas deste SKU' trouxer sugestões, são só sugestões)"
    else:
        descricao_tipo = (" / ".join(tipos) + " (depende do SKU: o tipo do SKU está em 'Campos deste SKU'; "
                          "se 'Listas deste SKU' trouxer lista para este campo, siga-a)")
    niveis = info["niveis"]
    if niveis == {"Sim"}:
        obrigatoriedade = "obrigatório"
    elif niveis == {"Não"}:
        obrigatoriedade = "opcional"
    elif niveis == {"Condicional"}:
        obrigatoriedade = "condicional"
    else:
        obrigatoriedade = "obrigatoriedade varia por categoria (ver 'Campos deste SKU')"
    rotulo = info["rotulos"][0] if len(info["rotulos"]) == 1 else "rótulo varia por categoria"
    partes = [rotulo, descricao_tipo, obrigatoriedade]
    if info["limite"]:
        partes.append(f"≤{info['limite']} caracteres")
    if info["unidades"]:
        unidades = info["unidades"]
        partes.append("unidades: " + "; ".join(unidades[:8]) + ("…" if len(unidades) > 8 else ""))
    if info["multi"]:
        partes.append("aceita vários valores separados por vírgula")
    return " · ".join(partes)


# * [EXPLICAÇÃO] → O objeto da aba REGRAS é o CAMPO da API (1 linha por campo). O que o ML decide por categoria
#                  (obrigatoriedade, lista, unidades, limite, tipo) não é do campo: é do campo NA categoria, então vai
#                  para a linha do SKU, na coluna 'Campos deste SKU'. Escrita e leitura ficam lado a lado de propósito.
GRUPOS_CAMPOS_DO_SKU = (("Sim", "Obrigatórios"), ("Condicional", "Condicionais"), ("Não", "Opcionais"))
TIPOS_DE_CAMPO = ("Lista fechada", "Texto com sugestões", "Texto livre", "Número + unidade", "Número")
REGEX_CAMPO_DO_SKU = re.compile(r"([A-Za-z0-9_]+)(?: \((.*?)\))?(?:, |$)")


def montar_regras_por_campo(linhas, ordem, cards, definicoes):
    """
    Linhas da aba REGRAS (1 por campo da API) e a 'base' de cada campo (tipos, unidades e limite do campo).
    O que for diferente da base num SKU aparece entre parênteses em 'Campos deste SKU'.
    """
    usos = defaultdict(list)
    for linha in linhas:
        for attr_id, campo in linha["campos"].items():
            usos[attr_id].append(campo)

    base = {"tipos": {}, "unidades": {}, "limite": {}}
    regras = []
    for attr_id in ordem:
        campos = usos[attr_id]
        metas = [c["meta"] for c in campos]
        categorias = sorted({cat for m in metas for cat in m["categorias"]})
        por_categoria = {cat: fundir_metadados(attr_id, [cat], cards, definicoes) for cat in categorias}

        tipos = sorted({m["tipo"] for m in metas})
        unidades = []
        for m in metas:
            for unidade in m["unidades"] or []:
                if unidade not in unidades:
                    unidades.append(unidade)
        limites = sorted({m["limite"] for m in metas if m["limite"]})
        base["tipos"][attr_id] = set(tipos)
        base["unidades"][attr_id] = set(unidades)
        base["limite"][attr_id] = limites[0] if limites else None

        rotulos = sorted({m["label"] for m in por_categoria.values()})
        niveis = Counter(m["obrigatorio"] for m in por_categoria.values())
        listas = Counter(c["id_lista"] for c in campos if c["id_lista"])
        avisos = Counter(texto for c in campos for texto in c["avisos"])

        if len(niveis) == 1:
            nivel = next(iter(niveis))
            obrigatorio = f"{nivel} em todas ({len(categorias)})" if len(categorias) > 1 else f"{nivel} (1 categoria)"
        else:
            obrigatorio = " · ".join(f"{nivel} em {niveis[nivel]}" for nivel, _ in GRUPOS_CAMPOS_DO_SKU if nivel in niveis)

        observacoes = []
        if len(rotulos) > 1:
            observacoes.append("Rótulo varia por categoria: " + "; ".join(rotulos) + ".")
        if len(tipos) > 1:
            observacoes.append("O tipo muda conforme o SKU; cada SKU diz o seu em 'Campos deste SKU'.")
        if len(niveis) > 1:
            observacoes.append("Obrigatoriedade varia por categoria; o nível de cada SKU está em 'Campos deste SKU'.")
        if len(listas) > 1:
            observacoes.append("A lista muda conforme a categoria (" + ", ".join(f"{l}: {n} SKU(s)" for l, n in sorted(listas.items())) + ").")
        if len({frozenset(m["unidades"] or []) for m in por_categoria.values()} - {frozenset()}) > 1:
            observacoes.append("As unidades aceitas diferem por categoria; a de cada SKU está em 'Campos deste SKU'.")
        if len(limites) > 1:
            observacoes.append("O limite de caracteres difere entre categorias; aqui vai o menor e o de cada SKU está em 'Campos deste SKU'.")
        for texto, quantidade in avisos.most_common():
            observacoes.append(f"Aviso ({quantidade} SKU(s)): {texto}")

        regras.append([
            attr_id, rotulos[0] if len(rotulos) == 1 else "(varia por categoria)", " / ".join(tipos),
            base["limite"][attr_id], "; ".join(unidades) or None, "Sim" if any(m["multi"] for m in metas) else "Não",
            obrigatorio, ", ".join(f"{lista} ({n})" for lista, n in sorted(listas.items())) or None,
            len(campos), len(categorias), "\n".join(observacoes) or None,
        ])
    return regras, base


def texto_campos_do_sku(campos, base):
    """
    Coluna 'Campos deste SKU': os campos que existem para o SKU, por nível de obrigatoriedade. Entre parênteses, só o que
    difere da base do campo: tipo (se o campo tem mais de um tipo), unidades, e limite (≤N).
    """
    por_nivel = {nivel: [] for nivel, _ in GRUPOS_CAMPOS_DO_SKU}
    for attr_id, campo in campos.items():
        meta = campo["meta"]
        extras = []
        if len(base["tipos"][attr_id]) > 1:
            extras.append(meta["tipo"])
        if meta["unidades"] and set(meta["unidades"]) != base["unidades"][attr_id]:
            extras.extend(str(u) for u in meta["unidades"])
        if meta["limite"] and meta["limite"] != base["limite"][attr_id]:
            extras.append(f"≤{meta['limite']}")
        por_nivel[meta["obrigatorio"]].append(attr_id + (f" ({'; '.join(extras)})" if extras else ""))
    texto = "\n".join(f"{rotulo}: {', '.join(por_nivel[nivel])}" for nivel, rotulo in GRUPOS_CAMPOS_DO_SKU if por_nivel[nivel])
    return texto or None


def ler_campos_do_sku(texto):
    """Inverso de texto_campos_do_sku: {attr_id: {"obrigatorio", "tipo", "unidades", "limite"}} (None = vale a base do campo)."""
    nivel_do_rotulo = {rotulo: nivel for nivel, rotulo in GRUPOS_CAMPOS_DO_SKU}
    campos = {}
    for linha in str(texto or "").split("\n"):
        rotulo, _, resto = linha.partition(": ")
        if rotulo not in nivel_do_rotulo:
            continue
        for attr_id, extras in REGEX_CAMPO_DO_SKU.findall(resto):
            itens = [x for x in extras.split("; ") if x] if extras else []
            tipo = next((x for x in itens if x in TIPOS_DE_CAMPO), None)
            limite = next((int(x[1:]) for x in itens if x.startswith("≤") and x[1:].isdigit()), None)
            unidades = [x for x in itens if x != tipo and not (x.startswith("≤") and x[1:].isdigit())]
            campos[attr_id] = {"obrigatorio": nivel_do_rotulo[rotulo], "tipo": tipo,
                               "unidades": unidades or None, "limite": limite}
    return campos


def montar_tudo(grupos, chaves, itens, categorias, caminhos_categoria, ficha_por_mlb):
    cards = {c: dados["card"] for c, dados in categorias.items()}
    definicoes = {c: dados["defs"] for c, dados in categorias.items()}

    linhas, mlbs_linhas, listas_linhas = [], [], []
    registro_listas = {}
    estat = Counter()
    tipos_de_campo = Counter()
    campos_por_attr = Counter()
    rotulo_por_attr = {}
    conjuntos_de_campos = Counter()
    codigos_de_aviso = Counter()
    excluidos = Counter()  # (attr_id, motivo) -> nº de SKUs
    tags_observadas = Counter()
    skus_por_mlb = defaultdict(set)
    skus_sem_dados = []
    skus_sem_mlb_valido = []
    cobertura_erp = Counter()
    multi_categoria = 0
    maior_lista = 0
    lote_atual = 0
    contador_no_lote = 0

    for categoria_id, card in cards.items():
        for attr_id, meta_card in card.items():
            for tag in tags_do_campo(meta_card, definicoes.get(categoria_id, {}).get(attr_id, {})):
                tags_observadas[tag] += 1

    for chave in chaves:
        grupo = grupos[chave]
        todos_mlbs = [grupo["mlbs"][m] for m in sorted(grupo["mlbs"])]
        # * [EXPLICAÇÃO] → Vale o status da API (o do banco pode estar desatualizado): MLB fechado ou inativo no ML
        #                  não entra na planilha (nem nos valores atuais, nem nos títulos). Fica só na aba MLBS, com o motivo.
        ids_fora_status = {m["mlb"] for m in todos_mlbs
                           if m["mlb"] in itens and not status_aceito(itens[m["mlb"]].get("status_ml"))}
        estat["mlbs_fora_status"] += len(ids_fora_status)
        mlbs_ok = [m for m in todos_mlbs
                   if m["mlb"] in itens and m["mlb"] not in ids_fora_status
                   and itens[m["mlb"]].get("category_id") in cards]
        mlbs_ok_ids = {m["mlb"] for m in mlbs_ok}

        for m in todos_mlbs:
            skus_por_mlb[m["mlb"]].add(chave)

        if not mlbs_ok:
            if len(ids_fora_status) == len(todos_mlbs):
                skus_sem_mlb_valido.append(chave)  # todos os MLBs do SKU estão fechados/inativos no ML
            else:
                skus_sem_dados.append(chave)
            for m in todos_mlbs:
                mlbs_linhas.append(linha_mlb_fora_da_planilha(m, chave, itens.get(m["mlb"]), m["mlb"] in ids_fora_status, ficha_por_mlb))
            continue

        if contador_no_lote == 0 or contador_no_lote >= TAMANHO_LOTE:
            lote_atual += 1
            contador_no_lote = 0
        contador_no_lote += 1

        produto = grupo["produto"]
        categorias_do_sku = [c for c, _ in Counter(itens[m["mlb"]]["category_id"] for m in mlbs_ok).most_common()]
        if len(categorias_do_sku) > 1:
            multi_categoria += 1

        # ---- contexto do produto (ERP)
        if produto is None:
            vinculo_txt = "Sem ERP"
        else:
            vinculo_txt = "SKU" if grupo["vinculo"] == "SKU" else "EAN (inferido)"

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
            preenchidas = sum(1 for x in medidas if x is not None)
            cobertura_erp["medidas_4_de_4" if preenchidas == 4 else ("medidas_parciais" if preenchidas else "medidas_nenhuma")] += 1
        else:
            cobertura_erp["sem_erp"] += 1

        # ---- aba MLBS (apoio)
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
                mlbs_linhas.append(linha_mlb_fora_da_planilha(m, chave, itens.get(m["mlb"]), m["mlb"] in ids_fora_status, ficha_por_mlb))

        # ---- campos do SKU: união dos campos pedidos pelas categorias dos MLBs
        attrs_do_sku = []
        for categoria in categorias_do_sku:
            for attr_id in cards[categoria]:
                if attr_id not in attrs_do_sku:
                    attrs_do_sku.append(attr_id)

        campos_do_sku = {}
        for attr_id in attrs_do_sku:
            categorias_do_campo = [c for c in categorias_do_sku if attr_id in cards[c]]
            motivos = {c: motivo_exclusao(attr_id, cards[c][attr_id], definicoes[c].get(attr_id, {}))
                       for c in categorias_do_campo}
            categorias_ativas = [c for c in categorias_do_campo if motivos[c] is None]
            if not categorias_ativas:
                excluidos[(attr_id, motivos[categorias_do_campo[0]])] += 1
                rotulo_por_attr.setdefault(attr_id, cards[categorias_do_campo[0]][attr_id]["label"])
                continue

            meta = fundir_metadados(attr_id, categorias_ativas, cards, definicoes)
            avisos = list(meta["avisos"])
            codigos = []
            travadas = [c for c in categorias_do_campo if motivos[c]]
            if travadas:
                avisos.append("campo travado (" + ", ".join(f"{c}: {motivos[c]}" for c in travadas)
                              + ") — não muda nessas categorias.")
                codigos.append("campo travado em parte das categorias")

            valores_pedidos = [
                normalizar_valor_atual(itens[m["mlb"]]["valores"].get(attr_id))
                for m in mlbs_ok if itens[m["mlb"]]["category_id"] in categorias_ativas
            ]
            distintos = {v for v in valores_pedidos if v is not None}
            vazios = sum(1 for v in valores_pedidos if v is None)

            if meta["avisos"]:
                codigos.append("diferença entre categorias")
            if len(distintos) > 1:
                codigos.append("valores diferentes entre MLBs")
            if vazios and distintos:
                codigos.append("vazio em parte dos MLBs")
            if vazios and not distintos:
                codigos.append("vazio em todos os MLBs")
            if meta["opcoes"]:
                nomes_validos = {str(o["name"]).strip().lower() for o in meta["opcoes"]}
                fora = sorted(v for v in distintos
                              if v != "N/A" and not eh_marcador_sem_nome(v) and v.strip().lower() not in nomes_validos)
                if fora and meta["tipo"] == "Lista fechada":
                    codigos.append("valor atual fora da lista")
                elif fora:
                    codigos.append("valor atual fora das sugestões (aceito)")
            if "N/A" in distintos:
                codigos.append("valor N/A")
            if any(eh_marcador_sem_nome(v) for v in distintos):
                codigos.append("valor sem nome (outro id)")
            for codigo in codigos:
                codigos_de_aviso[codigo] += 1

            id_lista = None
            if meta["opcoes"]:
                tipo_lista = "Fechada" if meta["tipo"] == "Lista fechada" else "Sugestão"
                chave_lista = (attr_id, tipo_lista, tuple(o["id"] for o in meta["opcoes"]))
                if chave_lista not in registro_listas:
                    registro_listas[chave_lista] = f"L{len(registro_listas) + 1:03d}"
                    # * [EXPLICAÇÃO] → 1 linha = 1 lista (o objeto). As opções são um atributo dela: nomes numa
                    #                  célula e IDs na célula ao lado, na MESMA ordem, separados por " | ".
                    listas_linhas.append([
                        registro_listas[chave_lista], attr_id, tipo_lista,
                        SEPARADOR_OPCOES.join(str(o["name"]) for o in meta["opcoes"]),
                        SEPARADOR_OPCOES.join(str(o["id"]) for o in meta["opcoes"]),
                    ])
                    maior_lista = max(maior_lista, len(meta["opcoes"]))
                id_lista = registro_listas[chave_lista]

            # * [EXPLICAÇÃO] → 'avisos' aqui são só os da categoria (diferença entre categorias, campo travado): vão para
            #                  'Observações do campo' na aba REGRAS. O que é do SKU (vazio, valores diferentes) já está em Atual.
            campos_do_sku[attr_id] = {"atual": texto_atual(valores_pedidos), "meta": meta, "id_lista": id_lista, "avisos": avisos}
            tipos_de_campo[meta["tipo"]] += 1
            campos_por_attr[attr_id] += 1
            rotulo_por_attr.setdefault(attr_id, meta["label"])

        conjuntos_de_campos[frozenset(campos_do_sku)] += 1
        if not campos_do_sku:
            estat["skus_sem_campos"] += 1

        titulos_mlbs = "\n".join(f"{m['mlb']} · {m['titulo']}" for m in mlbs_ok)
        listas_txt = " | ".join(
            f"{attr_id}→{c['id_lista']} ({'fechada' if c['meta']['tipo'] == 'Lista fechada' else 'sugestões'})"
            for attr_id, c in campos_do_sku.items() if c["id_lista"]
        ) or None

        linhas.append({
            "lote": lote_atual, "sku": chave, "vinculo": vinculo_txt,
            "produto": texto_ou_none(produto.titulo) if produto is not None else None,
            "marca": texto_ou_none(produto.marca) if produto is not None else None,
            "cod": texto_ou_none(produto.cod_fabricante) if produto is not None else None,
            "medidas": texto_medidas(*medidas),
            "categoria_ml": "\n".join(f"{c} · {caminhos_categoria.get(c, '(nome não encontrado)')}" for c in categorias_do_sku),
            "descricao": texto_ou_none(produto.descricao) if produto is not None else None,
            "titulos": titulos_mlbs, "listas_txt": listas_txt,
            "campos": campos_do_sku, "qtd_mlbs": texto_qtd_mlbs(mlbs_ok),
        })

    ordem = sorted(campos_por_attr, key=lambda a: (-campos_por_attr[a], a))
    regras_linhas, base_dos_campos = montar_regras_por_campo(linhas, ordem, cards, definicoes)
    for linha in linhas:
        linha["campos_txt"] = texto_campos_do_sku(linha["campos"], base_dos_campos)
    por_sku = [len(l["campos"]) for l in linhas] or [0]

    estat["skus_total"] = len(linhas)
    estat["campos_linhas"] = sum(por_sku)
    estat["campos_distintos"] = len(ordem)
    estat["regras_linhas"] = len(regras_linhas)
    estat["max_campos_por_sku"] = max(por_sku)
    estat["mediana_campos_por_sku"] = statistics.median(por_sku)
    estat["colunas_total"] = len(COLUNAS_FIXAS) + len(SUBCOLUNAS) * len(ordem)
    estat["mlbs_linhas"] = len(mlbs_linhas)
    estat["listas_distintas"] = len(registro_listas)
    estat["listas_linhas"] = len(listas_linhas)
    estat["maior_lista"] = maior_lista
    estat["skus_multi_categoria"] = multi_categoria
    estat["skus_sem_dados"] = len(skus_sem_dados)
    estat["skus_sem_mlb_valido"] = len(skus_sem_mlb_valido)
    estat["lotes"] = lote_atual
    estat["mlbs_em_mais_de_um_sku"] = sum(1 for skus in skus_por_mlb.values() if len(skus) > 1)
    estat["conjuntos_de_campos_distintos"] = len(conjuntos_de_campos)

    return {
        "linhas": linhas, "ordem": ordem, "cab": montar_cabecalhos(linhas),
        "regras": regras_linhas, "mlbs": mlbs_linhas, "listas": listas_linhas,
        "estat": estat, "tipos_de_campo": tipos_de_campo, "campos_por_attr": campos_por_attr,
        "rotulo_por_attr": rotulo_por_attr, "codigos_de_aviso": codigos_de_aviso,
        "cobertura_erp": cobertura_erp, "excluidos": excluidos, "tags_observadas": tags_observadas,
        "skus_sem_dados": skus_sem_dados, "skus_sem_mlb_valido": skus_sem_mlb_valido,
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
        ("MLBs fora da planilha por status no ML (ex.: closed)", e["mlbs_fora_status"]),
        ("SKUs que saíram por ficarem sem MLB ativo/pausado no ML", e["skus_sem_mlb_valido"]),
        ("Lotes (de até %d SKUs)" % TAMANHO_LOTE, e["lotes"]),
        (None, "TAMANHO DA PLANILHA (layout: 1 linha por SKU)"),
        ("Linhas em SKUS", e["skus_total"]),
        ("Campos distintos (colunas de campo)", e["campos_distintos"]),
        ("Colunas totais (fixas + 3 por campo)", e["colunas_total"]),
        ("Campos por SKU (mediana / máximo)", f"{e['mediana_campos_por_sku']:g} / {e['max_campos_por_sku']}"),
        ("Pares SKU×campo (campos a preencher nos SKUs)", e["campos_linhas"]),
        ("Linhas em REGRAS (1 por campo da API)", e["regras_linhas"]),
        ("Listas em LISTAS (nº / maior)", f"{e['listas_distintas']} / {e['maior_lista']} opções"),
        ("Linhas em MLBS", e["mlbs_linhas"]),
        (None, "TIPO DO CAMPO (pares SKU×campo)"),
    ]
    for tipo, quantidade in dados["tipos_de_campo"].most_common():
        linhas.append((tipo, quantidade))
    linhas.append((None, "CAMPOS FORA DA PLANILHA (nº de SKUs afetados)"))
    if dados["excluidos"]:
        for (attr_id, motivo), quantidade in dados["excluidos"].most_common():
            linhas.append((f"{attr_id} — {motivo}", quantidade))
    else:
        linhas.append(("(nenhum)", 0))
    linhas.append((None, "TAGS NOS CAMPOS DO CARD (categoria×campo)"))
    if dados["tags_observadas"]:
        for tag, quantidade in dados["tags_observadas"].most_common():
            linhas.append((tag, quantidade))
    else:
        linhas.append(("(nenhuma — cache sem tags?)", 0))
    linhas += [
        (None, "COMPORTAMENTO"),
        ("SKUs com mais de 1 categoria ML", pct(e["skus_multi_categoria"], total)),
        ("SKUs sem nenhum campo a preencher", e["skus_sem_campos"]),
        ("Conjuntos de campos distintos entre os SKUs", e["conjuntos_de_campos_distintos"]),
        ("MLBs que aparecem em mais de 1 SKU", e["mlbs_em_mais_de_um_sku"]),
        ("MLBs com mais de 1 variação no ML", e["mlbs_com_varias_variacoes"]),
        ("MLBs com alerta (status ativo/pausado diferente do banco, SKU ou variações; aba MLBS)", e["mlbs_com_alerta"]),
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
        ("Medidas: as 4 preenchidas", pct(c["medidas_4_de_4"], com_erp)),
        ("Medidas: parciais", pct(c["medidas_parciais"], com_erp)),
        ("Medidas: nenhuma", pct(c["medidas_nenhuma"], com_erp)),
        (None, "AVISOS (nº de pares SKU×campo)"),
    ]
    for codigo, quantidade in dados["codigos_de_aviso"].most_common():
        linhas.append((codigo, quantidade))
    linhas.append((None, "CAMPOS MAIS FREQUENTES (nº de SKUs)"))
    for attr_id, quantidade in dados["campos_por_attr"].most_common(15):
        linhas.append((f"{attr_id} ({dados['rotulo_por_attr'].get(attr_id, '')})", quantidade))
    linhas.append((None, "TEMPO"))
    linhas.append(("Duração da geração", f"{contexto['duracao_s']:.0f} s"))
    return linhas

# ──────────────────────────────────────────────────────────────────────
# ESCRITA DA PLANILHA (openpyxl)
# ──────────────────────────────────────────────────────────────────────

COR_MARINHO, COR_AZUL, COR_AZUL_ESCURO = "1F3A5F", "2E75B6", "255D8F"
COR_AMBAR, COR_VERDE, COR_CINZA = "B7791F", "4C7C3A", "6B7280"
FUNDO_ENTRADA, FUNDO_CHECAGEM, FUNDO_APOIO, FUNDO_ROTULO = "FFF4D6", "E6F0DF", "F3F4F6", "EAF2FA"

FONTE = Font(name="Arial", size=10)
FONTE_NEGRITO = Font(name="Arial", size=10, bold=True)
FONTE_CABECALHO = Font(name="Arial", size=10, bold=True, color="FFFFFF")
FONTE_REGRA = Font(name="Arial", size=9, color="FFFFFF")
LADO = Side(style="thin", color="D1D5DB")
BORDA = Border(left=LADO, right=LADO, top=LADO, bottom=LADO)
ALINHA_TOPO = Alignment(horizontal="left", vertical="top", wrap_text=True)
ALINHA_CABECALHO = Alignment(horizontal="center", vertical="center", wrap_text=True)
ALINHA_REGRA = Alignment(horizontal="left", vertical="top", wrap_text=True)
_FILLS = {}

# (chave, título da linha 3, grupo da linha 1, cor, largura)
COLUNAS_FIXAS = [
    ("lote", "Lote", "IDENTIFICAÇÃO", COR_MARINHO, 6),
    ("sku", "SKU", "IDENTIFICAÇÃO", COR_MARINHO, 22),
    ("vinculo", "Vínculo ERP", "CONTEXTO (só leitura)", COR_AZUL, 12),
    ("produto", "Produto (ERP)", "CONTEXTO (só leitura)", COR_AZUL, 34),
    ("marca", "Marca (ERP)", "CONTEXTO (só leitura)", COR_AZUL, 16),
    ("cod", "Cód. fabricante (ERP)", "CONTEXTO (só leitura)", COR_AZUL, 14),
    ("medidas", "Medidas sem embalar", "CONTEXTO (só leitura)", COR_AZUL, 22),
    ("categoria_ml", "Categoria ML (caminho)", "CONTEXTO (só leitura)", COR_AZUL, 36),
    ("descricao", "Descrição (ERP) — íntegra", "CONTEXTO (só leitura)", COR_AZUL, 75),
    ("titulos", "Títulos dos MLBs", "CONTEXTO (só leitura)", COR_AZUL, 48),
    ("listas_txt", "Listas deste SKU", "CONTEXTO (só leitura)", COR_AZUL, 30),
    ("campos_txt", "Campos deste SKU", "CONTEXTO (só leitura)", COR_AZUL, 44),
    ("obs", "Observações (LLM)", "LLM PREENCHE", COR_AMBAR, 40),
    ("checagem", "Checagem automática", "CONFERÊNCIA", COR_VERDE, 30),
    ("revisao", "Revisão humana", "CONFERÊNCIA", COR_VERDE, 13),
]
INDICE_FIXA = {chave: i for i, (chave, *_resto) in enumerate(COLUNAS_FIXAS, start=1)}
LARGURAS_SUBCOLUNAS = (24, 24, 9)

# 1 linha = 1 lista. A coluna "Opções" é o que a LLM lê; a de IDs é apoio (Fase 2), só na planilha mestre.
LISTAS_COLUNAS = [("Lista", COR_AZUL, 8), ("Campo na API", COR_AZUL, 26), ("Tipo da lista", COR_AZUL, 12),
                  ("Opções (separadas por ' | ')", COR_AZUL, 100),
                  ("IDs das opções (apoio, mesma ordem)", COR_CINZA, 60)]
COLUNAS_LISTAS_NO_LOTE = 4  # os arquivos de lote levam só as 4 primeiras (sem os IDs)
# 1 linha = 1 campo da API. O que depende da categoria é resumo aqui; o detalhe de cada SKU está em 'Campos deste SKU'.
REGRAS_COLUNAS = [
    ("Campo na API", COR_CINZA, 26), ("Campo", COR_CINZA, 24), ("Tipo", COR_CINZA, 18), ("Limite de caracteres", COR_CINZA, 11),
    ("Unidades", COR_CINZA, 22), ("Vários valores?", COR_CINZA, 10), ("Obrigatório (nº de categorias)", COR_CINZA, 24),
    ("Listas (nº de SKUs)", COR_CINZA, 18), ("SKUs", COR_CINZA, 7), ("Categorias", COR_CINZA, 10),
    ("Observações do campo", COR_CINZA, 70),
]
MLBS_COLUNAS = [
    ("MLB", COR_CINZA, 16), ("SKU", COR_CINZA, 22), ("Título do anúncio", COR_CINZA, 58), ("Categoria ML", COR_CINZA, 14),
    ("Status", COR_CINZA, 10), ("Tipo de anúncio", COR_CINZA, 16), ("Ficha técnica ML", COR_CINZA, 15),
    ("Alertas", COR_CINZA, 50), ("Link do anúncio", COR_CINZA, 40),
]


def fundo(cor):
    if cor not in _FILLS:
        _FILLS[cor] = PatternFill("solid", fgColor=cor)
    return _FILLS[cor]


def escrever_celula(ws, linha, coluna, valor, cor_fundo=None, negrito=False, formato=None):
    celula = ws.cell(row=linha, column=coluna)
    if isinstance(valor, str):
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


def escrever_cabecalho_celula(ws, linha, coluna, valor, cor, fonte=FONTE_CABECALHO, alinhamento=ALINHA_CABECALHO):
    celula = ws.cell(row=linha, column=coluna, value=limpar_texto(valor) if isinstance(valor, str) else valor)
    celula.font = fonte
    celula.fill = fundo(cor)
    celula.alignment = alinhamento
    celula.border = BORDA
    return celula


def escrever_cabecalho(ws, colunas):
    for i, (titulo, cor, largura) in enumerate(colunas, start=1):
        escrever_cabecalho_celula(ws, 1, i, titulo, cor)
        ws.column_dimensions[get_column_letter(i)].width = largura
    ws.row_dimensions[1].height = 43.5


def altura_estimada(pares_texto_largura, teto=300.0):
    # * [EXPLICAÇÃO] → Excel não calcula altura de linha com texto quebrado
    #                  quando o arquivo é gerado por código; estimativa
    #                  simples por nº de linhas. O teto é o máximo do Excel (409).
    linhas = 1
    for texto, largura in pares_texto_largura:
        if not texto:
            continue
        capacidade = max(int(largura), 1)
        total = sum(max(1, -(-len(parte) // capacidade)) for parte in str(texto).split("\n"))
        linhas = max(linhas, total)
    return min(max(15.0, 13.0 * linhas + 3), teto)


def nova_aba(wb, nome):
    if len(wb.worksheets) == 1 and wb.active.title == "Sheet" and wb.active.max_row == 1 and wb.active["A1"].value is None:
        ws = wb.active
        ws.title = nome
        return ws
    return wb.create_sheet(nome)


def texto_leia_me(contexto, dados):
    e = dados["estat"]
    c = dados["cobertura_erp"]
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    escopo = (f"{e['skus_total']} SKUs" + (f" (amostra de {LIMITE_SKUS}; o banco tem {contexto['skus_no_banco']})" if LIMITE_SKUS else " (inventário inteiro)")
              + f", {contexto['mlbs_lidos']} MLBs lidos na API ({contexto['mlbs_falhos']} falhas). "
              f"Status incluídos: {', '.join(sorted(STATUS_ACEITOS))}, conferido na API (MLB fechado ou inativo no ML fica de fora, "
              f"{e['mlbs_fora_status']} nesta geração); fora catálogo e fora anúncio 'fóssil'.")
    return [
        ("titulo", f"Planilha de Características Principais — conta {CONTA}", None),
        ("sub", f"Gerada em {agora}. 1 linha = 1 produto (SKU). A LLM lê a linha inteira, pensa uma vez e preenche os campos dela.", None),
        ("vazio", None, None),
        ("secao", "SOBRE ESTA GERAÇÃO", None),
        ("linha", "Escopo", escopo),
        ("linha", "Tamanho", f"{e['campos_distintos']} campos distintos; mediana de {e['mediana_campos_por_sku']:g} e máximo de "
                             f"{e['max_campos_por_sku']} campos por SKU; {e['colunas_total']} colunas na planilha mestre."),
        ("linha", "Origem dos dados", "ERP e anúncios: banco do sistema interno. Valores atuais, categorias, tipos, limites, listas e tags: API do Mercado Livre (somente leitura). Nada foi escrito no ML."),
        ("linha", "Vínculo com o ERP",
         f"{c['via_SKU']} SKUs com Produto pelo SKU (vínculo oficial), {c['via_EAN']} com Produto inferido pelo EAN contido no SKU "
         f"e {c['sem_erp']} sem Produto no ERP (coluna 'Vínculo ERP')."),
        ("secao", "COMO FUNCIONA", None),
        ("linha", "1. Gerar", "O script monta a planilha mestre (aba SKUS) e, se ligado, 1 arquivo por lote com só as colunas que o lote usa."),
        ("linha", "2. LLM preenche por lote", "A LLM trabalha num lote por vez (de preferência no arquivo do lote), lê as regras da aba INSTRUCOES_LLM e escreve só em PREENCHER, Conf. e Observações (LLM)."),
        ("linha", "3. Conferência automática", "O próprio script, no MODO = 'validar', confere o arquivo devolvido (limite, lista, número, unidade, confiança, obrigatório) e escreve o resultado em Checagem automática e na aba CHECAGEM."),
        ("linha", "4. Revisão humana", "Você filtra por Checagem diferente de OK e por Conf. Baixa ou Sem evidência, e marca Revisão humana."),
        ("linha", "5. Fase 2 (depois)", "Os valores aprovados serão aplicados nos MLBs do SKU (aba MLBS mostra quais). Nada é escrito no ML até esta etapa ser construída e autorizada."),
        ("secao", "ABAS", None),
        ("linha", "INSTRUCOES_LLM", "Regras que a LLM recebe, escritas uma única vez."),
        ("linha", "SKUS", "A planilha: 1 linha por SKU. Colunas fixas (identificação, contexto, listas e campos do SKU, observações) + 3 colunas por campo."),
        ("linha", "LISTAS", "1 linha por lista de opções, escrita UMA vez; as opções ficam na mesma célula, separadas por ' | '. 'Fechada' = só estas opções; 'Sugestão' = o ML aceita valor próprio. A coluna de IDs (só na mestre) é apoio da Fase 2."),
        ("linha", "REGRAS", "Apoio (não vai para a LLM): 1 linha por campo da API, com tipo, limite, unidades, vários valores e o resumo do que muda por categoria (obrigatoriedade, listas). O que vale para cada SKU está na coluna 'Campos deste SKU' da aba SKUS; as duas juntas são a base da conferência automática."),
        ("linha", "MLBS", "Apoio: qual MLB pertence a qual SKU, com categoria, status, ficha técnica e alertas. Os MLBs que ficaram fora da planilha (fechados ou inativos no ML) também estão aqui, com o motivo."),
        ("linha", "RESUMO", "Números desta geração: tamanho, tipos de campo, campos que ficaram de fora, tags e cobertura do ERP."),
        ("secao", "CORES DO CABEÇALHO", None),
        ("linha", "Azul-marinho", "Chave da linha (não editar)."),
        ("linha", "Azul", "Contexto e regras do campo (não editar). Linha 1 = campo; linha 2 = regra do campo."),
        ("linha", "Âmbar / células amarelas", "A LLM preenche: PREENCHER, Conf. e Observações (LLM). Bloco sem amarelo = o campo não existe para o SKU."),
        ("linha", "Verde", "Conferência automática e revisão humana."),
        ("linha", "Cinza", "Apoio."),
        ("secao", "DECISÕES ABERTAS", None),
        ("linha", "Escopo", "Só MLBs ativos ou pausados no ML (status conferido na API). SKU sem nenhum MLB assim não entra na planilha."),
        ("linha", "Regras por campo", "Marca, Modelo, Linha, Formato de venda, Cor principal e medidas já têm regra. Os demais campos seguem só as regras de tipo e de evidência até serem revisados."),
        ("linha", "Preço por unidade", "UNITS_PER_PACK, NET_WEIGHT e NET_VOLUME (tags unit_yield, pack_multiplier e conditional_required) dependem da documentação oficial do ML sobre preço por unidade. Até lá, UNITS_PER_PACK não recebe valor novo (ver INSTRUCOES_LLM); NET_WEIGHT e NET_VOLUME seguem as regras gerais de tipo e de evidência."),
        ("linha", "N/A", "Antes da Fase 2, testar no ML como o N/A se comporta (só pode ser trocado por um valor; campo obrigatório não aceita N/A)."),
        ("linha", "Tamanho dos lotes", f"Configurado em {TAMANHO_LOTE} SKUs por lote, agrupados por categoria principal."),
    ]


INSTRUCOES = [
    ("Objetivo", "Preencher, para cada produto (linha), as características principais que o Mercado Livre pede nos anúncios dele. 1 linha = 1 SKU = 1 produto: todos os MLBs do SKU são o mesmo produto e recebem os mesmos valores. Pense uma vez por produto, na linha inteira."),
    ("Como ler a linha", "À esquerda ficam as colunas fixas: SKU, dados do ERP, medidas, categoria, descrição, títulos dos MLBs, Listas deste SKU e Campos deste SKU. 'Campos deste SKU' diz quais campos existem para este produto (só estes) e quais são Obrigatórios, Condicionais ou Opcionais; um tipo, uma unidade ou um limite (≤N) entre parênteses vale só para este SKU e substitui o que o cabeçalho do campo diz. Depois vem um bloco de 3 colunas por campo: Atual | PREENCHER | Conf. O nome do campo está na linha 1 do cabeçalho e a regra dele na linha 2. Só preencha blocos com PREENCHER amarelo: bloco sem amarelo ou vazio = o campo não existe para este SKU, ignore."),
    ("Como trabalhar em massa", "Processe um Lote por vez (coluna Lote), sem pular linhas. Escreva SOMENTE em PREENCHER, Conf. e Observações (LLM). Nunca altere as outras células, nem a ordem das linhas e colunas."),
    ("Fontes de evidência (prioridade)", "1) ERP: Produto, Marca, Cód. fabricante, Medidas sem embalar e Descrição (ERP) (a descrição dá o contexto de todo o resto).\n2) Títulos dos MLBs e Categoria ML.\n3) Valores em Atual (o que está hoje nos MLBs).\nUse apenas o que estiver nessas fontes. Nunca invente."),
    ("Vínculo ERP", "'SKU' = vínculo oficial. 'EAN (inferido)' = o Produto foi achado pelo EAN contido no SKU: use, mas desconfie se o Produto (ERP) não bater com os títulos. 'Sem ERP' = não há dados do ERP: use títulos, categoria e Atual, com Conf. no máximo Média."),
    ("Como usar o Atual", "Foi preenchido à mão e muitas vezes está certo: se concorda com o ERP e os títulos, mantenha. Mas pode ter erro de grafia, estilo inconsistente, estar vazio ou fora da lista. Quando divergir do ERP e dos títulos, prevalece a evidência do produto e a divergência é explicada em Observações. Formato: 'valor' = todos os MLBs iguais; 'valor (2) | outro (1)' = valores diferentes entre MLBs (o número é a quantidade de MLBs); 'vazio' = sem valor; 'N/A' = o ML guarda 'não se aplica'."),
    ("PREENCHER", "PREENCHER é sempre o valor FINAL do campo: se o Atual já está correto, copie-o. Vazio significa que não há evidência para um valor."),
    ("Tipo: Lista fechada", "A linha 2 do campo diz 'LISTA FECHADA' e a coluna 'Listas deste SKU' aponta a lista (ex.: GENDER→L012 (fechada)). Na aba LISTAS, a linha dessa lista traz as opções na coluna 'Opções', separadas por ' | '. Escolha exatamente UMA opção, com a mesma grafia. Se nenhuma serve, deixe vazio e explique em Observações."),
    ("Tipo: Texto com sugestões", "Texto livre. A lista (ex.: POWER_SUPPLY_TYPE→L021 (sugestões)) é só sugestão: prefira uma opção dela quando descrever o produto, mas o Mercado Livre aceita valor próprio. Respeite o limite de caracteres."),
    ("Tipo: Texto livre", "Respeite o limite de caracteres da linha 2 (conte espaços e vírgulas). Sem aspas e sem ponto final."),
    ("Tipo: Número / Número + unidade", "Número: só o número. Número + unidade: número, espaço e uma unidade aceita da linha 2, por exemplo '20 L'. As medidas do ERP estão em cm e kg; converta se a unidade do campo for outra."),
    ("Vários valores", "Se a linha 2 diz 'aceita vários valores separados por vírgula', use vírgula entre os valores. Caso contrário, um valor só."),
    ("N/A", "Use N/A só se o produto realmente não tem esse atributo e o campo não é obrigatório. Se há evidência de um valor, escreva o valor."),
    ("Sem evidência", "Se as fontes não sustentam um valor, deixe PREENCHER vazio e Conf. = Sem evidência. Vazio é melhor do que chute."),
    ("Conf. (confiança)", "Mede a evidência do VALOR, não se o ML o aceita (isso a conferência automática verifica). Alta: ERP e/ou títulos dizem claramente. Média: inferência razoável. Baixa: ambíguo ou fontes em conflito (a revisão humana olha estas primeiro). Sem evidência: nenhum valor sustentado."),
    ("Observações (LLM)", "1 célula por linha, só quando Conf. não for Alta ou houver conflito. Formato: 'CAMPO: motivo curto', separando campos com ' | '. Exemplo: 'MODEL: código só no título | GENDER: ERP e títulos divergem'."),
    ("Regra: BRAND (Marca)", "Marca real/verdadeira do fabricante, nunca palavras-chave. A Marca (ERP) é a fonte da verdade de QUAL é a marca (a comparação ignora maiúsculas e minúsculas e espaços nas pontas). A caixa segue esta ordem: 1) se o Atual já traz a mesma marca, mantenha a grafia do Atual; 2) se os MLBs do SKU divergem só na caixa (ex.: 'QUIMIVIDA (1) | Quimivida (1)'), padronize na forma mais usada e, em empate, na que não está toda em maiúsculas; 3) se não há Atual, escreva a Marca (ERP) com a primeira letra de cada palavra maiúscula (ex.: ORTHO PAUHER vira Ortho Pauher), preservando siglas e grafias estilizadas conhecidas (JBL, DeWalt). Sem ERP: a marca vem do Atual e dos títulos, mantendo a caixa do Atual; Conf. Média se o Atual é igual em todos os MLBs e nenhum título o contradiz; Conf. Baixa se os MLBs divergem na marca ou um título a contradiz; nunca Alta. Exceção: Marca (ERP) que não é de fabricante (o nome da própria empresa, como 'Magazine Brasileiro', ou uma origem ou termo genérico, como 'Importados China' e 'Genérico') não conta como marca. Descarte-a, registre em Observações (LLM) e trate o SKU como Sem ERP (a marca vem do Atual e dos títulos). Nesse caso: se o Atual é 'Genérica' (ou 'Genérico'), mantenha com Conf. Baixa; se não há marca real nem no Atual nem nos títulos, deixe vazio com Conf. Sem evidência."),
    ("Regra: MODEL (Modelo)", "Palavras-chave separadas por vírgula, otimizadas para busca (SEO), no máximo 10 termos e dentro do limite de caracteres. Inclua o código do modelo (Cód. fabricante ou título) quando existir. Não inclua a marca (ela já tem campo próprio) nem códigos de peças avulsas ou de componentes, a não ser que o produto seja a própria peça. Sem código de modelo nas fontes, use termos do título e da descrição."),
    ("Regra: LINE (Linha)", "Preencha só se o ERP, os títulos ou o Atual mostrarem o nome de uma linha de produtos da marca. Nome de categoria ou palavras genéricas não são linha: ignore um Atual assim. Sem nome de linha, deixe vazio e Conf. = Sem evidência. Não use o estilo de palavras-chave do Modelo."),
    ("Regra: SALE_FORMAT (Formato de venda)", "'Unidade' quando o título ou o ERP descrevem um item só; 'Kit' quando dizem kit, conjunto ou combo; se não der para decidir, vazio e Conf. = Sem evidência."),
    ("Regra: UNITS_PER_PACK (quantidade por pacote)", "Não crie valor novo: a regra deste campo depende da documentação oficial do ML sobre preço por unidade, ainda em análise. Se o Atual já tem valor, copie-o com Conf. Baixa; se está vazio, deixe vazio e Conf. = Sem evidência, mesmo quando o campo é Condicional."),
    ("Regra: MAIN_COLOR (Cor principal)", "Escolha entre as cores que existem na lista do SKU; cor que não está na lista não é mapeada por aproximação (ex.: lilás não vira Violeta). Produto de duas cores: use a predominante; se não der para saber qual predomina, use a primeira citada, com Conf. Baixa e a explicação em Observações."),
    ("Regra: medidas e peso", "Use as 'Medidas sem embalar' do ERP (são do produto, não da caixa). '?' ou vazio significa 'nunca cadastrado': não use. Sem ERP, use só o Atual (se estiver vazio, deixe vazio), com Conf. no máximo Média. Formato: ponto decimal (o ERP usa vírgula: 2,6 kg vira 2.6 kg; a API devolve 52.5 cm) e uma unidade aceita pelo campo; se o Atual já está em unidade aceita (ex.: 1.41 m), não converta."),
    ("Regra: dado suspeito do ERP", "Se um dado do ERP parecer implausível para o produto (medida absurda, Cód. fabricante que não parece um código de modelo) ou contradisser a descrição, não use esse dado e registre em Observações."),
    ("Regra: demais campos", "Aplique as regras de tipo e de evidência acima. Na dúvida, vazio e Conf. = Sem evidência."),
]


def escrever_leia_me(wb, contexto, dados):
    ws = nova_aba(wb, "LEIA-ME")
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
    ws = nova_aba(wb, "INSTRUCOES_LLM")
    ws.sheet_properties.tabColor = COR_MARINHO
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 120
    for coluna, titulo in ((1, "Tópico"), (2, "Instrução")):
        escrever_cabecalho_celula(ws, 1, coluna, titulo, COR_MARINHO)
    for i, (topico, instrucao) in enumerate(INSTRUCOES, start=2):
        escrever_celula(ws, i, 1, topico, cor_fundo=FUNDO_ROTULO, negrito=True)
        escrever_celula(ws, i, 2, instrucao)
        ws.row_dimensions[i].height = altura_estimada([(instrucao, 120), (topico, 34)])
    ws.freeze_panes = "A2"


def escrever_aba_skus(wb, linhas, ordem, cab):
    """Variante A: 1 linha por SKU; 3 colunas (Atual | PREENCHER | Conf.) por campo. Dados a partir da linha 4."""
    ws = nova_aba(wb, "SKUS")
    ws.sheet_properties.tabColor = COR_AMBAR
    n_fixas = len(COLUNAS_FIXAS)

    for i, (_chave, titulo, grupo, cor, largura) in enumerate(COLUNAS_FIXAS, start=1):
        escrever_cabecalho_celula(ws, 1, i, grupo, cor)
        escrever_cabecalho_celula(ws, 2, i, None, cor)
        escrever_cabecalho_celula(ws, 3, i, titulo, cor)
        ws.column_dimensions[get_column_letter(i)].width = largura

    coluna_do_campo = {}
    colunas_conf = []
    for k, attr_id in enumerate(ordem):
        primeira = n_fixas + 1 + k * len(SUBCOLUNAS)
        coluna_do_campo[attr_id] = primeira
        cor_bloco = COR_AZUL if k % 2 == 0 else COR_AZUL_ESCURO
        regra = texto_regra_cabecalho(cab[attr_id])
        for j, subcoluna in enumerate(SUBCOLUNAS):
            coluna = primeira + j
            escrever_cabecalho_celula(ws, 1, coluna, attr_id, cor_bloco)
            escrever_cabecalho_celula(ws, 2, coluna, regra if j == 0 else None, cor_bloco, FONTE_REGRA, ALINHA_REGRA)
            escrever_cabecalho_celula(ws, 3, coluna, subcoluna, COR_CINZA if j == 0 else COR_AMBAR)
            ws.column_dimensions[get_column_letter(coluna)].width = LARGURAS_SUBCOLUNAS[j]
        colunas_conf.append(primeira + 2)
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 118
    ws.row_dimensions[3].height = 20

    for r, linha in enumerate(linhas, start=4):
        for chave, _titulo, _grupo, _cor, largura in COLUNAS_FIXAS:
            coluna = INDICE_FIXA[chave]
            if chave == "obs":
                escrever_celula(ws, r, coluna, None, cor_fundo=FUNDO_ENTRADA)
            elif chave == "checagem":
                escrever_celula(ws, r, coluna, None, cor_fundo=FUNDO_CHECAGEM)
            elif chave == "revisao":
                escrever_celula(ws, r, coluna, "Pendente", cor_fundo=FUNDO_CHECAGEM)
            else:
                escrever_celula(ws, r, coluna, linha.get(chave), negrito=(chave == "sku"))
        for attr_id, campo in linha["campos"].items():
            primeira = coluna_do_campo[attr_id]
            escrever_celula(ws, r, primeira, campo["atual"], cor_fundo=FUNDO_APOIO)
            escrever_celula(ws, r, primeira + 1, None, cor_fundo=FUNDO_ENTRADA)
            escrever_celula(ws, r, primeira + 2, None, cor_fundo=FUNDO_ENTRADA)
        ws.row_dimensions[r].height = altura_estimada([
            (linha["descricao"], COLUNAS_FIXAS[INDICE_FIXA["descricao"] - 1][4]),
            (linha["titulos"], COLUNAS_FIXAS[INDICE_FIXA["titulos"] - 1][4]),
            (linha["produto"], COLUNAS_FIXAS[INDICE_FIXA["produto"] - 1][4]),
            (linha["categoria_ml"], COLUNAS_FIXAS[INDICE_FIXA["categoria_ml"] - 1][4]),
            (linha["listas_txt"], COLUNAS_FIXAS[INDICE_FIXA["listas_txt"] - 1][4]),
            (linha["campos_txt"], COLUNAS_FIXAS[INDICE_FIXA["campos_txt"] - 1][4]),
        ])

    ultima = max(len(linhas) + 3, 4)
    ws.freeze_panes = "C4"
    ws.auto_filter.ref = f"A3:{get_column_letter(n_fixas + len(SUBCOLUNAS) * len(ordem))}{ultima}"

    # * [EXPLICAÇÃO] → Validações em pedaços de 40 faixas: uma lista de faixas gigante numa
    #                  validação só pode incomodar o Excel.
    faixas_conf = [f"{get_column_letter(c)}4:{get_column_letter(c)}{ultima}" for c in colunas_conf]
    for inicio in range(0, len(faixas_conf), 40):
        validacao = DataValidation(type="list", formula1='"' + ",".join(CONFIANCAS) + '"', allow_blank=True, showErrorMessage=False)
        ws.add_data_validation(validacao)
        for faixa in faixas_conf[inicio:inicio + 40]:
            validacao.add(faixa)
    coluna_revisao = get_column_letter(INDICE_FIXA["revisao"])
    validacao_revisao = DataValidation(type="list", formula1='"Pendente,Aprovado,Ajustado,Rejeitado"', allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(validacao_revisao)
    validacao_revisao.add(f"{coluna_revisao}4:{coluna_revisao}{ultima}")
    return ws


def escrever_simples(wb, nome, colunas, linhas, cor_aba, apoio=False):
    ws = nova_aba(wb, nome)
    ws.sheet_properties.tabColor = cor_aba
    escrever_cabecalho(ws, colunas)
    larguras = [c[2] for c in colunas]
    for i, valores in enumerate(linhas, start=2):
        for j, valor in enumerate(valores, start=1):
            escrever_celula(ws, i, j, valor, cor_fundo=FUNDO_APOIO if apoio else None)
        ws.row_dimensions[i].height = altura_estimada(list(zip(valores, larguras)), teto=150.0)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{max(len(linhas) + 1, 2)}"


def escrever_resumo(wb, linhas_resumo):
    ws = nova_aba(wb, "RESUMO")
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


def escrever_planilha_mestre(caminho, dados, contexto, linhas_resumo):
    wb = Workbook()
    escrever_leia_me(wb, contexto, dados)
    escrever_instrucoes(wb)
    escrever_aba_skus(wb, dados["linhas"], dados["ordem"], dados["cab"])
    escrever_simples(wb, "LISTAS", LISTAS_COLUNAS, dados["listas"], COR_AZUL)
    escrever_simples(wb, "REGRAS", REGRAS_COLUNAS, dados["regras"], COR_CINZA, apoio=True)
    escrever_simples(wb, "MLBS", MLBS_COLUNAS, dados["mlbs"], COR_CINZA, apoio=True)
    escrever_resumo(wb, linhas_resumo)
    wb.save(caminho)


def escrever_arquivos_por_lote(pasta, dados):
    """1 arquivo por lote: só as colunas de campo que aquele lote usa + as listas que ele referencia."""
    pasta.mkdir(parents=True, exist_ok=True)
    por_lote = defaultdict(list)
    for linha in dados["linhas"]:
        por_lote[linha["lote"]].append(linha)
    for lote, linhas in sorted(por_lote.items()):
        ordem = [a for a in dados["ordem"] if any(a in l["campos"] for l in linhas)]
        listas_usadas = {c["id_lista"] for l in linhas for c in l["campos"].values() if c["id_lista"]}
        wb = Workbook()
        escrever_instrucoes(wb)
        escrever_aba_skus(wb, linhas, ordem, montar_cabecalhos(linhas))
        escrever_simples(wb, "LISTAS", LISTAS_COLUNAS[:COLUNAS_LISTAS_NO_LOTE],
                         [x[:COLUNAS_LISTAS_NO_LOTE] for x in dados["listas"] if x[0] in listas_usadas], COR_AZUL)
        wb.save(pasta / f"lote_{lote:03d}.xlsx")
    return len(por_lote)

# ──────────────────────────────────────────────────────────────────────
# CONFERÊNCIA DO QUE A LLM DEVOLVEU (MODO = "validar")
# ──────────────────────────────────────────────────────────────────────

REGEX_NUMERO = re.compile(r"^-?\d+([.,]\d+)?$")
REGEX_NUMERO_UNIDADE = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(\S.*)$")


def resolver_caminho(texto):
    caminho = Path(texto)
    return caminho if caminho.is_absolute() else pasta_saida() / caminho


def celula_da_linha(linha, indice):
    return linha[indice] if indice < len(linha) else None


def carregar_regras_e_listas(caminho_mestre):
    """Da mestre: a regra de cada campo (REGRAS), as opções das listas (LISTAS) e a situação de cada campo em cada SKU (SKUS)."""
    wb = load_workbook(caminho_mestre, read_only=True, data_only=True)
    campos = {}
    for linha in wb["REGRAS"].iter_rows(min_row=2, values_only=True):
        if not linha[0]:
            continue
        campos[linha[0]] = {
            "label": linha[1], "tipo": linha[2], "limite": linha[3],
            "unidades": [u.strip() for u in str(linha[4]).split(";")] if linha[4] else [],
            "multi": linha[5] == "Sim",
        }
    listas = {}
    for linha in wb["LISTAS"].iter_rows(min_row=2, values_only=True):
        if linha[0]:
            listas[linha[0]] = [nome.strip() for nome in str(linha[3]).split(SEPARADOR_OPCOES)]

    situacao = {}  # sku -> {attr_id: {"obrigatorio", "tipo", "unidades", "limite", "lista"}}
    colunas = {}
    for numero, linha in enumerate(wb["SKUS"].iter_rows(values_only=True), start=1):
        if numero == 3:
            for i, nome in enumerate(linha):
                if nome not in SUBCOLUNAS:
                    colunas.setdefault(nome, i)
            for obrigatoria in ("SKU", "Campos deste SKU", "Listas deste SKU"):
                if obrigatoria not in colunas:
                    raise SystemExit(f"A mestre não tem a coluna '{obrigatoria}' (geração antiga?). Gere a planilha de novo.")
        elif numero > 3:
            sku = celula_da_linha(linha, colunas["SKU"])
            if not sku:
                continue
            listas_do_sku = dict(re.findall(r"([A-Za-z0-9_]+)→(L\d+)", str(celula_da_linha(linha, colunas["Listas deste SKU"]) or "")))
            situacao[sku] = {
                attr_id: {**dados, "lista": listas_do_sku.get(attr_id)}
                for attr_id, dados in ler_campos_do_sku(celula_da_linha(linha, colunas["Campos deste SKU"])).items()
            }
    wb.close()
    return campos, listas, situacao


def regra_do_campo_no_sku(campos, situacao_do_sku, attr_id):
    """Junta a regra do campo (REGRAS) com a situação dele neste SKU (SKUS). None = o campo não existe para o SKU."""
    no_sku, do_campo = situacao_do_sku.get(attr_id), campos.get(attr_id)
    if no_sku is None or do_campo is None:
        return None
    return {
        "label": do_campo["label"], "multi": do_campo["multi"],
        "tipo": no_sku["tipo"] or do_campo["tipo"],
        "obrigatorio": no_sku["obrigatorio"],
        "limite": no_sku["limite"] or do_campo["limite"],
        "unidades": no_sku["unidades"] or do_campo["unidades"],
        "lista": no_sku["lista"],
    }


def conferir_valor(valor, regra, listas):
    """Devolve a lista de problemas objetivos do valor que a LLM escreveu."""
    texto = str(valor).strip()
    problemas = []
    if texto.upper() == "N/A":
        if regra["obrigatorio"] == "Sim":
            problemas.append("N/A não é aceito em campo obrigatório")
        return problemas
    partes = [p.strip() for p in texto.split(",") if p.strip()] if regra["multi"] else [texto]
    if regra["limite"] and len(texto) > regra["limite"]:
        problemas.append(f"excede o limite ({len(texto)}/{regra['limite']})")
    if regra["tipo"] == "Lista fechada":
        validos = {n.strip().lower() for n in listas.get(regra["lista"], [])}
        fora = [p for p in partes if p.lower() not in validos]
        if fora:
            problemas.append("fora da lista: " + ", ".join(fora))
    elif regra["tipo"] == "Número":
        if not all(REGEX_NUMERO.match(p) for p in partes):
            problemas.append("não é um número")
    elif regra["tipo"] == "Número + unidade":
        for p in partes:
            achado = REGEX_NUMERO_UNIDADE.match(p)
            if not achado:
                problemas.append(f"formato inválido ('{p}'): use número, espaço e unidade")
            elif regra["unidades"] and achado.group(2).strip().lower() not in {u.lower() for u in regra["unidades"]}:
                problemas.append(f"unidade '{achado.group(2).strip()}' não aceita (aceitas: {'; '.join(regra['unidades'])})")
    return problemas


def validar_arquivo(caminho=None, dados_mestre=None, pasta_dos_checados=None):
    """Confere 1 arquivo preenchido. Sem argumentos: usa VALIDAR_ARQUIVO e VALIDAR_MESTRE e imprime o detalhe.
    Com argumentos (modo pasta): não imprime o detalhe e devolve o resultado para o consolidado."""
    individual = caminho is None
    if individual:
        if not VALIDAR_ARQUIVO or not VALIDAR_MESTRE:
            raise SystemExit("Preencha VALIDAR_ARQUIVO e VALIDAR_MESTRE na configuração do script.")
        caminho = resolver_caminho(VALIDAR_ARQUIVO)
        console.print(f"\n[bold]Conferindo[/bold] {caminho.name} contra a mestre {resolver_caminho(VALIDAR_MESTRE).name}...")
        dados_mestre = carregar_regras_e_listas(resolver_caminho(VALIDAR_MESTRE))
    campos, listas, situacao = dados_mestre

    wb = load_workbook(caminho)
    ws = wb["SKUS"]
    cabecalhos = {ws.cell(row=3, column=c).value: c for c in range(1, ws.max_column + 1)
                  if ws.cell(row=3, column=c).value not in SUBCOLUNAS}
    col_sku, col_checagem = cabecalhos["SKU"], cabecalhos["Checagem automática"]
    col_vinculo, col_marca_erp = cabecalhos["Vínculo ERP"], cabecalhos["Marca (ERP)"]
    col_produto, col_titulos, col_observacao = cabecalhos.get("Produto (ERP)"), cabecalhos.get("Títulos dos MLBs"), cabecalhos.get("Observações (LLM)")
    blocos = [(ws.cell(row=1, column=c).value, c, c + 1, c + 2)
              for c in range(1, ws.max_column + 1) if ws.cell(row=3, column=c).value == "Atual"]
    lote = re.sub(r"_preenchido$", "", caminho.stem)

    problemas_gerais = []
    contagem = Counter()
    revisao, confiancas_usadas = [], Counter()  # revisao: o que um humano precisa olhar (alimenta o consolidado)
    campos_existentes = campos_preenchidos = 0
    for r in range(4, ws.max_row + 1):
        sku = ws.cell(row=r, column=col_sku).value
        if not sku:
            continue
        problemas_da_linha, preenchidos = [], 0
        vinculo_erp = ws.cell(row=r, column=col_vinculo).value
        marca_erp = str(ws.cell(row=r, column=col_marca_erp).value or "").strip()
        situacao_do_sku = situacao.get(sku)
        if situacao_do_sku is None:
            problemas_gerais.append([sku, "(linha)", "SKU não existe na planilha mestre", sku])
            problemas_da_linha.append("SKU não existe na planilha mestre")
            contagem["SKU não existe na planilha mestre"] += 1
        for attr_id, c_atual, c_preencher, c_conf in (blocos if situacao_do_sku is not None else []):
            regra = regra_do_campo_no_sku(campos, situacao_do_sku, attr_id)  # a mestre diz quais campos existem para o SKU
            valor = ws.cell(row=r, column=c_preencher).value
            confianca = ws.cell(row=r, column=c_conf).value
            achados = []
            if regra is None:
                if valor not in (None, ""):
                    achados.append("campo que não existe para este SKU (não preencher)")
            elif valor in (None, ""):
                if regra["obrigatorio"] == "Sim" and confianca != "Sem evidência":
                    achados.append("obrigatório sem valor (e sem 'Sem evidência')")
            else:
                preenchidos += 1
                achados += conferir_valor(valor, regra, listas)
                # * [EXPLICAÇÃO] → Só com vínculo oficial (pelo SKU) a Marca (ERP) é a verdade; a caixa não conta (strip + lower).
                if (attr_id == "BRAND" and vinculo_erp == "SKU" and marca_erp and marca_erp.lower() not in MARCAS_ERP_QUE_NAO_SAO_FABRICANTE
                        and str(valor).strip().lower() != marca_erp.lower()):
                    achados.append(f"marca diferente da Marca (ERP): '{marca_erp}'")
                if confianca is None:
                    achados.append("sem confiança")
                elif confianca not in CONFIANCAS:
                    achados.append(f"confiança inválida ('{confianca}')")
            if regra is not None:
                campos_existentes += 1
                campos_preenchidos += valor not in (None, "")
                if confianca in CONFIANCAS:
                    confiancas_usadas[confianca] += 1
            if achados or confianca in CONFIANCAS_PARA_REVISAR:
                prioridade = 1 if achados else (2 if confianca == "Baixa" else 3)  # 1 = conferência, 2 = Baixa, 3 = Sem evidência
                produto = ws.cell(row=r, column=col_produto).value if col_produto else None
                if not produto and col_titulos:  # sem ERP: o título ajuda a reconhecer o produto
                    produto = str(ws.cell(row=r, column=col_titulos).value or "")[:90]
                revisao.append([
                    prioridade, lote, sku, produto, attr_id, regra["obrigatorio"] if regra else "-",
                    ws.cell(row=r, column=c_atual).value, valor, confianca, "; ".join(achados),
                    ws.cell(row=r, column=col_observacao).value if col_observacao else "",
                ])
            for achado in achados:
                problemas_gerais.append([sku, attr_id, achado, valor])
                problemas_da_linha.append(f"{attr_id}: {achado}")
                contagem[achado.split(" (")[0].split(":")[0]] += 1
        if problemas_da_linha:
            resultado = "; ".join(problemas_da_linha)
            contagem["linhas com problema"] += 1
        else:
            resultado = "OK" if preenchidos else "Sem preenchimento"
            contagem["linhas " + resultado.lower()] += 1
        celula = ws.cell(row=r, column=col_checagem, value=limpar_texto(resultado))
        celula.font, celula.alignment, celula.border = FONTE, ALINHA_TOPO, BORDA
        celula.fill = fundo("F8D7DA" if problemas_da_linha else ("D7EBD0" if preenchidos else "FFE8B3"))

    if "CHECAGEM" in wb.sheetnames:
        del wb["CHECAGEM"]
    aba = wb.create_sheet("CHECAGEM")
    aba.sheet_properties.tabColor = COR_VERDE
    escrever_cabecalho(aba, [("SKU", COR_VERDE, 22), ("Campo", COR_VERDE, 26), ("Problema", COR_VERDE, 60), ("Valor escrito", COR_VERDE, 40)])
    for i, linha in enumerate(problemas_gerais, start=2):
        for j, valor in enumerate(linha, start=1):
            escrever_celula(aba, i, j, valor)
    aba.freeze_panes = "A2"

    pasta_do_checado = pasta_dos_checados or PASTA_RESULTADOS  # o resultado da conferência também fica na pasta de resultados
    pasta_do_checado.mkdir(parents=True, exist_ok=True)
    saida = pasta_do_checado / (caminho.stem + "_checado.xlsx")
    wb.save(saida)
    if individual:
        console.print(f"\n[green]Pronto: {saida}[/green]\n")
        for rotulo, quantidade in contagem.most_common():
            console.print(f"  {rotulo}: {quantidade}")
        console.print(f"  total de problemas: {len(problemas_gerais)}")
    return {
        "lote": lote, "arquivo": caminho.name, "saida": saida, "erro": None,
        "contagem": contagem, "confiancas": confiancas_usadas,
        "campos_existentes": campos_existentes, "campos_preenchidos": campos_preenchidos,
        "problemas": len(problemas_gerais), "revisao": revisao,
    }


def validar_pasta():
    """Confere todos os *_preenchido.xlsx de uma pasta contra a mesma mestre e junta tudo num arquivo de revisão."""
    if not VALIDAR_PASTA or not VALIDAR_MESTRE:
        raise SystemExit("Preencha VALIDAR_PASTA e VALIDAR_MESTRE na configuração do script.")
    pasta = resolver_caminho(VALIDAR_PASTA)
    arquivos = sorted(p for p in pasta.glob("*_preenchido.xlsx") if not p.name.startswith("~$"))
    if not arquivos:
        raise SystemExit(f"Nenhum arquivo *_preenchido.xlsx em {pasta}")
    console.print(f"\n[bold]Conferindo {len(arquivos)} arquivos de[/bold] {pasta} [bold]contra a mestre[/bold] {resolver_caminho(VALIDAR_MESTRE).name}...")
    dados_mestre = carregar_regras_e_listas(resolver_caminho(VALIDAR_MESTRE))
    pasta_dos_checados = PASTA_RESULTADOS / "checados"
    resultados = []
    for arquivo in arquivos:
        try:
            resultado = validar_arquivo(arquivo, dados_mestre, pasta_dos_checados)
            c = resultado["contagem"]
            console.print(f"  {arquivo.name}: {c['linhas ok']} OK, {c['linhas com problema']} com problema, "
                          f"{c['linhas sem preenchimento']} sem preenchimento, {len(resultado['revisao'])} itens para revisão")
        except Exception as erro:  # um arquivo quebrado não pode derrubar os outros
            console.print(f"  [red]{arquivo.name}: não foi possível conferir ({erro})[/red]")
            resultado = {
                "lote": re.sub(r"_preenchido$", "", arquivo.stem), "arquivo": arquivo.name, "saida": None, "erro": str(erro),
                "contagem": Counter(), "confiancas": Counter(), "campos_existentes": 0, "campos_preenchidos": 0,
                "problemas": 0, "revisao": [],
            }
        resultados.append(resultado)
    consolidar_revisao(resultados)


def consolidar_revisao(resultados):
    """Um arquivo só para o humano: aba REVISAO (tudo que precisa de olho, em ordem de prioridade) e aba RESUMO (1 linha por lote)."""
    rotulos = {1: "1 - Conferência", 2: "2 - Baixa", 3: "3 - Sem evidência"}
    cores = {1: "F8D7DA", 2: "FFE8B3", 3: "E5E7EB"}
    ordem_obrigatorio = {"Sim": 0, "Condicional": 1, "Não": 2}  # dentro da prioridade, o obrigatório vem primeiro
    itens = sorted((i for r in resultados for i in r["revisao"]), key=lambda i: (i[0], ordem_obrigatorio.get(i[5], 3), i[1], i[2], i[4]))

    wb = Workbook()
    aba = nova_aba(wb, "REVISAO")
    aba.sheet_properties.tabColor = COR_AMBAR
    escrever_cabecalho(aba, [
        ("Prioridade", COR_AMBAR, 17), ("Lote", COR_AMBAR, 12), ("SKU", COR_AMBAR, 22), ("Produto (ERP) ou título", COR_AMBAR, 38),
        ("Campo", COR_AMBAR, 24), ("Obrigatório", COR_AMBAR, 13), ("Atual", COR_AMBAR, 28), ("PREENCHER (LLM)", COR_AMBAR, 28), ("Conf.", COR_AMBAR, 14),
        ("Problema da conferência", COR_AMBAR, 42), ("Observações (LLM)", COR_AMBAR, 50),
        ("Decisão humana", COR_VERDE, 18), ("Valor final", COR_VERDE, 28),
    ])
    for i, (prioridade, *resto) in enumerate(itens, start=2):
        escrever_celula(aba, i, 1, rotulos[prioridade], cor_fundo=cores[prioridade])
        for j, valor in enumerate(resto, start=2):
            escrever_celula(aba, i, j, valor)
        escrever_celula(aba, i, 12, None)
        escrever_celula(aba, i, 13, None)
    aba.freeze_panes = "D2"
    aba.auto_filter.ref = f"A1:M{max(len(itens) + 1, 2)}"
    if itens:
        decisao = DataValidation(type="list", formula1='"Aceitar LLM,Manter Atual,Corrigir"', allow_blank=True)
        aba.add_data_validation(decisao)
        decisao.add(f"L2:L{len(itens) + 1}")

    resumo = wb.create_sheet("RESUMO")
    resumo.sheet_properties.tabColor = COR_VERDE
    escrever_cabecalho(resumo, [
        ("Lote", COR_VERDE, 12), ("SKUs", COR_VERDE, 8), ("Campos que existem", COR_VERDE, 12), ("Preenchidos", COR_VERDE, 12),
        ("% preenchido", COR_VERDE, 12), ("Alta", COR_VERDE, 8), ("Média", COR_VERDE, 8), ("Baixa", COR_VERDE, 8),
        ("Sem evidência", COR_VERDE, 12), ("SKUs OK", COR_VERDE, 9), ("SKUs com problema", COR_VERDE, 11),
        ("SKUs sem preenchimento", COR_VERDE, 13), ("Itens para revisão", COR_VERDE, 11), ("Arquivo conferido / erro", COR_VERDE, 60),
    ])
    total = Counter()
    for i, r in enumerate(resultados, start=2):
        c, conf = r["contagem"], r["confiancas"]
        skus = c["linhas ok"] + c["linhas com problema"] + c["linhas sem preenchimento"]
        linha = [r["lote"], skus, r["campos_existentes"], r["campos_preenchidos"],
                 (r["campos_preenchidos"] / r["campos_existentes"]) if r["campos_existentes"] else None,
                 conf["Alta"], conf["Média"], conf["Baixa"], conf["Sem evidência"],
                 c["linhas ok"], c["linhas com problema"], c["linhas sem preenchimento"], len(r["revisao"]),
                 ("ERRO: " + r["erro"]) if r["erro"] else r["saida"].name]
        for j, valor in enumerate(linha, start=1):
            escrever_celula(resumo, i, j, valor, cor_fundo="F8D7DA" if r["erro"] else None, formato="0%" if j == 5 else None)
        for j in (2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13):
            total[j] += linha[j - 1] or 0
    linha_total = len(resultados) + 2
    escrever_celula(resumo, linha_total, 1, "TOTAL", negrito=True)
    for j in range(2, 15):
        valor = total[j] if j in total else None
        if j == 5:
            valor = (total[4] / total[3]) if total[3] else None
        escrever_celula(resumo, linha_total, j, valor, negrito=True, formato="0%" if j == 5 else None)
    resumo.freeze_panes = "B2"

    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    saida = PASTA_RESULTADOS / f"revisao_consolidada_{datetime.now():%Y%m%d_%H%M}.xlsx"
    wb.save(saida)

    por_prioridade = Counter(i[0] for i in itens)
    console.print(f"\n[green]Pronto: {saida}[/green]")
    console.print(f"  {len(resultados)} arquivos conferidos, {sum(1 for r in resultados if r['erro'])} com erro")
    console.print(f"  itens para revisão: {len(itens)} (conferência {por_prioridade[1]}, Baixa {por_prioridade[2]}, Sem evidência {por_prioridade[3]})")
    console.print(f"  campos preenchidos: {total[4]} de {total[3]}" + (f" ({total[4] / total[3]:.0%})" if total[3] else ""))
    console.print(f"  arquivos conferidos de cada lote: {PASTA_RESULTADOS / 'checados'}")


# ──────────────────────────────────────────────────────────────────────
# FLUXO PRINCIPAL
# ──────────────────────────────────────────────────────────────────────

def gerar():
    inicio = time.time()
    iniciar_django()
    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)  # antes de qualquer cache ou log
    console.print(f"\n[dim]Tudo o que este script gera fica em: {PASTA_RESULTADOS}[/dim]")

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

    console.print("\n[bold]3/6 Lendo as categorias na API (card, tipos, limites, listas, tags)...[/bold]")
    ids_categorias = sorted({i["category_id"] for i in itens.values() if i.get("category_id")})
    cache_categorias = {
        chave: valor for chave, valor in carregar_cache(CAMINHO_CACHE_CATEGORIAS).items()
        if isinstance(valor, dict) and valor.get("versao") == VERSAO_CACHE_CATEGORIAS
    }
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
    pasta = pasta_saida()
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = f"{datetime.now():%Y%m%d_%H%M}"
    nome = f"planilha_llm_{CONTA}_{'amostra' + str(LIMITE_SKUS) if LIMITE_SKUS else 'completa'}_{carimbo}.xlsx"
    caminho = pasta / nome
    escrever_planilha_mestre(caminho, dados, contexto, linhas_resumo)
    console.print(f"\n[green]Pronto: {caminho}[/green]")
    if GERAR_ARQUIVOS_POR_LOTE:
        pasta_lotes = pasta / f"lotes_{CONTA}_{carimbo}"
        quantidade = escrever_arquivos_por_lote(pasta_lotes, dados)
        console.print(f"[green]Pronto: {quantidade} arquivos de lote em {pasta_lotes}[/green]")
    console.print()

    for rotulo, valor in linhas_resumo:
        if rotulo is None:
            console.print(f"[bold]{valor}[/bold]")
        else:
            console.print(f"  {rotulo}: {valor}")
    console.print("\n[dim]Cole este resumo na conversa para eu analisar o comportamento.[/dim]")


def main():
    if MODO == "validar":
        validar_pasta() if VALIDAR_PASTA else validar_arquivo()
    elif MODO == "gerar":
        gerar()
    else:
        raise SystemExit(f"MODO inválido: {MODO!r} (use 'gerar' ou 'validar').")


if __name__ == "__main__":
    main()