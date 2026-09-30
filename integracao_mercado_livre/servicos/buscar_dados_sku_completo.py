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
#
# Peça 4 da reforma estrutural (27/09/2026): as 2 chamadas à API saíram
# daqui e foram pra api_mercado_livre.dados_sku_completo_ml.
# DadosSkuCompletoML (Contexto), por trás de ApiMercadoLivre (Facade).
# O cache por execução (cache_perf/cache_ptw) continua 100% aqui — é
# controle de "evitar chamada repetida nesse run", não conhecimento de
# API.
#
# Otimização e POO (29/09/2026 — Etapa 4 de "otimizar e paralelizar
# todas as etapas que envolvem integração com o ML" — domínio mais lento
# do pipeline até aqui, "pode levar 1h30+" em produção, nenhuma
# otimização aplicada ainda antes deste diff):
#   1. Paralelismo via ThreadPoolExecutor dentro de cada bloco de
#      exibição (até 20 SKUs concorrentes por bloco) — cada worker
#      processa 1 SKU inteiro (seu fecho transitivo inteiro, sequencial
#      dentro do próprio SKU). Mesma correção de threading.local().
#      MAX_WORKERS_DADOS_SKU_COMPLETO=20 extrapolado do teto já
#      confirmado nos outros domínios — não testado isoladamente pra
#      estes 2 endpoints específicos.
#   2. PARTICULARIDADE deste domínio: cache_perf/cache_ptw são
#      compartilhados entre SKUs DIFERENTES (o mesmo MLB pode aparecer
#      no fecho de mais de 1 SKU) — sob paralelismo isso deixa de ser
#      thread-safe por padrão. Protegido com 1 threading.Lock() por
#      cache, travando só a checagem/gravação (nunca a chamada de rede
#      em si — travar a chamada inteira serializaria tudo e anularia o
#      ganho do paralelismo). Na pior hipótese, 2 SKUs pedem o mesmo MLB
#      pela 1ª vez ao mesmo tempo e cada um faz sua própria chamada
#      (dado duplicado, não incorreto — GET idempotente); depois disso
#      o cache fica consistente pros dois. Decisão consciente: aceitar
#      essa corrida rara em vez de coordenação perfeita (mais
#      complexidade do que vale a pena aqui).
#   3. rich.Progress mantido 100% como estava — só o momento de
#      start_task muda (todas as tarefas do bloco juntas). Toda mutação
#      de Progress/estado compartilhado continua só na thread principal,
#      via as_completed.
#   4. Retorno trocado de dict solto pra @dataclass
#      (RelatorioBuscaDadosSkuCompleto/ResultadoSku) — mesmo padrão dos
#      outros domínios. O dict por MLB (_montar_mlb, ~12 campos) e o
#      dict por SKU (_montar_sku) CONTINUAM como dict solto — são
#      gravados direto em dados_completos_por_sku.json, lido por pelo
#      menos 2 arquivos reais (importar_qualidade_anuncio.py,
#      importar_competicao_catalogo.py). Os campos "performance"/
#      "price_to_win" de cada MLB agora vêm de PacoteApi (Contexto,
#      dados_sku_completo_ml.py) — convertidos de volta pra dict com
#      dataclasses.asdict() na montagem de cada registro, formato do
#      JSON final preservado byte a byte.
#   5. Sem Enum — classificar_catalogo() mora numa função compartilhada
#      fora deste arquivo (usada também em importar_anuncios_ml.py),
#      fora de escopo pra este diff.

import json
import time
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.dados_sku_completo_ml import PacoteApi
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

TAMANHO_GRUPO_EXIBICAO = 20  # quantos SKUs por bloco visual no console — também o
                              # tamanho do lote de paralelismo (ver nota de otimização
                              # 29/09/2026 no cabeçalho do arquivo)

# * [EXPLICAÇÃO] → throughput de GET /user-product/{mlbu}/performance e
#                  GET /items/{mlb}/price_to_win sob ThreadPoolExecutor NÃO foi
#                  testado isoladamente — aplicado por extrapolação (mesma conta, mesmo
#                  domínio de API do ML, mesmo teto de 20 já confirmado nos outros 3
#                  domínios) mais a margem de segurança do pool de conexão em
#                  chamar_api(). Se algum 429 aparecer de verdade, é sinal pra medir com
#                  dado real em vez de só reduzir no escuro.
MAX_WORKERS_DADOS_SKU_COMPLETO = 20


@dataclass
class ResultadoSku:
    """Resultado de 1 SKU processado (fecho transitivo inteiro) — objeto de
    processo/domínio, mesmo padrão de ResultadoLote/ResultadoVarrida. erro só é
    preenchido quando o SKU INTEIRO falhou — hoje nenhuma chamada individual (por MLB)
    é capturada à parte, um erro de API em qualquer MLB do fecho derruba o SKU inteiro
    sem resultado parcial, exatamente como no comportamento original."""
    sku: str
    bloco: dict | None = None
    duracao_segundos: float = 0.0
    erro: str | None = None


@dataclass
class RelatorioBuscaDadosSkuCompleto:
    """Relatório de 1 execução completa do orquestrador — devolvido no lugar do dict
    solto anterior, mesmo padrão de RelatorioBuscaMlbs/RelatorioBuscaDetalhes/
    RelatorioComissaoReal. `skus` é o mesmo conteúdo gravado em
    dados_completos_por_sku.json (lista de dicts, formato preservado)."""
    empresa: str
    gerado_em: str = ""
    total_skus_no_arquivo: int = 0
    skus_processados_nesta_execucao: int = 0
    skus_pendentes_no_inicio: int = 0
    skus_com_erro: int = 0
    duracao_total_segundos: float = 0.0
    detalhe_skus: list[ResultadoSku] = field(default_factory=list)
    erros_skus: list[dict] = field(default_factory=list)
    skus: list[dict] = field(default_factory=list)


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


# ─── CHAMADAS À API, COM CACHE POR EXECUÇÃO (thread-safe) ────────────

def _pacote_nao_chamado() -> PacoteApi:
    return PacoteApi(chamado=False, http=None, erro=None, dados=None)


def _chamar_performance(mlbu, api_ml, cache, lock) -> PacoteApi:
    with lock:
        if mlbu in cache:
            return cache[mlbu]
    # Chamada de rede FORA do lock — não trava outras threads enquanto espera a API.
    pacote = api_ml.buscar_performance(mlbu)
    with lock:
        cache.setdefault(mlbu, pacote)
        return cache[mlbu]


def _chamar_price_to_win(mlb, api_ml, cache, lock) -> PacoteApi:
    with lock:
        if mlb in cache:
            return cache[mlb]
    pacote = api_ml.buscar_price_to_win(mlb)
    with lock:
        cache.setdefault(mlb, pacote)
        return cache[mlb]


def _montar_mlb(registro, api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw) -> dict:
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


def _montar_sku(sku, registros_idx, todos_registros, api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw) -> dict:
    fecho = encontrar_fecho_transitivo(sku, todos_registros)
    if not fecho:
        return {"sku": sku, "total_mlbs": 0, "mlbs": []}
    mlbs_saida = [
        _montar_mlb(registros_idx[mlb], api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw)
        for mlb in sorted(fecho)
    ]
    return {"sku": sku, "total_mlbs": len(mlbs_saida), "mlbs": mlbs_saida}


# ─── WORKER ─────────────────────────────────────────────────────────────

# Função Objetivo: Processa 1 SKU (fecho transitivo inteiro, todas as chamadas de
# performance/price_to_win dos MLBs relacionados) e devolve o resultado — não mexe em
# console, Progress nem arquivo de progresso, isso é 100% do chamador (thread principal).
def _processar_sku(
    empresa_ativa: str, sku: str, registros_idx: dict, todos_registros: list, api_ml: ApiMercadoLivre,
    cache_perf: dict, cache_ptw: dict, lock_perf: threading.Lock, lock_ptw: threading.Lock,
) -> ResultadoSku:
    definir_empresa_ativa(empresa_ativa)

    inicio_sku = time.perf_counter()
    try:
        bloco = _montar_sku(sku, registros_idx, todos_registros, api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw)
        erro = None
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        bloco = None
        erro = str(e)
    duracao_sku = time.perf_counter() - inicio_sku

    return ResultadoSku(sku=sku, bloco=bloco, duracao_segundos=round(duracao_sku, 2), erro=erro)


# ─── MAIN ────────────────────────────────────────────────────────────

def buscar_dados_sku_completo(empresa: str, skus: list | None = None) -> RelatorioBuscaDadosSkuCompleto:
    """
    skus=None  -> modo produção: todos os SKUs distintos, com checkpoint.
    skus=[...] -> modo teste: só os SKUs informados, sem checkpoint, faz
                  merge com o dados_completos_por_sku.json existente.
    """
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

    blocos = dict(blocos_prontos)
    erros_skus = []
    detalhe_skus: list[ResultadoSku] = []

    grupos = [
        pendentes[i:i + TAMANHO_GRUPO_EXIBICAO]
        for i in range(0, len(pendentes), TAMANHO_GRUPO_EXIBICAO)
    ]

    inicio_execucao = time.perf_counter()
    skus_feitos = 0

    empresa_ativa = obter_empresa_ativa()  # lido 1x na thread principal, repassado pra cada worker

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

            # * [EXPLICAÇÃO] → mesma mudança já aplicada em buscar_mlbs.py/
            #                  buscar_detalhes.py (29/09/2026): tarefas criadas com
            #                  start=False (igual antes) mas iniciadas TODAS juntas,
            #                  logo antes de submeter pro ThreadPoolExecutor. Formato
            #                  visual não muda em nada.
            tarefas = {}
            for i, sku in enumerate(grupo):
                indice_absoluto = skus_feitos + i + 1
                task_id = progress.add_task(
                    f"[{indice_absoluto}/{len(pendentes)}] {sku[:22]}", total=1, resultado="⏳ na fila", start=False
                )
                tarefas[task_id] = (indice_absoluto, sku)

            for task_id in tarefas:
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS_DADOS_SKU_COMPLETO) as executor:
                futuros = {
                    executor.submit(
                        _processar_sku, empresa_ativa, sku, registros_idx, todos_registros,
                        api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw,
                    ): task_id
                    for task_id, (indice_absoluto, sku) in tarefas.items()
                }

                # * [EXPLICAÇÃO] → toda mutação de Progress/blocos/erros_skus só
                #                  acontece aqui, na thread principal, via as_completed
                #                  — nunca dentro de _processar_sku (worker). Mesma
                #                  disciplina já usada nos outros domínios.
                for futuro in as_completed(futuros):
                    task_id = futuros[futuro]
                    indice_absoluto, sku = tarefas[task_id]

                    try:
                        resultado = futuro.result()
                    except Exception as e:
                        resultado = ResultadoSku(sku=sku, erro=f"ERRO INESPERADO: {e}")

                    detalhe_skus.append(resultado)

                    if resultado.erro:
                        erros_skus.append({"sku": resultado.sku, "erro": resultado.erro})
                        progress.update(task_id, resultado="[red]✗ ERRO — ver .log[/red]")
                    else:
                        blocos[resultado.sku] = resultado.bloco
                        progress.update(task_id, resultado=f"{resultado.bloco['total_mlbs']} MLBs")

                    progress.update(task_id, completed=1)
                    skus_feitos += 1

                    # Salva progresso a cada SKU CONCLUÍDO — mesmo trade-off de
                    # resiliência já documentado nos outros domínios: sob paralelismo,
                    # um crash no pior caso perde mais de 1 SKU em andamento, não só 1.
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
    gerado_em = time.strftime("%Y-%m-%d %H:%M:%S")
    resultado_final = {
        "gerado_em": gerado_em,
        "empresa": empresa,
        "skus": list(blocos_final.values()),
    }
    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(resultado_final, f, ensure_ascii=False, indent=2)

    if caminho_progresso is not None and caminho_progresso.exists() and not erros_skus:
        caminho_progresso.unlink()

    skus_mais_lentos = sorted(detalhe_skus, key=lambda r: r.duracao_segundos, reverse=True)[:5]

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green] SKUs no arquivo final: {len(blocos_final)}")
    resumo_linha = f"SKUs processados nesta execução: {skus_feitos}/{len(pendentes)}"
    if erros_skus:
        resumo_linha += f"  •  [red]{len(erros_skus)} SKUs c/ erro[/red]"
    console.print(resumo_linha)
    console.print(f"Tempo total: {duracao_total:.1f}s")
    if skus_mais_lentos:
        console.print("5 SKUs mais lentos:")
        for r in skus_mais_lentos:
            console.print(f"  {r.duracao_segundos:>6.2f}s — {r.sku}")
    console.print(f"JSON: {caminho_json}")

    return RelatorioBuscaDadosSkuCompleto(
        empresa=empresa,
        gerado_em=gerado_em,
        total_skus_no_arquivo=len(blocos_final),
        skus_processados_nesta_execucao=skus_feitos,
        skus_pendentes_no_inicio=len(pendentes),
        skus_com_erro=len(erros_skus),
        duracao_total_segundos=round(duracao_total, 2),
        detalhe_skus=detalhe_skus,
        erros_skus=erros_skus,
        skus=list(blocos_final.values()),
    )