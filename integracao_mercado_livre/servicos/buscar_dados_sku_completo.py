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
# Cache em memória por execução (por mlbu / por mlb), protegido por lock
# — nunca repete chamada pro mesmo par, ainda que o MLB apareça no fecho
# de mais de 1 SKU (cache cross-SKU, ver Etapa 4 abaixo).
#
# Peça 4 da reforma estrutural (27/09/2026): as 2 chamadas à API saíram
# daqui e foram pra api_mercado_livre.dados_sku_completo_ml.
# DadosSkuCompletoML (Contexto), por trás de ApiMercadoLivre (Facade).
# O cache por execução (cache_perf/cache_ptw) continua 100% aqui — é
# controle de "evitar chamada repetida nesse run", não conhecimento de
# API. Nada disso mudou de comportamento, só de onde a chamada HTTP
# acontece.
#
# Etapa 4 (29/09/2026): 1ª rodada de paralelismo — ThreadPoolExecutor(20)
# por SKU, cache cross-SKU com lock, dataclasses (ResultadoSku/
# RelatorioBuscaDadosSkuCompleto). Validado em produção: 1682/1682 SKUs,
# 0 erro, 869,3s. MAS o throughput real medido (~8,9 MLBs/s) ficou bem
# abaixo do teto já comprovado a 20 threads com pool de conexão (~107
# req/s, seção 15 do checkpoint) — a causa identificada foi o desenho de
# "grupo = 20 SKUs, 1 thread por SKU": o fecho transitivo de cada SKU
# tem tamanho variável (~3,6 MLBs em média, mas com outliers), e como
# o loop de MLBs DENTRO de 1 SKU era sequencial, 1 SKU com fecho grande
# segurava o grupo inteiro (os outros ~19 workers ociosos esperando ele).
#
# Refinamento da Etapa 4 (30/09/2026) — reestruturado em 3 fases
# explícitas, discutido e desenhado junto com Matheus:
#
#   FASE 1 (descoberta) — calcula o fecho transitivo de TODOS os SKUs
#   pendentes de uma vez, antes de qualquer chamada de API. Puramente
#   local (lê só todos_registros, já em memória), barato.
#
#   FASE 2 (empacotamento) — agrupa SKUs INTEIROS (nunca corta 1 SKU no
#   meio) em grupos, somando o tamanho do fecho de cada um até bater
#   ~META_MLBS_POR_GRUPO. Troca "20 SKUs por grupo" (desbalanceado) por
#   "~20 MLBs por grupo" (balanceado) — resolve a barreira da Etapa 4.
#
#   FASE 3 (execução) — pra cada grupo, achata os SKUs em itens de
#   trabalho por MLB (não por SKU) e dispara TODOS no mesmo
#   ThreadPoolExecutor(20) — isso dá paralelismo de verdade dentro de 1
#   SKU também (os MLBs de um SKU competem pelos workers junto com os
#   MLBs de todo mundo no grupo), sem precisar de pool aninhado. Um
#   contador de "MLBs pendentes" por SKU (só a thread principal mexe
#   nele) decide quando um SKU está pronto pra fechar (bloco montado,
#   checkpoint gravado, linha do rich.Progress concluída).
#
#   Nota de auditoria: com o disparo achatado, se 1 MLB de um SKU der
#   erro, os outros MLBs desse MESMO SKU que já tinham sido disparados
#   em paralelo continuam rodando até o fim (não dá pra cancelar uma
#   task já em andamento no ThreadPoolExecutor) — o resultado deles é só
#   descartado, já que o SKU já fechou como erro. Antes (Etapa 4), o
#   loop sequencial parava no 1º erro (fail-fast). Na prática isso é
#   inalcançável hoje: DadosSkuCompletoML.buscar_performance/
#   buscar_price_to_win já capturam ErroAPI/ErroAutenticacaoAPI
#   internamente e nunca deixam propagar (confirmado com dado real —
#   53,2% de 404 em /performance na rodada de produção, 0 SKUs com
#   erro). O try/except aqui fica por defesa/consistência com o resto
#   do pipeline, não porque dispara na prática.

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa, obter_empresa_ativa
from mercado_livre.funcoes_auxiliares.classificacao_catalogo import (
    classificar_catalogo, encontrar_fecho_transitivo,
)

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

MAX_WORKERS_DADOS_SKU_COMPLETO = 20
# Meta de MLBs por grupo (Fase 2) — mantido igual a MAX_WORKERS de propósito:
# cada grupo vira, na prática, ~1 leva cheia de trabalho pros workers
# disponíveis. Testar os 2 valores juntos (ex: subir ambos pra 30/50,
# dentro do teto já validado na seção 15) é o próximo passo natural,
# mas não misturado com esta mudança estrutural.
META_MLBS_POR_GRUPO = MAX_WORKERS_DADOS_SKU_COMPLETO


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


# ─── FASE 2 — EMPACOTAMENTO ────────────────────────────────────────────

def _empacotar_por_mlbs(pendentes: list, fechos: dict, meta_mlbs: int) -> list:
    """
    Agrupa SKUs INTEIROS (nunca corta 1 SKU no meio) na ordem de
    `pendentes`, somando len(fecho) até a soma do grupo atingir/passar
    meta_mlbs — então fecha o grupo e começa outro. `fechos` é
    {sku: [mlbs...]}, já calculado na Fase 1. Retorna list[list[sku]].
    Um único SKU com fecho > meta_mlbs vira sozinho um grupo maior que a
    meta (raro, dado fecho médio de ~3,6 MLBs) — sem problema, o disparo
    dentro do grupo é por MLB, então esse SKU já ganha paralelismo
    interno mesmo sozinho no grupo.
    """
    grupos = []
    grupo_atual = []
    soma_atual = 0
    for sku in pendentes:
        grupo_atual.append(sku)
        soma_atual += len(fechos[sku])
        if soma_atual >= meta_mlbs:
            grupos.append(grupo_atual)
            grupo_atual = []
            soma_atual = 0
    if grupo_atual:
        grupos.append(grupo_atual)
    return grupos


# ─── CHAMADAS À API, COM CACHE POR EXECUÇÃO (cross-SKU, com lock) ─────

def _pacote_nao_chamado():
    from api_mercado_livre.dados_sku_completo_ml import PacoteApi
    return PacoteApi(chamado=False, http=None, erro=None, dados=None)


def _chamar_performance(mlbu, api_ml, cache, lock):
    with lock:
        if mlbu in cache:
            return cache[mlbu]
    pacote = api_ml.buscar_performance(mlbu)
    with lock:
        cache.setdefault(mlbu, pacote)
        return cache[mlbu]


def _chamar_price_to_win(mlb, api_ml, cache, lock):
    with lock:
        if mlb in cache:
            return cache[mlb]
    pacote = api_ml.buscar_price_to_win(mlb)
    with lock:
        cache.setdefault(mlb, pacote)
        return cache[mlb]


def _montar_mlb(registro, api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw) -> dict:
    from dataclasses import asdict

    mlb = registro["mlb"]
    mlbu = registro.get("user_product_id")
    classificacao = classificar_catalogo(registro)

    performance = _chamar_performance(mlbu, api_ml, cache_perf, lock_perf) if mlbu else _pacote_nao_chamado()
    price_to_win = (
        _chamar_price_to_win(mlb, api_ml, cache_ptw, lock_ptw)
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
        "performance": asdict(performance),
        "price_to_win": asdict(price_to_win),
    }


# ─── FASE 3 — trabalho no nível de MLB (não mais de SKU) ──────────────

@dataclass
class ResultadoMlb:
    sku: str
    mlb_pronto: dict | None = None
    duracao_segundos: float = 0.0
    erro: str | None = None


def _processar_mlb(empresa_ativa, sku, mlb, registros_idx, api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw) -> ResultadoMlb:
    definir_empresa_ativa(empresa_ativa)
    inicio = time.perf_counter()
    try:
        mlb_pronto = _montar_mlb(registros_idx[mlb], api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw)
        return ResultadoMlb(sku=sku, mlb_pronto=mlb_pronto, duracao_segundos=time.perf_counter() - inicio)
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        return ResultadoMlb(sku=sku, mlb_pronto=None, duracao_segundos=time.perf_counter() - inicio, erro=str(e))


@dataclass
class ResultadoSku:
    sku: str
    bloco: dict | None = None
    duracao_segundos: float = 0.0
    erro: str | None = None


@dataclass
class RelatorioBuscaDadosSkuCompleto:
    empresa: str
    gerado_em: str = ""
    total_skus_no_arquivo: int = 0
    skus_processados_nesta_execucao: int = 0
    skus_pendentes_no_inicio: int = 0
    skus_com_erro: int = 0
    total_mlbs_processados: int = 0
    total_grupos: int = 0
    duracao_fase1_descoberta_segundos: float = 0.0
    duracao_fase2_empacotamento_segundos: float = 0.0
    duracao_fase3_execucao_segundos: float = 0.0
    duracao_total_segundos: float = 0.0
    detalhe_skus: list = field(default_factory=list)
    erros_skus: list = field(default_factory=list)
    skus: list = field(default_factory=list)


# ─── MAIN ────────────────────────────────────────────────────────────

def buscar_dados_sku_completo(empresa: str, skus: list | None = None) -> RelatorioBuscaDadosSkuCompleto:
    """
    skus=None  -> modo produção: todos os SKUs distintos, com checkpoint.
    skus=[...] -> modo teste: só os SKUs informados, sem checkpoint, faz
                  merge com o dados_completos_por_sku.json existente.

    3 fases (ver comentário no topo do arquivo): descoberta (fecho de
    todo mundo) -> empacotamento (grupos de ~META_MLBS_POR_GRUPO) ->
    execução (paralelo, achatado por MLB, grupo a grupo).
    """
    empresa_ativa = obter_empresa_ativa()
    pasta_logs = _caminho_pasta_logs(empresa)
    api_ml = ApiMercadoLivre(pasta_logs=pasta_logs, empresa=empresa)

    todos_registros = _carregar_registros(empresa)
    registros_idx = {r["mlb"]: r for r in todos_registros}

    cache_perf = {}
    cache_ptw = {}
    lock_perf = threading.Lock()
    lock_ptw = threading.Lock()
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

    inicio_execucao = time.perf_counter()

    # ─── FASE 1/3 — descoberta ─────────────────────────────────────
    console.print("[bold]Fase 1/3[/bold] — descobrindo MLBs de cada SKU pendente (fecho transitivo)...")
    inicio_fase1 = time.perf_counter()
    fechos = {sku: sorted(encontrar_fecho_transitivo(sku, todos_registros)) for sku in pendentes}
    duracao_fase1 = time.perf_counter() - inicio_fase1
    total_mlbs_a_processar = sum(len(f) for f in fechos.values())
    console.print(
        f"Fase 1 concluída em {duracao_fase1:.2f}s — {total_mlbs_a_processar} MLBs "
        f"encontrados em {len(pendentes)} SKUs pendentes.\n"
    )

    # ─── FASE 2/3 — empacotamento ──────────────────────────────────
    console.print(f"[bold]Fase 2/3[/bold] — agrupando SKUs em blocos de ~{META_MLBS_POR_GRUPO} MLBs...")
    inicio_fase2 = time.perf_counter()
    grupos = _empacotar_por_mlbs(pendentes, fechos, META_MLBS_POR_GRUPO)
    duracao_fase2 = time.perf_counter() - inicio_fase2
    if grupos:
        tamanhos_grupos_mlbs = [sum(len(fechos[s]) for s in g) for g in grupos]
        tamanhos_grupos_skus = [len(g) for g in grupos]
        console.print(
            f"Fase 2 concluída em {duracao_fase2:.3f}s — {len(grupos)} grupos formados "
            f"(MLBs/grupo: mín {min(tamanhos_grupos_mlbs)}, média {sum(tamanhos_grupos_mlbs)/len(grupos):.1f}, "
            f"máx {max(tamanhos_grupos_mlbs)}  •  SKUs/grupo: mín {min(tamanhos_grupos_skus)}, "
            f"média {sum(tamanhos_grupos_skus)/len(grupos):.1f}, máx {max(tamanhos_grupos_skus)}).\n"
        )
    else:
        console.print("Fase 2 concluída — nada pendente.\n")

    # ─── FASE 3/3 — execução paralela, grupo a grupo ───────────────
    blocos = dict(blocos_prontos)
    erros_skus = []
    detalhe_skus = []
    erros_skus_processados = set()

    inicio_fase3 = time.perf_counter()
    mlbs_feitos = 0
    skus_feitos = 0

    if grupos:
        console.print(f"[bold]Fase 3/3[/bold] — execução paralela ({MAX_WORKERS_DADOS_SKU_COMPLETO} workers)\n")

    with Progress(
        SpinnerColumn(finished_text="[green]✓[/green]"),
        TextColumn("[cyan]{task.description:<30}"),
        BarColumn(),
        TextColumn("{task.fields[resultado]}"),
        TimeElapsedColumn(),
    ) as progress:

        for indice_grupo, grupo in enumerate(grupos, start=1):
            inicio_grupo = time.perf_counter()
            soma_mlbs_grupo = sum(len(fechos[s]) for s in grupo)
            decorrido = time.perf_counter() - inicio_execucao
            sku_inicial = skus_feitos + 1
            sku_final = skus_feitos + len(grupo)
            console.print(
                f"[bold]GRUPO {indice_grupo}/{len(grupos)}[/bold]  "
                f"(SKUs {sku_inicial}-{sku_final} de {len(pendentes)}, {len(grupo)} SKUs, {soma_mlbs_grupo} MLBs)  "
                f"•  {len(blocos)} SKUs prontos até agora  •  {decorrido:.0f}s decorridos"
            )

            tarefas_sku = {}
            mlbs_pendentes_por_sku = {}
            mlbs_prontos_por_sku = {}
            inicio_sku_por_sku = {}

            for i, sku in enumerate(grupo):
                indice_absoluto = skus_feitos + i + 1
                task_id = progress.add_task(
                    f"[{indice_absoluto}/{len(pendentes)}] {sku[:22]}", total=1, resultado="⏳ na fila", start=False
                )
                tarefas_sku[sku] = task_id
                mlbs_pendentes_por_sku[sku] = len(fechos[sku])
                mlbs_prontos_por_sku[sku] = []
                inicio_sku_por_sku[sku] = time.perf_counter()

            for task_id in tarefas_sku.values():
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

            def _fechar_sku_sucesso(sku: str):
                nonlocal skus_feitos
                task_id = tarefas_sku[sku]
                duracao_sku = time.perf_counter() - inicio_sku_por_sku[sku]
                mlbs_saida = sorted(mlbs_prontos_por_sku[sku], key=lambda r: r["mlb"])
                bloco = {"sku": sku, "total_mlbs": len(mlbs_saida), "mlbs": mlbs_saida}

                detalhe_skus.append(ResultadoSku(sku=sku, bloco=bloco, duracao_segundos=round(duracao_sku, 2)))
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

            def _fechar_sku_com_erro(sku: str, mensagem_erro: str):
                nonlocal skus_feitos
                task_id = tarefas_sku[sku]
                duracao_sku = time.perf_counter() - inicio_sku_por_sku[sku]

                erros_skus.append({"sku": sku, "erro": mensagem_erro})
                detalhe_skus.append(ResultadoSku(sku=sku, duracao_segundos=round(duracao_sku, 2), erro=mensagem_erro))
                progress.update(task_id, resultado="[red]✗ ERRO — ver .log[/red]")
                progress.update(task_id, completed=1)
                skus_feitos += 1
                # Erro nunca vai pro checkpoint — SKU continua "pendente" numa
                # próxima retomada, mesmo critério de antes.

            # SKUs com fecho vazio (raro) não geram nenhum item de trabalho —
            # fecham de cara, sem esperar nenhuma chamada de API.
            for sku in grupo:
                if mlbs_pendentes_por_sku[sku] == 0:
                    _fechar_sku_sucesso(sku)

            itens_trabalho = [(sku, mlb) for sku in grupo for mlb in fechos[sku]]

            if itens_trabalho:
                with ThreadPoolExecutor(max_workers=MAX_WORKERS_DADOS_SKU_COMPLETO) as executor:
                    futuros = [
                        executor.submit(
                            _processar_mlb, empresa_ativa, sku, mlb, registros_idx,
                            api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw,
                        )
                        for sku, mlb in itens_trabalho
                    ]
                    for futuro in as_completed(futuros):
                        resultado = futuro.result()
                        sku = resultado.sku
                        mlbs_feitos += 1

                        if sku in erros_skus_processados:
                            continue  # SKU já fechado com erro — resultado tardio, descarta

                        if resultado.erro:
                            erros_skus_processados.add(sku)
                            _fechar_sku_com_erro(sku, resultado.erro)
                            continue

                        mlbs_prontos_por_sku[sku].append(resultado.mlb_pronto)
                        mlbs_pendentes_por_sku[sku] -= 1
                        if mlbs_pendentes_por_sku[sku] == 0:
                            _fechar_sku_sucesso(sku)

            duracao_grupo = time.perf_counter() - inicio_grupo
            vazao_grupo = soma_mlbs_grupo / duracao_grupo if duracao_grupo > 0 else 0.0
            console.print(
                f"  └─ grupo concluído em {duracao_grupo:.2f}s  •  {vazao_grupo:.1f} MLBs/s  •  "
                f"{mlbs_feitos} MLBs prontos até agora\n"
            )

    duracao_fase3 = time.perf_counter() - inicio_fase3
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

    skus_mais_lentos = sorted(detalhe_skus, key=lambda s: s.duracao_segundos, reverse=True)[:5]

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green] SKUs no arquivo final: {len(blocos_final)}")
    resumo_linha = f"SKUs processados nesta execução: {skus_feitos}/{len(pendentes)}"
    if erros_skus:
        resumo_linha += f"  •  [red]{len(erros_skus)} SKUs c/ erro[/red]"
    console.print(resumo_linha)
    console.print(
        f"Tempo total: {duracao_total:.1f}s  "
        f"(Fase 1 descoberta: {duracao_fase1:.2f}s  •  "
        f"Fase 2 empacotamento: {duracao_fase2:.3f}s  •  "
        f"Fase 3 execução paralela: {duracao_fase3:.1f}s)"
    )
    vazao_geral = mlbs_feitos / duracao_fase3 if duracao_fase3 > 0 else 0.0
    console.print(
        f"Vazão média na Fase 3: {vazao_geral:.1f} MLBs/s "
        f"({MAX_WORKERS_DADOS_SKU_COMPLETO} workers, grupos de ~{META_MLBS_POR_GRUPO} MLBs, {len(grupos)} grupos)"
    )
    if skus_mais_lentos:
        console.print("5 SKUs mais lentos:")
        for s in skus_mais_lentos:
            console.print(f"  {s.duracao_segundos:>6.2f}s — {s.sku}")
    console.print(f"JSON: {caminho_json}")

    return RelatorioBuscaDadosSkuCompleto(
        empresa=empresa,
        gerado_em=resultado_final["gerado_em"],
        total_skus_no_arquivo=len(blocos_final),
        skus_processados_nesta_execucao=skus_feitos,
        skus_pendentes_no_inicio=len(pendentes),
        skus_com_erro=len(erros_skus),
        total_mlbs_processados=mlbs_feitos,
        total_grupos=len(grupos),
        duracao_fase1_descoberta_segundos=round(duracao_fase1, 3),
        duracao_fase2_empacotamento_segundos=round(duracao_fase2, 3),
        duracao_fase3_execucao_segundos=round(duracao_fase3, 2),
        duracao_total_segundos=round(duracao_total, 2),
        detalhe_skus=detalhe_skus,
        erros_skus=erros_skus,
        skus=resultado_final["skus"],
    )