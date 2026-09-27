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
#
# Peça 4 da reforma estrutural (27/09/2026): a chamada à API e a
# extração de campos (extrair_sku, extrair_atributo, extrair_campos_pai,
# processar_item, etc.) saíram daqui e foram pra
# api_mercado_livre.detalhes_ml.DetalhesML (Contexto), por trás de
# ApiMercadoLivre (Facade). Este arquivo continua 100% dono do controle
# de lotes/progresso/retomada — nada disso mudou de comportamento, só de
# onde a chamada HTTP e a extração acontecem.

import json
import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE

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


# ─── MAIN ────────────────────────────────────────────────────────────────

def buscar_detalhes(empresa: str) -> dict:
    """
    Ponto único de entrada. Busca o detalhe completo de cada MLB da
    empresa informada (EMPRESA_MAGAZINE ou EMPRESA_SAMVALE), a partir do
    lista_mlbs.json gerado pelo ponto 02 (buscar_mlbs). Salva
    detalhes_mlbs.json isolado por empresa, e devolve um resumo da execução.
    """
    pasta_logs = _caminho_pasta_logs(empresa)
    api_ml = ApiMercadoLivre(pasta_logs=pasta_logs, empresa=empresa)

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
                    registros_lote, erros_lote_itens = api_ml.buscar_detalhes_lote(ids_str, meta_map)
                    qtd_erros_item = len(erros_lote_itens)
                    erros_itens.extend(erros_lote_itens)
                    for reg in registros_lote:
                        processados_ids.add(reg["mlb"])

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