# scripts_exploracao_ML/montar_contexto_llm_por_sku.py
#
# Monta, pra uma LISTA de SKUs (lote pequeno de teste, não a base inteira
# ainda), 1 pacote de CONTEXTO por SKU (dado puro, sem instrução de como
# a LLM deve trabalhar — isso fica no prompt/conversa, construído à
# parte) — SEM nenhuma integração de API de LLM (decisão de Matheus: toda
# "comunicação" com LLM é manual/Cowork; este script só prepara o
# material, nunca chama LLM nenhuma).
#
# Objetivo desse lote: olhar os dados de um punhado de SKUs de categorias
# diferentes ANTES de fechar o conjunto de regras de preenchimento — ver
# que tipo de variação/complexidade aparece (categorias com mais/menos
# campos, listas fechadas grandes, SKU sem produto no ERP, etc.) antes de
# escalar pra todos os SKUs.
#
# Reaproveita TUDO do script anterior (1 SKU só): mesmo agrupamento por
# banco, mesma exclusão de catálogo, mesmo card de Características
# principais por categoria (MAIN menos allow_variations), mesmo catálogo
# de atributos (value_type/values) via /categories/$ID/attributes.
# Mudança: SKU vira SKUS (lista) e os caches de categoria (card +
# definições) são compartilhados entre os SKUs do lote inteiro.
#
# Pré-requisito: banco atualizado pros SKUs do lote (rodar a
# sincronização antes, como de costume).
#
# Saída: 1 arquivo contexto_llm_{SKU}.json por SKU do lote.
#
# Só leitura. Não toca em nada na API além de GET, não grava no banco,
# não chama nenhuma LLM.

import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

# ==== CONFIGURA AQUI ANTES DE RODAR ====
SKUS = [
    "F7908050719121.001",
    # adicione aqui outros SKUs do lote de teste — ideal: categorias
    # diferentes entre si, incluindo o caso que disparou o projeto
    # (Bota Ortopédica Imobilizadora Curta Bilateral Takecare).
]
CONTA = "MB"  # "MB" (Magazine) ou "SV" (Samvale) — todo o lote usa a mesma conta por enquanto
LIMITE_OPCOES_LISTA = 150  # acima disso, a lista de opções válidas não entra inteira no .json
# ========================================

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default. Precisa rodar
#                  ANTES de qualquer acesso ao ORM.

from rich.console import Console

from mercado_livre.funcoes_auxiliares.classificacao_catalogo import carregar_variacoes_por_sku
from mercado_livre.models import TipoDeAnuncioMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
PASTA_SAIDA = Path(__file__).resolve().parent

console = Console()

Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo


def _tem_tag(attr: dict, nome_tag: str) -> bool:
    tags = attr.get("tags")
    if isinstance(tags, dict):
        return bool(tags.get(nome_tag))
    if isinstance(tags, list):
        return nome_tag in tags
    return False


def buscar_card_caracteristicas_principais(category_id: str) -> dict:
    """Grupo MAIN do technical_specs/input, menos allow_variations. {attr_id: {label, required}}."""
    resposta = chamar_api(
        "GET", f"/categories/{category_id}/technical_specs/input",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="montar_contexto_llm_por_sku",
    )
    technical_specs = resposta.json()

    card = {}
    for grupo in technical_specs.get("groups", []):
        if grupo.get("id") != "MAIN":
            continue
        for componente in grupo.get("components", []):
            for attr in componente.get("attributes", []):
                attr_id = attr.get("id")
                if not attr_id:
                    continue
                if _tem_tag(attr, "allow_variations"):
                    continue
                card[attr_id] = {
                    "label": attr.get("label") or attr.get("name") or attr_id,
                    "required": _tem_tag(attr, "required"),
                }
    return card


def buscar_definicoes_de_atributos(category_id: str) -> dict:
    """GET /categories/$ID/attributes — {attr_id: attr_bruto}, com value_type/values."""
    resposta = chamar_api(
        "GET", f"/categories/{category_id}/attributes",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="montar_contexto_llm_por_sku",
    )
    definicoes = {}
    for attr in resposta.json():
        attr_id = attr.get("id")
        if attr_id:
            definicoes[attr_id] = attr
    return definicoes


def buscar_atributos_preenchidos(mlb: str):
    """GET /items/{mlb} -> category_id + {attr_id: valor}, ou None se erro."""
    try:
        resposta = chamar_api(
            "GET", f"/items/{mlb}",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            params={"include_internal_attributes": "true"},
            nome_log="montar_contexto_llm_por_sku",
        )
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        console.print(f"  [red]Erro ao buscar {mlb}: {erro}[/red]")
        return None

    body = resposta.json()
    valores = {}
    for attr in body.get("attributes", []):
        attr_id = attr.get("id")
        if not attr_id:
            continue
        valor = attr.get("value_name")
        if valor is None:
            valores_lista = attr.get("values") or []
            if valores_lista:
                valor = valores_lista[0].get("name")
        valores[attr_id] = valor

    return {
        "category_id": body.get("category_id"),
        "valores": valores,
    }


# Caches COMPARTILHADOS entre todos os SKUs do lote — se 2 SKUs caírem na
# mesma categoria, a 2ª vez não chama a API de novo.
cache_card_por_categoria = {}
cache_definicoes_por_categoria = {}


def montar_contexto_de_1_sku(sku: str):
    """Roda o fluxo inteiro pra 1 SKU e devolve o dict pronto pra virar .json (ou None se não deu pra processar)."""

    variacoes_por_sku = carregar_variacoes_por_sku(skus=[sku])
    variacoes = variacoes_por_sku.get(sku, [])

    if not variacoes:
        console.print(f"  [red]Nenhuma variação encontrada no banco pro SKU '{sku}' — pulando.[/red]")
        return None

    produto = variacoes[0].produto
    if produto is None:
        console.print(f"  [yellow]SKU '{sku}' sem Produto conectado no ERP — título/descrição ficarão vazios.[/yellow]")

    variacoes_por_mlb = defaultdict(list)
    for v in variacoes:
        variacoes_por_mlb[v.anuncio.mlb].append(v)

    mlbs_catalogo = []
    mlbs_sem_tipo = []
    mlbs_a_processar = []
    titulo_anuncio_por_mlb = {}

    for mlb, vars_do_mlb in variacoes_por_mlb.items():
        anuncio = vars_do_mlb[0].anuncio
        titulo_anuncio_por_mlb[mlb] = anuncio.titulo_anuncio
        tipo = anuncio.tipo_de_anuncio
        if tipo is None:
            mlbs_sem_tipo.append(mlb)
            mlbs_a_processar.append(mlb)
            continue
        if tipo.classificacao_catalogo == Classificacao.CATALOGO:
            mlbs_catalogo.append(mlb)
            continue
        mlbs_a_processar.append(mlb)

    console.print(f"  {len(variacoes_por_mlb)} MLB(s) no banco — "
                  f"{len(mlbs_catalogo)} ignorado(s) por catálogo, "
                  f"{len(mlbs_a_processar)} a processar.")
    if mlbs_sem_tipo:
        console.print(f"  [yellow]Sem tipo_de_anuncio (não ignorados): {mlbs_sem_tipo}[/yellow]")

    if not mlbs_a_processar:
        console.print("  [red]Todos os MLBs desse SKU são de catálogo — nada pra montar.[/red]")
        return None

    dados_por_mlb = {}
    for mlb in mlbs_a_processar:
        resultado = buscar_atributos_preenchidos(mlb)
        if resultado is not None:
            dados_por_mlb[mlb] = resultado

    if not dados_por_mlb:
        console.print("  [red]Nenhum MLB retornou dados — pulando SKU.[/red]")
        return None

    colunas_ordem = []

    for mlb, dados in dados_por_mlb.items():
        category_id = dados["category_id"]
        if category_id not in cache_card_por_categoria:
            console.print(f"  Categoria nova: {category_id} — buscando card + catálogo de atributos...")
            cache_card_por_categoria[category_id] = buscar_card_caracteristicas_principais(category_id)
            cache_definicoes_por_categoria[category_id] = buscar_definicoes_de_atributos(category_id)

        for attr_id in cache_card_por_categoria[category_id]:
            if attr_id not in colunas_ordem:
                colunas_ordem.append(attr_id)

    anuncios = []
    for mlb, dados in dados_por_mlb.items():
        card_desta_categoria = cache_card_por_categoria[dados["category_id"]]
        caracteristicas_atuais = {
            attr_id: dados["valores"].get(attr_id)
            for attr_id in card_desta_categoria
        }
        anuncios.append({
            "mlb": mlb,
            "titulo": titulo_anuncio_por_mlb.get(mlb),
            "category_id": dados["category_id"],
            "caracteristicas_atuais": caracteristicas_atuais,
        })

    caracteristicas = {}
    for attr_id in colunas_ordem:
        # categoria de referência: a 1ª categoria (entre as deste SKU) que tem esse attr_id no card
        category_id_ref = next(
            dados["category_id"] for dados in dados_por_mlb.values()
            if attr_id in cache_card_por_categoria[dados["category_id"]]
        )
        meta = cache_card_por_categoria[category_id_ref][attr_id]
        definicao = cache_definicoes_por_categoria[category_id_ref].get(attr_id, {})
        opcoes = definicao.get("values") or []

        entrada = {
            "label": meta["label"],
            "obrigatorio": meta["required"],
        }
        if opcoes:
            entrada["tipo_valor"] = "lista_fechada"
            if len(opcoes) <= LIMITE_OPCOES_LISTA:
                entrada["opcoes_validas"] = [
                    {"id": o.get("id"), "nome": o.get("name")} for o in opcoes
                ]
            else:
                entrada["opcoes_validas"] = None
                entrada["aviso"] = f"{len(opcoes)} opções — lista grande demais, não incluída aqui."
        else:
            entrada["tipo_valor"] = "texto_livre"
            if definicao.get("value_max_length"):
                entrada["tamanho_maximo"] = definicao["value_max_length"]

        caracteristicas[attr_id] = entrada

    return {
        "sku": sku,
        "produto_erp": {
            "titulo": produto.titulo,
            "descricao": produto.descricao,
        } if produto is not None else None,
        "mlbs_ignorados_catalogo": mlbs_catalogo,
        "mlbs_sem_tipo_de_anuncio": mlbs_sem_tipo,
        "anuncios": anuncios,
        "caracteristicas": caracteristicas,
    }


# ──────────────────────────────────────────────────────────────────────
# Roda o lote inteiro.
# ──────────────────────────────────────────────────────────────────────

processados = []
pulados = []

for sku in SKUS:
    console.print(f"\n[bold]SKU {sku}[/bold]")
    contexto = montar_contexto_de_1_sku(sku)
    if contexto is None:
        pulados.append(sku)
        continue

    caminho_saida = PASTA_SAIDA / f"contexto_llm_{sku}.json"
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(contexto, f, ensure_ascii=False, indent=2)
    console.print(f"  [green]Salvo em: {caminho_saida}[/green]")
    processados.append(sku)

console.print(f"\n[bold]Lote concluído.[/bold] {len(processados)} processado(s), {len(pulados)} pulado(s).")
if pulados:
    console.print(f"  Pulados: {pulados}")
console.print(f"  Categorias distintas encontradas no lote: "
              f"{len(cache_card_por_categoria)} {list(cache_card_por_categoria.keys())}")