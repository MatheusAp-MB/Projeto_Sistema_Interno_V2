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
#
# Rodada 2 (01/10/2026) — SKUS deixou de ser lista manual. Pedido de
# Matheus: parar de escolher SKU à mão. `selecionar_skus_candidatos()`
# escolhe os candidatos sozinha, direto do banco (nenhuma chamada à API
# nessa etapa — só depois, 1x por SKU já selecionado, no fluxo de sempre),
# priorizando diversidade de categoria: round-robin por categoria e,
# dentro da mesma categoria, prioriza o SKU com mais MLBs não-catálogo
# (mais chance de achar divergência real, como no teste manual anterior).
#
# Rodada 3 (01/10/2026) — 5 mudanças, todas aditivas:
#   1. Metadados de cada campo agora são FUNDIDOS entre as categorias do
#      SKU. Decisão de Matheus: a ficha é do SKU, não da categoria — o SKU
#      precisa de "Modelo" e "Cor", e cada MLB só recebe o subconjunto que
#      a categoria dele pede. Regras: obrigatório se qualquer categoria
#      exigir; opções = interseção entre as categorias com lista fechada;
#      tamanho máximo = o menor. Divergências viram "avisos" no campo.
#   2. Valores atuais agregados por SKU, com contagem e lista de MLBs.
#   3. produto_erp.marca (referência pro BRAND — Marca é a marca real).
#   4. Só entram na ficha MLBs com status em STATUS_ACEITOS; os demais vão
#      pra mlbs_ignorados_inativos (mesmo tratamento do catálogo).
#   5. Dados do próprio GET /items (nenhuma chamada extra): SKU gravado no
#      ML, family_id/family_name, variações (id, SKU, atributos) e status
#      no ML, comparados com o que o banco tem, em "alertas" por MLB.
#      Motivo: um MLB "pai" com variações pode pertencer a mais de 1 SKU
#      (caso do MLB6296165596, agrupado no SKU F7898415014148.001).

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
CONTA = "MB"  # "MB" (Magazine) ou "SV" (Samvale) — todo o lote usa a mesma conta por enquanto
QUANTIDADE_LOTE = 10  # quantos SKUs distintos processar neste lote (seleção automática, ver abaixo)
SKUS_FIXOS = []  # opcional: SKUs que SEMPRE entram no lote (contam dentro de QUANTIDADE_LOTE). Vazio = só seleção automática.
STATUS_ACEITOS = {"active", "paused"}  # status (TipoDeAnuncioMercadoLivre.Status) que entram na ficha; os demais viram mlbs_ignorados_inativos
LIMITE_OPCOES_LISTA = 150  # acima disso, a lista de opções válidas não entra inteira no .json
# ========================================

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE

EMPRESA_POR_PREFIXO = {'MB': EMPRESA_MAGAZINE, 'SV': EMPRESA_SAMVALE}
definir_empresa_ativa(EMPRESA_POR_PREFIXO[CONTA])
# * [EXPLICAÇÃO] → Sem isso o Django cai no banco default. Precisa rodar
#                  ANTES de qualquer acesso ao ORM — inclusive a seleção
#                  automática de candidatos abaixo, que já é ORM.

from django.db.models import Q
from rich.console import Console

from mercado_livre.funcoes_auxiliares.classificacao_catalogo import carregar_variacoes_por_sku
from mercado_livre.models import TipoDeAnuncioMercadoLivre, VariacaoAnuncioMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
PASTA_SAIDA = Path(__file__).resolve().parent

console = Console()

Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo


# ──────────────────────────────────────────────────────────────────────
# SELEÇÃO AUTOMÁTICA DE CANDIDATOS — só banco, nenhuma chamada à API.
# ──────────────────────────────────────────────────────────────────────

def selecionar_skus_candidatos(quantidade: int) -> list[dict]:
    """
    Seleciona `quantidade` SKUs distintos automaticamente — sem escolha
    manual. Critério: máxima diversidade de categoria (round-robin, 1 SKU
    de cada categoria distinta por vez; só repete categoria quando não
    sobra categoria nova) e, dentro da mesma categoria, prioriza o SKU
    com mais MLBs não-catálogo (mais chance de achar divergência real
    entre eles, igual ao teste manual anterior — SKU F7908050719121.001,
    9 grupos divergentes em 13 MLBs).

    Só conta MLBs que vão de fato entrar na ficha: fora catálogo e fora
    status que não está em STATUS_ACEITOS (MLB sem tipo_de_anuncio passa,
    igual ao fluxo principal, que processa e avisa).

    Mesmo agrupamento por SKU de carregar_variacoes_por_sku (produto.sku
    -> sku_ml -> mlb, nessa ordem de fallback), mas direto por query —
    não reaproveita carregar_variacoes_por_sku aqui porque ela carrega a
    base inteira com select_related pesado (qualidade, recomendacoes,
    promocoes) que essa etapa não usa; aqui só precisamos de
    mlb/produto/sku_ml/categoria.

    SKUs sem nenhuma variação com categoria resolvida no banco ficam de
    fora (não tem como avaliar diversidade de categoria deles) — precisa
    do popular_banco já ter rodado.

    Retorna lista de dicts {sku, categoria, total_mlbs}, não só a lista
    de SKUs — pra dar pra imprimir o motivo da escolha antes de rodar o
    lote.
    """
    qs = (
        VariacaoAnuncioMercadoLivre.objects
        .select_related('anuncio', 'anuncio__tipo_de_anuncio', 'produto')
        .exclude(anuncio__eh_fossil_migracao=True)
        .exclude(anuncio__tipo_de_anuncio__classificacao_catalogo=Classificacao.CATALOGO)
        .exclude(categoria__isnull=True)
        .filter(
            Q(anuncio__tipo_de_anuncio__status__in=STATUS_ACEITOS)
            | Q(anuncio__tipo_de_anuncio__isnull=True)
        )
    )

    mlbs_por_sku = defaultdict(set)
    contagem_categoria_por_sku = defaultdict(lambda: defaultdict(int))

    for v in qs:
        chave = v.produto.sku if v.produto else (v.sku_ml or v.anuncio.mlb)
        mlbs_por_sku[chave].add(v.anuncio.mlb)
        contagem_categoria_por_sku[chave][v.categoria_id] += 1

    candidatos = []
    for sku, mlbs in mlbs_por_sku.items():
        categoria_representativa = max(
            contagem_categoria_por_sku[sku].items(), key=lambda par: par[1]
        )[0]
        candidatos.append({
            "sku": sku,
            "categoria": categoria_representativa,
            "total_mlbs": len(mlbs),
        })

    candidatos_por_categoria = defaultdict(list)
    for c in candidatos:
        candidatos_por_categoria[c["categoria"]].append(c)
    for fila in candidatos_por_categoria.values():
        fila.sort(key=lambda c: c["total_mlbs"], reverse=True)

    categorias_ordenadas = sorted(candidatos_por_categoria.keys())
    selecionados = []
    rodada = 0
    while len(selecionados) < quantidade:
        algum_novo_nesta_rodada = False
        for categoria in categorias_ordenadas:
            fila = candidatos_por_categoria[categoria]
            if rodada < len(fila):
                selecionados.append(fila[rodada])
                algum_novo_nesta_rodada = True
                if len(selecionados) == quantidade:
                    break
        if not algum_novo_nesta_rodada:
            break  # esgotou todos os candidatos elegíveis do banco
        rodada += 1

    return selecionados


console.print(f"\n[bold]Montando o lote de {QUANTIDADE_LOTE} SKUs "
              f"(diversidade de categoria, só banco)...[/bold]")
SKUS = list(SKUS_FIXOS)
for sku_fixo in SKUS_FIXOS:
    console.print(f"  {sku_fixo:<25} (fixo, vindo de SKUS_FIXOS)")

candidatos_selecionados = selecionar_skus_candidatos(QUANTIDADE_LOTE + len(SKUS_FIXOS))
for c in candidatos_selecionados:
    if len(SKUS) >= QUANTIDADE_LOTE:
        break
    if c["sku"] in SKUS:
        continue
    SKUS.append(c["sku"])
    console.print(f"  {c['sku']:<25} categoria {c['categoria']:<12} "
                  f"({c['total_mlbs']} MLB(s) elegíveis)")

if len(SKUS) < QUANTIDADE_LOTE:
    console.print(f"[yellow]Só {len(SKUS)} SKU(s) elegível(eis) no banco "
                  f"(menos que os {QUANTIDADE_LOTE} pedidos).[/yellow]")


# ──────────────────────────────────────────────────────────────────────
# LEITURA DA API
# ──────────────────────────────────────────────────────────────────────

def _tem_tag(attr: dict, nome_tag: str) -> bool:
    tags = attr.get("tags")
    if isinstance(tags, dict):
        return bool(tags.get(nome_tag))
    if isinstance(tags, list):
        return nome_tag in tags
    return False


def _extrair_sku(item_ou_variacao: dict):
    # Mesma lógica de api_mercado_livre/detalhes_ml.py (_extrair_sku e
    # _extrair_sku_variacao): SELLER_SKU nos atributos; se não houver,
    # seller_custom_field.
    for attr in item_ou_variacao.get("attributes") or []:
        if attr.get("id") == "SELLER_SKU":
            return attr.get("value_name")
    return item_ou_variacao.get("seller_custom_field")


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
    """
    GET /items/{mlb} -> dict com category_id, valores {attr_id: valor} e os
    dados de identidade do anúncio no ML (status, SKU gravado, família,
    variações), ou None se erro. Tudo vem da MESMA chamada — nenhuma
    chamada extra pra identidade.
    """
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
        if isinstance(valor, str):
            valor = valor.strip() or None
        valores[attr_id] = valor

    variacoes = [
        {
            "id": var.get("id"),
            "sku": _extrair_sku(var),
            "atributos": " / ".join(
                c.get("value_name", "") for c in var.get("attribute_combinations", []) if c.get("value_name")
            ) or None,
        }
        for var in body.get("variations") or []
    ]

    return {
        "category_id": body.get("category_id"),
        "valores": valores,
        "status_ml": body.get("status"),
        "sku_no_ml": _extrair_sku(body),
        "family_id": body.get("family_id"),
        "family_name": body.get("family_name"),
        "variacoes": variacoes,
    }


# Caches COMPARTILHADOS entre todos os SKUs do lote — se 2 SKUs caírem na
# mesma categoria, a 2ª vez não chama a API de novo.
cache_card_por_categoria = {}
cache_definicoes_por_categoria = {}


# ──────────────────────────────────────────────────────────────────────
# FUSÃO DOS METADADOS DE UM CAMPO ENTRE AS CATEGORIAS DO SKU
# ──────────────────────────────────────────────────────────────────────

def fundir_metadados_do_campo(attr_id: str, categorias_do_campo: list) -> dict:
    """
    A ficha é do SKU: o mesmo campo pode vir de mais de 1 categoria, e o
    valor escolhido pro SKU precisa ser válido em TODAS as categorias que
    pedem esse campo. Regras de fusão:
      - obrigatório   = qualquer categoria exigir;
      - lista fechada = interseção (por id) entre as categorias que têm
                        lista; categoria em que o campo é texto livre não
                        restringe;
      - texto livre   = tamanho máximo = o menor entre as categorias.
    Qualquer divergência relevante entre categorias vira uma linha em
    "avisos" — nada é resolvido em silêncio.
    """
    metas = {c: cache_card_por_categoria[c][attr_id] for c in categorias_do_campo}
    definicoes = {c: cache_definicoes_por_categoria[c].get(attr_id, {}) for c in categorias_do_campo}

    categorias_obrigatorias = [c for c in categorias_do_campo if metas[c]["required"]]
    entrada = {
        "label": metas[categorias_do_campo[0]]["label"],
        "obrigatorio": bool(categorias_obrigatorias),
        "categorias": categorias_do_campo,
    }
    avisos = []

    if categorias_obrigatorias and len(categorias_obrigatorias) < len(categorias_do_campo):
        entrada["obrigatorio_apenas_em"] = categorias_obrigatorias
        avisos.append(f"obrigatório só em {categorias_obrigatorias} (nas outras categorias do SKU é opcional).")

    opcoes_por_categoria = {c: (d.get("values") or []) for c, d in definicoes.items()}
    categorias_com_lista = [c for c, opcoes in opcoes_por_categoria.items() if opcoes]

    if categorias_com_lista:
        entrada["tipo_valor"] = "lista_fechada"

        if len(categorias_com_lista) < len(categorias_do_campo):
            sem_lista = [c for c in categorias_do_campo if c not in categorias_com_lista]
            avisos.append(f"lista fechada em {categorias_com_lista} e texto livre em {sem_lista}; "
                          f"a lista vale como restrição só nas categorias que têm lista.")

        conjuntos_de_ids = [
            frozenset(o.get("id") for o in opcoes_por_categoria[c]) for c in categorias_com_lista
        ]
        ids_comuns = set.intersection(*[set(conjunto) for conjunto in conjuntos_de_ids])
        primeira_lista = opcoes_por_categoria[categorias_com_lista[0]]
        opcoes_comuns = [
            {"id": o.get("id"), "nome": o.get("name")} for o in primeira_lista if o.get("id") in ids_comuns
        ]

        if len(set(conjuntos_de_ids)) > 1:
            avisos.append(f"as opções diferem entre as categorias; lista = interseção ({len(opcoes_comuns)} opção(ões) em comum).")
        if not opcoes_comuns:
            avisos.append("ATENÇÃO: nenhuma opção em comum entre as categorias — nenhum valor da lista serve pra todas.")

        if len(opcoes_comuns) <= LIMITE_OPCOES_LISTA:
            entrada["opcoes_validas"] = opcoes_comuns
        else:
            entrada["opcoes_validas"] = None
            avisos.append(f"{len(opcoes_comuns)} opções em comum — lista grande demais, não incluída aqui.")
    else:
        entrada["tipo_valor"] = "texto_livre"
        tamanhos = {c: d.get("value_max_length") for c, d in definicoes.items() if d.get("value_max_length")}
        if tamanhos:
            entrada["tamanho_maximo"] = min(tamanhos.values())
            if len(set(tamanhos.values())) > 1:
                avisos.append(f"tamanho máximo difere entre categorias ({tamanhos}); usando o menor.")

    if avisos:
        entrada["avisos"] = avisos
    return entrada


def montar_alertas(sku: str, status_banco, dados: dict) -> list:
    """
    Compara o que o banco acha desse MLB com o que o ML devolveu agora.
    Motivo: MLB "pai" com variações pode pertencer a mais de 1 SKU, e o
    banco agrupa por SKU — então o grupo pode estar engolindo variações
    de outro SKU (ou um anúncio pode estar com SKU de outro tamanho).
    """
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


def montar_contexto_de_1_sku(sku: str):
    """Roda o fluxo inteiro pra 1 SKU e devolve o dict pronto pra virar .json (ou None se não deu pra processar)."""

    variacoes_por_sku = carregar_variacoes_por_sku(skus=[sku])
    variacoes = variacoes_por_sku.get(sku, [])

    if not variacoes:
        console.print(f"  [red]Nenhuma variação encontrada no banco pro SKU '{sku}' — pulando.[/red]")
        return None

    produto = variacoes[0].produto
    if produto is None:
        console.print(f"  [yellow]SKU '{sku}' sem Produto conectado no ERP — título/descrição/marca ficarão vazios.[/yellow]")

    variacoes_por_mlb = defaultdict(list)
    for v in variacoes:
        variacoes_por_mlb[v.anuncio.mlb].append(v)

    mlbs_catalogo = []
    mlbs_inativos = []
    mlbs_sem_tipo = []
    mlbs_a_processar = []
    titulo_anuncio_por_mlb = {}
    status_banco_por_mlb = {}

    for mlb, vars_do_mlb in variacoes_por_mlb.items():
        anuncio = vars_do_mlb[0].anuncio
        titulo_anuncio_por_mlb[mlb] = anuncio.titulo_anuncio
        tipo = anuncio.tipo_de_anuncio
        status_banco_por_mlb[mlb] = tipo.status if tipo else None
        if tipo is None:
            mlbs_sem_tipo.append(mlb)
            mlbs_a_processar.append(mlb)
            continue
        if tipo.classificacao_catalogo == Classificacao.CATALOGO:
            mlbs_catalogo.append(mlb)
            continue
        if tipo.status not in STATUS_ACEITOS:
            mlbs_inativos.append({"mlb": mlb, "status": tipo.status})
            continue
        mlbs_a_processar.append(mlb)

    console.print(f"  {len(variacoes_por_mlb)} MLB(s) no banco — "
                  f"{len(mlbs_catalogo)} ignorado(s) por catálogo, "
                  f"{len(mlbs_inativos)} ignorado(s) por status fora de {sorted(STATUS_ACEITOS)}, "
                  f"{len(mlbs_a_processar)} a processar.")
    if mlbs_sem_tipo:
        console.print(f"  [yellow]Sem tipo_de_anuncio (não ignorados): {mlbs_sem_tipo}[/yellow]")

    if not mlbs_a_processar:
        console.print("  [red]Nenhum MLB sobrou depois dos filtros (catálogo/status) — nada pra montar.[/red]")
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
    categorias_do_sku = []

    for mlb, dados in dados_por_mlb.items():
        category_id = dados["category_id"]
        if category_id not in cache_card_por_categoria:
            console.print(f"  Categoria nova: {category_id} — buscando card + catálogo de atributos...")
            cache_card_por_categoria[category_id] = buscar_card_caracteristicas_principais(category_id)
            cache_definicoes_por_categoria[category_id] = buscar_definicoes_de_atributos(category_id)

        if category_id not in categorias_do_sku:
            categorias_do_sku.append(category_id)

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
        alertas = montar_alertas(sku, status_banco_por_mlb.get(mlb), dados)
        anuncios.append({
            "mlb": mlb,
            "titulo": titulo_anuncio_por_mlb.get(mlb),
            "category_id": dados["category_id"],
            "status_banco": status_banco_por_mlb.get(mlb),
            "status_ml": dados["status_ml"],
            "sku_no_ml": dados["sku_no_ml"],
            "family_id": dados["family_id"],
            "family_name": dados["family_name"],
            "variacoes_no_ml": dados["variacoes"],
            "variacoes_no_banco": [
                {
                    "variacao_id": v.variacao_id,
                    "sku_ml": v.sku_ml,
                    "produto_sku": v.produto.sku if v.produto else None,
                    "atributos": v.atributos,
                }
                for v in variacoes_por_mlb[mlb]
            ],
            "alertas": alertas,
            "caracteristicas_atuais": caracteristicas_atuais,
        })

    total_com_alerta = sum(1 for a in anuncios if a["alertas"])
    if total_com_alerta:
        console.print(f"  [yellow]{total_com_alerta} MLB(s) com alerta:[/yellow]")
        for a in anuncios:
            for alerta in a["alertas"]:
                console.print(f"    [yellow]{a['mlb']}: {alerta}[/yellow]")

    caracteristicas = {}
    for attr_id in colunas_ordem:
        categorias_do_campo = [c for c in categorias_do_sku if attr_id in cache_card_por_categoria[c]]
        entrada = fundir_metadados_do_campo(attr_id, categorias_do_campo)

        mlbs_por_valor = defaultdict(list)
        for a in anuncios:
            if attr_id in a["caracteristicas_atuais"]:
                mlbs_por_valor[a["caracteristicas_atuais"][attr_id]].append(a["mlb"])

        entrada["mlbs_que_pedem_o_campo"] = sum(len(mlbs) for mlbs in mlbs_por_valor.values())
        entrada["valores_atuais"] = [
            {"valor": valor, "quantidade": len(mlbs), "mlbs": mlbs}
            for valor, mlbs in sorted(mlbs_por_valor.items(), key=lambda par: (-len(par[1]), str(par[0])))
        ]
        caracteristicas[attr_id] = entrada

    return {
        "sku": sku,
        "produto_erp": {
            "titulo": produto.titulo,
            "descricao": produto.descricao,
            "marca": getattr(produto, "marca", None),
        } if produto is not None else None,
        "mlbs_ignorados_catalogo": mlbs_catalogo,
        "mlbs_ignorados_inativos": mlbs_inativos,
        "mlbs_sem_tipo_de_anuncio": mlbs_sem_tipo,
        "categorias_do_sku": categorias_do_sku,
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