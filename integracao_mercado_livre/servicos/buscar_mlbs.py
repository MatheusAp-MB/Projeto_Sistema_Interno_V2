# integracao_mercado_livre/servicos/buscar_mlbs.py
#
# Busca TODOS os MLBs de 1 empresa (Magazine ou Samvale) usando "get all"
# com paginação via scroll_id. 168 varridas cobrindo todas as combinações
# possíveis de status × logística × tipo × catálogo (6 × 7 × 2 × 2).
# Salva 1 lista_mlbs.json por empresa, isolado, dentro de
# integracao_mercado_livre/Arquivos_API/<Empresa>/.
#
# Migrado de APP_performance/buscar_mlbs.py (pasta separada, fora do repo).

import json
import os
import time
from pathlib import Path
from itertools import product

from dotenv import load_dotenv
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

STATUS_LIST = ["active", "paused", "closed", "under_review", "payment_required", "not_yet_active"]
LOGISTICA_LIST = ["fulfillment", "cross_docking", "xd_drop_off", "self_service", "not_specified", "drop_off", "custom"]
TIPO_LIST = ["gold_pro", "gold_special"]
CATALOGO_LIST = ["true", "false"]

# Agrupado por status — 6 grupos de 28 combinações cada (7 × 2 × 2), 168 no
# total. Cada grupo vira 1 bloco visual próprio no console (posições fixas,
# 1 linha por combinação), fechado antes do próximo abrir. Isso NÃO muda o
# ritmo real das chamadas — continua 1 de cada vez, em sequência estrita —
# só organiza o que é mostrado.
GRUPOS = {}
for status in STATUS_LIST:
    GRUPOS[status] = []
    for logistica, tipo, catalogo in product(LOGISTICA_LIST, TIPO_LIST, CATALOGO_LIST):
        GRUPOS[status].append({
            "status": status,
            "logistic_type": logistica,
            "listing_type_id": tipo,
            "catalog_listing": catalogo,
            "label": f"{logistica} | {tipo} | cat:{catalogo}",
        })

TOTAL_VARRIDAS = sum(len(grupo) for grupo in GRUPOS.values())


def _pasta_empresa(empresa: str) -> str:
    if empresa not in NOME_PASTA_POR_EMPRESA:
        raise ValueError(f'Empresa inválida: "{empresa}". Use {list(NOME_PASTA_POR_EMPRESA)}.')
    return NOME_PASTA_POR_EMPRESA[empresa]


def _caminho_saida_json(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'lista_mlbs.json'


def _caminho_pasta_logs(empresa: str) -> Path:
    return RAIZ_APP / 'logs' / _pasta_empresa(empresa)


def _obter_user_id(conta: str) -> str:
    # load_dotenv() redundante quando chamado via manage.py (settings.py já
    # carrega o .env no boot) — mantido mesmo assim, defensivo, caso esta
    # função seja importada/testada fora do ciclo normal do Django.
    load_dotenv()
    user_id = os.getenv(f"{conta}_USER_ID")
    if not user_id:
        raise RuntimeError(
            f'{conta}_USER_ID não encontrado no .env da raiz do repo — '
            f'adicione a linha {conta}_USER_ID=seu_user_id_aqui.'
        )
    return user_id


def buscar_mlbs_varrida(varrida: dict, conta: str, user_id: str, pasta_logs: Path) -> list[dict]:
    mlbs_encontrados = []
    scroll_id = None

    while True:
        params = {
            "search_type": "scan",
            "status": varrida["status"],
            "logistic_type": varrida["logistic_type"],
            "listing_type_id": varrida["listing_type_id"],
            "catalog_listing": varrida["catalog_listing"],
        }
        if scroll_id:
            params["scroll_id"] = scroll_id

        resposta = chamar_api(
            "GET", f"/users/{user_id}/items/search",
            pasta_logs=pasta_logs, conta=conta, params=params, nome_log="buscar_mlbs",
        )
        dados = resposta.json()
        resultados = dados.get("results", [])

        if not resultados:
            break

        for mlb in resultados:
            mlbs_encontrados.append({
                "mlb": mlb,
                "status": varrida["status"],
                "logistica": varrida["logistic_type"],
                "tipo": varrida["listing_type_id"],
                "catalogo": varrida["catalog_listing"],
            })

        scroll_id = dados.get("scroll_id")
        if not scroll_id:
            break

    return mlbs_encontrados


def buscar_mlbs(empresa: str) -> dict:
    """
    Ponto único de entrada. Busca todos os MLBs da empresa informada
    (EMPRESA_MAGAZINE ou EMPRESA_SAMVALE), salva lista_mlbs.json isolado
    por empresa, e devolve um resumo da execução.

    Exibição em blocos por status (28 combinações por bloco) — cada bloco
    fecha e fica no histórico do terminal antes do próximo abrir. O ritmo
    real das chamadas não muda: continua 1 de cada vez, em sequência.
    """
    conta = PREFIXO_ENV_POR_EMPRESA[empresa]
    user_id = _obter_user_id(conta)
    pasta_logs = _caminho_pasta_logs(empresa)

    todos_mlbs = []
    varridas_com_resultado = 0
    varridas_sem_resultado = 0
    varridas_com_erro = 0
    detalhe_varridas = []

    inicio_execucao = time.perf_counter()
    varridas_feitas = 0

    for status, varridas_do_grupo in GRUPOS.items():
        decorrido = time.perf_counter() - inicio_execucao
        console.print(
            f"\n[bold]GRUPO: {status}[/bold]  "
            f"({varridas_feitas}/{TOTAL_VARRIDAS} no total  •  "
            f"{len(todos_mlbs)} MLBs até agora  •  {decorrido:.0f}s decorridos)"
        )

        with Progress(
            SpinnerColumn(finished_text="[green]✓[/green]"),
            TextColumn("[cyan]{task.description:<40}"),
            BarColumn(),
            TextColumn("{task.fields[resultado]}"),
            TimeElapsedColumn(),
        ) as progress:

            tarefas = [
                (varrida, progress.add_task(varrida["label"], total=1, resultado="⏳ na fila", start=False))
                for varrida in varridas_do_grupo
            ]

            for varrida, task_id in tarefas:
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

                inicio_varrida = time.perf_counter()
                try:
                    mlbs_varrida = buscar_mlbs_varrida(varrida, conta, user_id, pasta_logs)
                    erro = None
                except (ErroAPI, ErroAutenticacaoAPI) as e:
                    mlbs_varrida = []
                    erro = e
                duracao_varrida = time.perf_counter() - inicio_varrida

                detalhe_varridas.append({
                    "label": f"{status} | {varrida['label']}",
                    "encontrados": len(mlbs_varrida),
                    "duracao_segundos": round(duracao_varrida, 2),
                    "erro": str(erro) if erro else None,
                })

                if erro:
                    varridas_com_erro += 1
                    progress.update(task_id, resultado="[red]✗ ERRO — ver .log[/red]")
                elif mlbs_varrida:
                    todos_mlbs.extend(mlbs_varrida)
                    varridas_com_resultado += 1
                    progress.update(task_id, resultado=f"{len(mlbs_varrida)} MLBs")
                else:
                    varridas_sem_resultado += 1
                    progress.update(task_id, resultado="sem resultado")

                progress.update(task_id, completed=1)
                varridas_feitas += 1

    duracao_total = time.perf_counter() - inicio_execucao

    caminho_json = _caminho_saida_json(empresa)
    caminho_json.parent.mkdir(parents=True, exist_ok=True)

    resumo = {
        "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        "empresa": empresa,
        "total": len(todos_mlbs),
        "varridas_total": TOTAL_VARRIDAS,
        "varridas_com_resultado": varridas_com_resultado,
        "varridas_sem_resultado": varridas_sem_resultado,
        "varridas_com_erro": varridas_com_erro,
        "duracao_total_segundos": round(duracao_total, 2),
        "detalhe_varridas": detalhe_varridas,
        "mlbs": todos_mlbs,
    }

    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    varridas_mais_lentas = sorted(detalhe_varridas, key=lambda v: v["duracao_segundos"], reverse=True)[:5]

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green] Total: {len(todos_mlbs)} MLBs")
    resumo_linha = f"Varridas com resultado: {varridas_com_resultado} / {TOTAL_VARRIDAS}"
    if varridas_com_erro:
        resumo_linha += f"  •  [red]{varridas_com_erro} com erro[/red]"
    console.print(resumo_linha)
    console.print(f"Tempo total: {duracao_total:.1f}s")
    console.print("5 varridas mais lentas:")
    for v in varridas_mais_lentas:
        console.print(f"  {v['duracao_segundos']:>6.2f}s — {v['label']} ({v['encontrados']} MLBs)")
    console.print(f"JSON: {caminho_json}")

    return resumo