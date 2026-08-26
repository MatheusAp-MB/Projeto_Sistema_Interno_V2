# integracao_mercado_livre/servicos/buscar_detalhes.py
#
# Busca o detalhe completo de cada MLB de 1 empresa via multiget
# (GET /items?ids=...), em lotes de 20. Lê lista_mlbs.json (saída do
# ponto 02, buscar_mlbs) e salva detalhes_mlbs.json, isolado por empresa,
# dentro de integracao_mercado_livre/Arquivos_API/<Empresa>/.
#
# Retomável: se a execução cair no meio, salva progresso a cada lote em
# detalhes_progresso.json. Só apaga esse arquivo no final se terminou sem
# nenhum erro (de lote ou de item) — se sobrou erro, o progresso fica e a
# próxima execução retoma automaticamente só o que falta (lista_mlbs.json
# menos o que já está em "processados").
#
# Console: mesmo padrão do ponto 02 (buscar_mlbs) — blocos rich.Progress
# fechados um de cada vez, nada fica "às cegas". Aqui não existe uma
# dimensão de negócio natural pra agrupar (como "status" em buscar_mlbs),
# então o agrupamento é por posição sequencial, blocos fixos de lotes.
#
# Migrado de APP_performance/buscar_detalhes.py (pasta separada, fora do
# repo). CSV removido de propósito — só JSON.

import json
import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, PREFIXO_ENV_POR_EMPRESA

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

TAMANHO_LOTE = 20            # quantos MLBs por chamada multiget (limite da API)
TAMANHO_GRUPO_EXIBICAO = 20  # quantos lotes por bloco visual no console


def _pasta_empresa(empresa: str) -> str:
    if empresa not in NOME_PASTA_POR_EMPRESA:
        raise ValueError(f'Empresa inválida: "{empresa}". Use {list(NOME_PASTA_POR_EMPRESA)}.')
    return NOME_PASTA_POR_EMPRESA[empresa]


def _caminho_lista_mlbs(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'lista_mlbs.json'


def _caminho_saida_json(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'detalhes_mlbs.json'


def _caminho_progresso(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'detalhes_progresso.json'


def _caminho_pasta_logs(empresa: str) -> Path:
    return RAIZ_APP / 'logs' / _pasta_empresa(empresa)


# ─── EXTRAÇÃO DE CAMPOS (idêntico ao script original — lógica não mudou) ───

def extrair_sku(body: dict) -> str | None:
    for attr in body.get("attributes", []):
        if attr.get("id") == "SELLER_SKU":
            return attr.get("value_name")
    return body.get("seller_custom_field")


def extrair_atributo(body: dict, attr_id: str) -> str | None:
    for attr in body.get("attributes", []):
        if attr.get("id") == attr_id:
            return attr.get("value_name")
    return None


def extrair_sku_variacao(var: dict) -> str | None:
    for attr in var.get("attributes", []):
        if attr.get("id") == "SELLER_SKU":
            return attr.get("value_name")
    return var.get("seller_custom_field")


def extrair_dimensoes(shipping: dict) -> dict:
    dims = shipping.get("dimensions") or {}
    if not isinstance(dims, dict):
        return {"shipping_dim_width": None, "shipping_dim_height": None,
                "shipping_dim_length": None, "shipping_dim_weight": None}
    return {
        "shipping_dim_width":  dims.get("width"),
        "shipping_dim_height": dims.get("height"),
        "shipping_dim_length": dims.get("length"),
        "shipping_dim_weight": dims.get("weight"),
    }


def extrair_campos_pai(body: dict, meta: dict) -> dict:
    shipping = body.get("shipping", {})
    shipping_tags = shipping.get("tags", [])

    def extrair_imagem_principal(body: dict) -> str | None:
        pictures = body.get("pictures", [])
        if not pictures:
            return None
        url = pictures[0].get("secure_url") or pictures[0].get("url")
        if not url:
            return None
        try:
            base, ext = url.rsplit(".", 1)
            base_sem_sufixo = base.rsplit("-", 1)[0]
            return f"{base_sem_sufixo}-F.{ext}"
        except Exception:
            return url

    return {
        "mlb":                  body.get("id"),
        "title":                body.get("title"),
        "thumbnail":            body.get("thumbnail"),
        "imagem_principal":     extrair_imagem_principal(body),
        "status":               body.get("status"),
        "sub_status":           json.dumps(body.get("sub_status", []), ensure_ascii=False),
        "condition":            body.get("condition"),

        "price":                body.get("price"),
        "base_price":           body.get("base_price"),
        "original_price":       body.get("original_price"),

        "available_quantity":   body.get("available_quantity"),
        "sold_quantity":        body.get("sold_quantity"),
        "initial_quantity":     body.get("initial_quantity"),

        "listing_type_id":      body.get("listing_type_id"),
        "catalog_listing":      body.get("catalog_listing"),
        "catalog_product_id":   body.get("catalog_product_id"),

        "logistic_type":        shipping.get("logistic_type"),
        "free_shipping":        shipping.get("free_shipping"),
        "flex":                 "self_service_in" in shipping_tags,
        "shipping_tags":        json.dumps(shipping_tags, ensure_ascii=False),
        **extrair_dimensoes(shipping),

        "sku":                  extrair_sku(body),
        "inventory_id":         body.get("inventory_id"),
        "user_product_id":      body.get("user_product_id"),

        "attr_seller_package_height": extrair_atributo(body, "SELLER_PACKAGE_HEIGHT"),
        "attr_seller_package_width":  extrair_atributo(body, "SELLER_PACKAGE_WIDTH"),
        "attr_seller_package_length": extrair_atributo(body, "SELLER_PACKAGE_LENGTH"),
        "attr_seller_package_weight": extrair_atributo(body, "SELLER_PACKAGE_WEIGHT"),
        "attr_dimensions":            extrair_atributo(body, "DIMENSIONS"),
        "attr_weight":                extrair_atributo(body, "WEIGHT"),

        "family_name":          body.get("family_name"),
        "family_id":            body.get("family_id"),

        "item_relations":       json.dumps(body.get("item_relations", []), ensure_ascii=False),
        "parent_item_id":       body.get("parent_item_id"),
        "differential_pricing": body.get("differential_pricing"),
        "deal_ids":             json.dumps(body.get("deal_ids", []), ensure_ascii=False),

        "category_id":          body.get("category_id"),
        "domain_id":            body.get("domain_id"),

        "tags":                 json.dumps(body.get("tags", []), ensure_ascii=False),

        "warranty":             body.get("warranty"),

        "date_created":         body.get("date_created"),
        "last_updated":         body.get("last_updated"),
        "start_time":           body.get("start_time"),
        "stop_time":            body.get("stop_time"),
        "end_time":             body.get("end_time"),
        "expiration_time":      body.get("expiration_time"),

        "permalink":            body.get("permalink"),

        "tem_variacoes":        len(body.get("variations", [])) > 0,
        "variacao_id":          None,
        "variacao_atributos":   None,
        "variacao_num_fotos":   None,

        "ga_status":            meta.get("status"),
        "ga_logistica":         meta.get("logistica"),
        "ga_tipo":              meta.get("tipo"),
        "ga_catalogo":          meta.get("catalogo"),
    }


def processar_item(body: dict, meta: dict) -> list[dict]:
    variacoes = body.get("variations", [])

    if not variacoes:
        return [extrair_campos_pai(body, meta)]

    registros = []
    campos_pai = extrair_campos_pai(body, meta)

    for var in variacoes:
        reg = campos_pai.copy()

        reg["available_quantity"] = var.get("available_quantity")
        reg["sold_quantity"]      = var.get("sold_quantity")
        reg["inventory_id"]       = var.get("inventory_id")
        reg["user_product_id"]    = var.get("user_product_id")
        reg["catalog_product_id"] = var.get("catalog_product_id") or campos_pai["catalog_product_id"]
        reg["item_relations"]     = json.dumps(var.get("item_relations", []), ensure_ascii=False)

        sku_var = extrair_sku_variacao(var)
        if sku_var:
            reg["sku"] = sku_var

        if var.get("price") is not None:
            reg["price"] = var.get("price")

        reg["variacao_id"] = var.get("id")
        reg["variacao_num_fotos"] = len(var.get("picture_ids", []))

        combinacoes = var.get("attribute_combinations", [])
        reg["variacao_atributos"] = " / ".join(
            c.get("value_name", "") for c in combinacoes if c.get("value_name")
        ) or None

        registros.append(reg)

    return registros


# ─── MAIN ────────────────────────────────────────────────────────────────

def buscar_detalhes(empresa: str) -> dict:
    """
    Ponto único de entrada. Busca o detalhe completo de cada MLB da
    empresa informada (EMPRESA_MAGAZINE ou EMPRESA_SAMVALE), a partir do
    lista_mlbs.json gerado pelo ponto 02 (buscar_mlbs). Salva
    detalhes_mlbs.json isolado por empresa, e devolve um resumo da execução.
    """
    conta = PREFIXO_ENV_POR_EMPRESA[empresa]
    pasta_logs = _caminho_pasta_logs(empresa)

    caminho_lista = _caminho_lista_mlbs(empresa)
    if not caminho_lista.exists():
        nome_arg = 'magazine' if empresa == EMPRESA_MAGAZINE else 'samvale'
        raise RuntimeError(
            f'{caminho_lista} não encontrado — rode "manage.py buscar_mlbs '
            f'--empresa {nome_arg}" primeiro (ponto 02).'
        )

    with open(caminho_lista, encoding="utf-8") as f:
        dados_lista = json.load(f)

    mlbs_lista = dados_lista.get("mlbs", [])
    total_geral = len(mlbs_lista)
    console.print(f"MLBs a processar ({empresa}): {total_geral}")

    # Retomada de progresso
    caminho_progresso = _caminho_progresso(empresa)
    processados_ids = set()
    todos_registros = []
    erros_itens = []

    if caminho_progresso.exists():
        with open(caminho_progresso, encoding="utf-8") as f:
            progresso = json.load(f)
            processados_ids = set(progresso.get("processados", []))
            todos_registros = progresso.get("registros", [])
            erros_itens = progresso.get("erros_itens", [])
        console.print(
            f"[yellow]Retomando progresso: {len(processados_ids)}/{total_geral} "
            f"MLBs já processados numa execução anterior[/yellow]"
        )

    meta_map = {m["mlb"]: m for m in mlbs_lista}
    mlbs_pendentes = [m for m in mlbs_lista if m["mlb"] not in processados_ids]

    lotes = [
        mlbs_pendentes[i:i + TAMANHO_LOTE]
        for i in range(0, len(mlbs_pendentes), TAMANHO_LOTE)
    ]
    total_lotes = len(lotes)
    console.print(f"Lotes pendentes: {total_lotes} (até {TAMANHO_LOTE} MLBs cada)\n")

    grupos = [
        lotes[i:i + TAMANHO_GRUPO_EXIBICAO]
        for i in range(0, total_lotes, TAMANHO_GRUPO_EXIBICAO)
    ]

    erros_lotes = []
    detalhe_lotes = []
    inicio_execucao = time.perf_counter()
    lotes_feitos = 0

    for indice_grupo, grupo in enumerate(grupos, start=1):
        decorrido = time.perf_counter() - inicio_execucao
        lote_inicial = lotes_feitos + 1
        lote_final = lotes_feitos + len(grupo)
        console.print(
            f"\n[bold]GRUPO {indice_grupo}/{len(grupos)}[/bold]  (lotes {lote_inicial}–{lote_final} de {total_lotes})  "
            f"•  {len(todos_registros)} registros até agora  •  {decorrido:.0f}s decorridos"
        )

        with Progress(
            SpinnerColumn(finished_text="[green]✓[/green]"),
            TextColumn("[cyan]{task.description:<20}"),
            BarColumn(),
            TextColumn("{task.fields[resultado]}"),
            TimeElapsedColumn(),
        ) as progress:

            tarefas = []
            for i, lote in enumerate(grupo):
                indice_absoluto = lotes_feitos + i + 1
                task_id = progress.add_task(
                    f"lote {indice_absoluto}/{total_lotes}", total=1, resultado="⏳ na fila", start=False
                )
                tarefas.append((indice_absoluto, lote, task_id))

            for indice_absoluto, lote, task_id in tarefas:
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

                ids_str = ",".join(m["mlb"] for m in lote)
                inicio_lote = time.perf_counter()
                registros_lote = []
                qtd_erros_item = 0
                erro = None

                try:
                    resposta = chamar_api(
                        "GET", "/items",
                        pasta_logs=pasta_logs, conta=conta, params={"ids": ids_str},
                        nome_log="buscar_detalhes",
                    )
                    resultados = resposta.json()

                    for item in resultados:
                        code = item.get("code", 0)
                        body = item.get("body", {})
                        mlb  = body.get("id") or ""

                        if code != 200:
                            erros_itens.append({"mlb": mlb, "code": code})
                            qtd_erros_item += 1
                            continue

                        meta = meta_map.get(mlb, {})
                        registros_lote.extend(processar_item(body, meta))
                        processados_ids.add(mlb)

                except (ErroAPI, ErroAutenticacaoAPI) as e:
                    erro = e

                duracao_lote = time.perf_counter() - inicio_lote

                detalhe_lotes.append({
                    "lote": indice_absoluto,
                    "tamanho": len(lote),
                    "registros_gerados": len(registros_lote),
                    "itens_com_erro": qtd_erros_item,
                    "duracao_segundos": round(duracao_lote, 2),
                    "erro": str(erro) if erro else None,
                })

                if erro:
                    erros_lotes.append({"lote": indice_absoluto, "erro": str(erro)})
                    progress.update(task_id, resultado="[red]✗ ERRO — ver .log[/red]")
                else:
                    todos_registros.extend(registros_lote)
                    texto_resultado = f"{len(registros_lote)} registros"
                    if qtd_erros_item:
                        texto_resultado += f" [yellow]({qtd_erros_item} c/ erro)[/yellow]"
                    progress.update(task_id, resultado=texto_resultado)

                progress.update(task_id, completed=1)
                lotes_feitos += 1

                # Salva progresso a cada lote — dado de API é caro, não
                # perder o que já foi buscado se cair no meio.
                with open(caminho_progresso, "w", encoding="utf-8") as f:
                    json.dump({
                        "processados": list(processados_ids),
                        "registros": todos_registros,
                        "erros_itens": erros_itens,
                        "atualizado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }, f, ensure_ascii=False)

    duracao_total = time.perf_counter() - inicio_execucao

    caminho_json = _caminho_saida_json(empresa)
    caminho_json.parent.mkdir(parents=True, exist_ok=True)

    resumo = {
        "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        "empresa": empresa,
        "total_registros": len(todos_registros),
        "total_mlbs_processados": len(processados_ids),
        "total_mlbs_na_lista": total_geral,
        "lotes_total": total_lotes,
        "lotes_com_erro": len(erros_lotes),
        "duracao_total_segundos": round(duracao_total, 2),
        "detalhe_lotes": detalhe_lotes,
        "erros_itens": erros_itens,
        "erros_lotes": erros_lotes,
        "registros": todos_registros,
    }

    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    # Só apaga o progresso se terminou tudo certo — se sobrou erro (de lote
    # ou de item), mantém, pra próxima execução retomar automaticamente só
    # o que falta (mlbs_pendentes já exclui quem está em "processados").
    if caminho_progresso.exists() and not erros_itens and not erros_lotes:
        caminho_progresso.unlink()

    lotes_mais_lentos = sorted(detalhe_lotes, key=lambda l: l["duracao_segundos"], reverse=True)[:5]

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green] Registros: {len(todos_registros)} (inclui variações)")
    resumo_linha = f"MLBs processados: {len(processados_ids)}/{total_geral}"
    if erros_itens:
        resumo_linha += f"  •  [yellow]{len(erros_itens)} itens c/ erro[/yellow]"
    if erros_lotes:
        resumo_linha += f"  •  [red]{len(erros_lotes)} lotes c/ erro[/red]"
    console.print(resumo_linha)
    console.print(f"Tempo total: {duracao_total:.1f}s")
    console.print("5 lotes mais lentos:")
    for l in lotes_mais_lentos:
        console.print(f"  {l['duracao_segundos']:>6.2f}s — lote {l['lote']} ({l['registros_gerados']} registros)")
    console.print(f"JSON: {caminho_json}")

    return resumo