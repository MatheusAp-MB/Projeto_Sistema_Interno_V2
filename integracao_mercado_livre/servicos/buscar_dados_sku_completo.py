# integracao_mercado_livre/servicos/buscar_dados_sku_completo.py
#
# Ponto 05 (último do plano). Pra cada SKU, encontra todos os MLBs
# relacionados (fecho transitivo, migrado pra
# mercado_livre/funcoes_auxiliares/classificacao_catalogo.py —
# encontrar_fecho_transitivo), classifica cada um (classificar_catalogo,
# unificado no ponto 04) e busca:
#
#   - /user-product/{MLBU}/performance  -> todo MLB que tiver mlbu
#   - /items/{MLB}/price_to_win         -> só os classificados "catalogo"
#
# Lê detalhes_mlbs.json (saída do ponto 03) — inclusive user_product_id
# (mlbu), já extraído lá desde a migração de buscar_detalhes.
#
# 2 modos, espelhando o script original:
#   - Produção (skus=None): todos os SKUs distintos da base, com
#     checkpoint/retomada em dados_completos_progresso.json (só apaga se
#     terminar sem erro, mesmo critério do ponto 03).
#   - Teste pontual (skus=[...]): só os SKUs informados, sem checkpoint —
#     faz merge com o dados_completos_por_sku.json existente em vez de
#     sobrescrever (correção sobre o script original, que sobrescrevia
#     silenciosamente).
#
# Cache em memória por execução (por mlbu / por mlb) — nunca repete
# chamada pro mesmo par, ainda que o MLB apareça no fecho de mais de 1 SKU.

import json
import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, PREFIXO_ENV_POR_EMPRESA
from mercado_livre.funcoes_auxiliares.classificacao_catalogo import (
    classificar_catalogo, encontrar_fecho_transitivo,
)

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

TAMANHO_GRUPO_EXIBICAO = 20  # quantos SKUs por bloco visual no console


def _pasta_empresa(empresa: str) -> str:
    if empresa not in NOME_PASTA_POR_EMPRESA:
        raise ValueError(f'Empresa inválida: "{empresa}". Use {list(NOME_PASTA_POR_EMPRESA)}.')
    return NOME_PASTA_POR_EMPRESA[empresa]


def _caminho_detalhes_mlbs(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'detalhes_mlbs.json'


def _caminho_saida_json(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'dados_completos_por_sku.json'


def _caminho_progresso(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'dados_completos_progresso.json'


def _caminho_pasta_logs(empresa: str) -> Path:
    return RAIZ_APP / 'logs' / _pasta_empresa(empresa)


def _carregar_registros(empresa: str) -> list:
    caminho = _caminho_detalhes_mlbs(empresa)
    if not caminho.exists():
        nome_arg = 'magazine' if empresa == EMPRESA_MAGAZINE else 'samvale'
        raise RuntimeError(
            f'{caminho} não encontrado — rode "manage.py buscar_detalhes '
            f'--empresa {nome_arg}" primeiro (ponto 03).'
        )
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)["registros"]


def _listar_todos_os_skus(registros: list) -> list:
    return sorted({r["sku"] for r in registros if r.get("sku")})


# ─── CHAMADAS À API, COM CACHE POR EXECUÇÃO ──────────────────────────

def _pacote_nao_chamado() -> dict:
    return {"chamado": False, "http": None, "erro": None, "dados": None}


def _chamar_performance(mlbu, conta, pasta_logs, cache) -> dict:
    if mlbu in cache:
        return cache[mlbu]
    try:
        r = chamar_api(
            "GET", f"/user-product/{mlbu}/performance",
            pasta_logs=pasta_logs, conta=conta, nome_log="buscar_dados_sku_completo",
        )
        pacote = {"chamado": True, "http": r.status_code, "erro": None, "dados": r.json()}
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        pacote = {"chamado": True, "http": None, "erro": str(e), "dados": None}
    cache[mlbu] = pacote
    return pacote


def _chamar_price_to_win(mlb, conta, pasta_logs, cache) -> dict:
    if mlb in cache:
        return cache[mlb]
    try:
        r = chamar_api(
            "GET", f"/items/{mlb}/price_to_win",
            pasta_logs=pasta_logs, conta=conta, params={"version": "v2"},
            nome_log="buscar_dados_sku_completo",
        )
        pacote = {"chamado": True, "http": r.status_code, "erro": None, "dados": r.json()}
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        pacote = {"chamado": True, "http": None, "erro": str(e), "dados": None}
    cache[mlb] = pacote
    return pacote


def _montar_mlb(registro, conta, pasta_logs, cache_perf, cache_ptw) -> dict:
    mlb = registro["mlb"]
    mlbu = registro.get("user_product_id")
    classificacao = classificar_catalogo(registro)

    performance = _chamar_performance(mlbu, conta, pasta_logs, cache_perf) if mlbu else _pacote_nao_chamado()
    price_to_win = (
        _chamar_price_to_win(mlb, conta, pasta_logs, cache_ptw)
        if classificacao == 'catalogo' else _pacote_nao_chamado()
    )

    return {
        "mlb": mlb,
        "mlbu": mlbu,
        "classificacao": classificacao,
        "catalog_product_id": registro.get("catalog_product_id"),
        "catalog_listing": registro.get("catalog_listing"),
        "status": registro.get("status"),
        "title": registro.get("title"),
        "thumbnail": registro.get("thumbnail"),
        "imagem_principal": registro.get("imagem_principal"),
        "listing_type_id": registro.get("listing_type_id"),
        "logistic_type": registro.get("logistic_type"),
        "flex": registro.get("flex"),
        "performance": performance,
        "price_to_win": price_to_win,
    }


def _montar_sku(sku, registros_idx, todos_registros, conta, pasta_logs, cache_perf, cache_ptw) -> dict:
    fecho = encontrar_fecho_transitivo(sku, todos_registros)
    if not fecho:
        return {"sku": sku, "total_mlbs": 0, "mlbs": []}
    mlbs_saida = [
        _montar_mlb(registros_idx[mlb], conta, pasta_logs, cache_perf, cache_ptw)
        for mlb in sorted(fecho)
    ]
    return {"sku": sku, "total_mlbs": len(mlbs_saida), "mlbs": mlbs_saida}


# ─── MAIN ────────────────────────────────────────────────────────────

def buscar_dados_sku_completo(empresa: str, skus: list | None = None) -> dict:
    """
    skus=None  -> modo produção: todos os SKUs distintos, com checkpoint.
    skus=[...] -> modo teste: só os SKUs informados, sem checkpoint, faz
                  merge com o dados_completos_por_sku.json existente.
    """
    conta = PREFIXO_ENV_POR_EMPRESA[empresa]
    pasta_logs = _caminho_pasta_logs(empresa)

    todos_registros = _carregar_registros(empresa)
    registros_idx = {r["mlb"]: r for r in todos_registros}

    cache_perf = {}
    cache_ptw = {}
    caminho_json = _caminho_saida_json(empresa)

    if skus is not None:
        console.print(f"SKUs a processar ({empresa}, modo teste): {len(skus)}")
        blocos_prontos = {}
        pendentes = skus
        caminho_progresso = None
    else:
        alvo_skus = _listar_todos_os_skus(todos_registros)
        console.print(f"SKUs a processar ({empresa}): {len(alvo_skus)}")

        caminho_progresso = _caminho_progresso(empresa)
        blocos_prontos = {}
        if caminho_progresso.exists():
            with open(caminho_progresso, encoding="utf-8") as f:
                progresso = json.load(f)
            blocos_prontos = {b["sku"]: b for b in progresso.get("blocos", [])}
            console.print(
                f"[yellow]Retomando progresso: {len(blocos_prontos)} SKUs já "
                f"processados numa execução anterior[/yellow]"
            )
        pendentes = [s for s in alvo_skus if s not in blocos_prontos]

    console.print(f"SKUs pendentes: {len(pendentes)}\n")

    blocos = dict(blocos_prontos)
    erros_skus = []
    detalhe_skus = []

    grupos = [
        pendentes[i:i + TAMANHO_GRUPO_EXIBICAO]
        for i in range(0, len(pendentes), TAMANHO_GRUPO_EXIBICAO)
    ]

    inicio_execucao = time.perf_counter()
    skus_feitos = 0

    for indice_grupo, grupo in enumerate(grupos, start=1):
        decorrido = time.perf_counter() - inicio_execucao
        sku_inicial = skus_feitos + 1
        sku_final = skus_feitos + len(grupo)
        console.print(
            f"\n[bold]GRUPO {indice_grupo}/{len(grupos)}[/bold]  (SKUs {sku_inicial}–{sku_final} de {len(pendentes)})  "
            f"•  {len(blocos)} SKUs prontos até agora  •  {decorrido:.0f}s decorridos"
        )

        with Progress(
            SpinnerColumn(finished_text="[green]✓[/green]"),
            TextColumn("[cyan]{task.description:<30}"),
            BarColumn(),
            TextColumn("{task.fields[resultado]}"),
            TimeElapsedColumn(),
        ) as progress:

            tarefas = []
            for i, sku in enumerate(grupo):
                indice_absoluto = skus_feitos + i + 1
                task_id = progress.add_task(
                    f"[{indice_absoluto}/{len(pendentes)}] {sku[:22]}", total=1, resultado="⏳ na fila", start=False
                )
                tarefas.append((indice_absoluto, sku, task_id))

            for indice_absoluto, sku, task_id in tarefas:
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

                inicio_sku = time.perf_counter()
                erro = None
                bloco = None

                try:
                    bloco = _montar_sku(sku, registros_idx, todos_registros, conta, pasta_logs, cache_perf, cache_ptw)
                except (ErroAPI, ErroAutenticacaoAPI) as e:
                    erro = e

                duracao_sku = time.perf_counter() - inicio_sku
                detalhe_skus.append({
                    "sku": sku, "duracao_segundos": round(duracao_sku, 2),
                    "erro": str(erro) if erro else None,
                })

                if erro:
                    erros_skus.append({"sku": sku, "erro": str(erro)})
                    progress.update(task_id, resultado="[red]✗ ERRO — ver .log[/red]")
                else:
                    blocos[sku] = bloco
                    progress.update(task_id, resultado=f"{bloco['total_mlbs']} MLBs")

                progress.update(task_id, completed=1)
                skus_feitos += 1

                if caminho_progresso is not None:
                    with open(caminho_progresso, "w", encoding="utf-8") as f:
                        json.dump({
                            "blocos": list(blocos.values()),
                            "atualizado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }, f, ensure_ascii=False)

    duracao_total = time.perf_counter() - inicio_execucao

    if skus is not None and caminho_json.exists():
        with open(caminho_json, encoding="utf-8") as f:
            anterior = json.load(f)
        blocos_final = {b["sku"]: b for b in anterior.get("skus", [])}
        blocos_final.update(blocos)
    else:
        blocos_final = blocos

    caminho_json.parent.mkdir(parents=True, exist_ok=True)
    resultado_final = {
        "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        "empresa": empresa,
        "skus": list(blocos_final.values()),
    }
    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(resultado_final, f, ensure_ascii=False, indent=2)

    if caminho_progresso is not None and caminho_progresso.exists() and not erros_skus:
        caminho_progresso.unlink()

    skus_mais_lentos = sorted(detalhe_skus, key=lambda s: s["duracao_segundos"], reverse=True)[:5]

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green] SKUs no arquivo final: {len(blocos_final)}")
    resumo_linha = f"SKUs processados nesta execução: {skus_feitos}/{len(pendentes)}"
    if erros_skus:
        resumo_linha += f"  •  [red]{len(erros_skus)} SKUs c/ erro[/red]"
    console.print(resumo_linha)
    console.print(f"Tempo total: {duracao_total:.1f}s")
    if skus_mais_lentos:
        console.print("5 SKUs mais lentos:")
        for s in skus_mais_lentos:
            console.print(f"  {s['duracao_segundos']:>6.2f}s — {s['sku']}")
    console.print(f"JSON: {caminho_json}")

    return resultado_final