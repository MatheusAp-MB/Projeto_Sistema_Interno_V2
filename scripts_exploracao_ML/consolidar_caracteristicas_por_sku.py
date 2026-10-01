# scripts_exploracao_ML/consolidar_caracteristicas_por_sku.py
#
# Lê TODOS os MLBs de 1 SKU (via banco — VariacaoAnuncioMercadoLivre,
# reaproveitando carregar_variacoes_por_sku() de
# mercado_livre/funcoes_auxiliares/classificacao_catalogo.py) e monta uma
# tabela consolidada das Características principais de cada um.
#
# Pré-requisito: o banco precisa estar atualizado pro SKU em questão —
# rodar antes o comando de integração/sincronização de anúncios ML de
# sempre. Este script só LÊ o banco, nunca escreve nele.
#
# Regras de negócio confirmadas (ver Checkpoint - Investigação da API de
# Atributos do Mercado Livre, no vault):
#   - Ignora TODO MLB classificado como Catálogo (classificacao_catalogo
#     == CATALOGO) — o ML não deixa alterar características de anúncios
#     de catálogo, então não faz sentido nem ler esses pra essa feature.
#   - Características principais = grupo MAIN do technical_specs/input
#     da categoria, EXCETO os atributos com a tag allow_variations (esses
#     vivem na seção separada "Características da variação" da tela,
#     fora do escopo — confirmado visualmente com COLOR no teste da
#     MLB2616936722). Essa generalização pela tag ainda NÃO foi validada
#     numa 2ª categoria real — o script avisa no console toda vez que
#     exclui um atributo por essa regra, e imprime o card final de cada
#     categoria, pra conferência visual.
#
# Visualização pedida: 1 linha por grupo de MLBs com os MESMOS valores em
# todas as colunas de característica; MLB com qualquer valor divergente
# vira linha própria.
#
# Terceiro script do novo objetivo "Características/Atributos ML" — depois
# de investigar_atributos_item.py (1 MLB, retorno bruto) e
# comparar_atributos_item_vs_grupo_main.py (1 MLB vs grupo MAIN da
# categoria). Este aqui generaliza pra TODOS os MLBs de 1 SKU.
#
# SKU de teste: F7908050719121.001 (mesmo produto dos 2 scripts anteriores).
#
# Só leitura. Não toca em nada na API além de GET, não grava no banco.

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
SKU = "F7908050719121.001"
CONTA = "MB"  # "MB" (Magazine) ou "SV" (Samvale) — CONFIRME de qual empresa é esse SKU
# ========================================

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Mesmo motivo dos outros scripts que tocam o ORM: sem isso o
#                  Django cai no banco default, e pra CONTA="SV" isso leria
#                  dado do MB silenciosamente. Precisa rodar ANTES de qualquer
#                  acesso ao ORM (carregar_variacoes_por_sku logo abaixo).

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from mercado_livre.funcoes_auxiliares.classificacao_catalogo import carregar_variacoes_por_sku
from mercado_livre.models import TipoDeAnuncioMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
CAMINHO_SAIDA = Path(__file__).resolve().parent / f"consolidado_caracteristicas_{SKU}.json"

console = Console()

Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

FORA_DA_CATEGORIA = "— (fora da categoria)"
VAZIO = "(vazio)"


def _tem_tag(attr: dict, nome_tag: str) -> bool:
    tags = attr.get("tags")
    if isinstance(tags, dict):
        return bool(tags.get(nome_tag))
    if isinstance(tags, list):
        return nome_tag in tags
    return False


def buscar_card_caracteristicas_principais(category_id: str) -> dict:
    """
    Busca technical_specs/input da categoria e devolve só os atributos do
    grupo MAIN que representam o card "Características principais" de
    verdade — ou seja, MAIN menos os atributos marcados allow_variations
    (esses vão pra "Características da variação", fora do escopo).
    Devolve {attr_id: {"label": ..., "required": ...}}.
    """
    resposta = chamar_api(
        "GET", f"/categories/{category_id}/technical_specs/input",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log="consolidar_caracteristicas_por_sku",
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
                    console.print(
                        f"  [yellow]Categoria {category_id}: excluindo '{attr_id}' do card "
                        f"(tag allow_variations — vai pra Características da variação)[/yellow]"
                    )
                    continue
                card[attr_id] = {
                    "label": attr.get("label") or attr.get("name") or attr_id,
                    "required": _tem_tag(attr, "required"),
                }

    console.print(f"  Categoria {category_id}: card final = {list(card.keys())} ({len(card)} atributos)")
    return card


def buscar_atributos_preenchidos(mlb: str):
    """GET /items/{mlb} — devolve {"category_id", "valores": {attr_id: valor}}, ou None se erro."""
    try:
        resposta = chamar_api(
            "GET", f"/items/{mlb}",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            params={"include_internal_attributes": "true"},
            nome_log="consolidar_caracteristicas_por_sku",
        )
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        console.print(f"[red]Erro ao buscar {mlb}: {erro}[/red]")
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


# ──────────────────────────────────────────────────────────────────────
# 1) Todos os MLBs do SKU, via banco (mesma função de sempre pra
#    agrupamento + classificação de catálogo).
# ──────────────────────────────────────────────────────────────────────

variacoes_por_sku = carregar_variacoes_por_sku(skus=[SKU])
variacoes = variacoes_por_sku.get(SKU, [])

if not variacoes:
    console.print(Panel(
        f"Nenhuma variação encontrada no banco pro SKU '{SKU}'.\n"
        "Confere se o SKU está certo, ou se o banco precisa ser sincronizado "
        "antes (comando de integração de anúncios ML).",
        title="SKU não encontrado", style="red",
    ))
    sys.exit(1)

variacoes_por_mlb = defaultdict(list)
for v in variacoes:
    variacoes_por_mlb[v.anuncio.mlb].append(v)

mlbs_catalogo = []
mlbs_sem_tipo = []
mlbs_a_processar = []

for mlb, vars_do_mlb in variacoes_por_mlb.items():
    tipo = vars_do_mlb[0].anuncio.tipo_de_anuncio
    if tipo is None:
        mlbs_sem_tipo.append(mlb)
        mlbs_a_processar.append(mlb)  # não ignora por padrão — só avisa
        continue
    if tipo.classificacao_catalogo == Classificacao.CATALOGO:
        mlbs_catalogo.append(mlb)
        continue
    mlbs_a_processar.append(mlb)

console.print(f"SKU {SKU}: {len(variacoes_por_mlb)} MLB(s) no banco.")
console.print(f"  Ignorados por catálogo: {len(mlbs_catalogo)} {mlbs_catalogo}")
if mlbs_sem_tipo:
    console.print(f"  [yellow]Sem tipo_de_anuncio (não ignorados, confira manualmente): {mlbs_sem_tipo}[/yellow]")
console.print(f"  A processar: {len(mlbs_a_processar)} {mlbs_a_processar}\n")

if not mlbs_a_processar:
    console.print("[red]Todos os MLBs desse SKU são de catálogo — nada pra consolidar.[/red]")
    sys.exit(0)


# ──────────────────────────────────────────────────────────────────────
# 2) Pra cada MLB restante: busca ao vivo os atributos preenchidos +
#    category_id (1 GET /items por MLB).
# ──────────────────────────────────────────────────────────────────────

dados_por_mlb = {}
for mlb in mlbs_a_processar:
    resultado = buscar_atributos_preenchidos(mlb)
    if resultado is not None:
        dados_por_mlb[mlb] = resultado

if not dados_por_mlb:
    console.print("[red]Nenhum MLB retornou dados — abortando.[/red]")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────
# 3) Card de Características principais por categoria (cacheado — SKUs
#    costumam ter todos os MLBs na mesma categoria, mas o script aguenta
#    categorias diferentes dentro do mesmo SKU).
# ──────────────────────────────────────────────────────────────────────

cache_card_por_categoria = {}
colunas_ordem = []  # ids de característica, na ordem em que foram descobertos
labels_coluna = {}  # attr_id -> label legível

for mlb, dados in dados_por_mlb.items():
    category_id = dados["category_id"]
    if category_id not in cache_card_por_categoria:
        console.print(f"Buscando card de Características principais da categoria {category_id}...")
        cache_card_por_categoria[category_id] = buscar_card_caracteristicas_principais(category_id)

    for attr_id, meta in cache_card_por_categoria[category_id].items():
        if attr_id not in labels_coluna:
            colunas_ordem.append(attr_id)
            labels_coluna[attr_id] = meta["label"]


# ──────────────────────────────────────────────────────────────────────
# 4) Monta o "vetor de características" de cada MLB (1 valor por coluna
#    — marcado como fora da categoria quando o atributo nem existe no
#    card da categoria desse MLB específico).
# ──────────────────────────────────────────────────────────────────────

vetor_por_mlb = {}
for mlb, dados in dados_por_mlb.items():
    card_desta_categoria = cache_card_por_categoria[dados["category_id"]]
    vetor = []
    for attr_id in colunas_ordem:
        if attr_id not in card_desta_categoria:
            vetor.append(FORA_DA_CATEGORIA)
            continue
        valor = dados["valores"].get(attr_id)
        vetor.append(valor if valor else VAZIO)
    vetor_por_mlb[mlb] = tuple(vetor)


# ──────────────────────────────────────────────────────────────────────
# 5) Agrupa por vetor idêntico — 1 linha por grupo, maior grupo primeiro
#    (consenso). MLB sozinho num grupo = divergência real.
# ──────────────────────────────────────────────────────────────────────

mlbs_por_vetor = defaultdict(list)
for mlb, vetor in vetor_por_mlb.items():
    mlbs_por_vetor[vetor].append(mlb)

grupos = sorted(mlbs_por_vetor.items(), key=lambda item: -len(item[1]))


# ──────────────────────────────────────────────────────────────────────
# 6) Saída.
# ──────────────────────────────────────────────────────────────────────

tabela = Table(title=f"Características principais consolidadas — SKU {SKU}", show_lines=True)
tabela.add_column("MLB(s)", style="bold")
for attr_id in colunas_ordem:
    tabela.add_column(labels_coluna[attr_id])

for idx, (vetor, mlbs) in enumerate(grupos):
    estilo = None if idx == 0 else "yellow"
    tabela.add_row(
        "\n".join(mlbs) if len(mlbs) > 1 else mlbs[0],
        *vetor,
        style=estilo,
    )

console.print(tabela)

if len(grupos) == 1:
    console.print(
        f"\n[green]Consenso total — os {len(dados_por_mlb)} MLB(s) processados têm exatamente "
        f"as mesmas características.[/green]"
    )
else:
    console.print(
        f"\n[yellow]{len(grupos)} grupos de características diferentes entre os "
        f"{len(dados_por_mlb)} MLB(s) processados — revisar divergência(s) acima.[/yellow]"
    )

saida = {
    "sku": SKU,
    "mlbs_ignorados_catalogo": mlbs_catalogo,
    "mlbs_sem_tipo_de_anuncio": mlbs_sem_tipo,
    "colunas": [{"id": attr_id, "label": labels_coluna[attr_id]} for attr_id in colunas_ordem],
    "mlbs": {
        mlb: {
            "category_id": dados_por_mlb[mlb]["category_id"],
            "valores": dict(zip(colunas_ordem, vetor_por_mlb[mlb])),
        }
        for mlb in dados_por_mlb
    },
}
with open(CAMINHO_SAIDA, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2)

console.print(f"\nDados completos salvos em: {CAMINHO_SAIDA}")