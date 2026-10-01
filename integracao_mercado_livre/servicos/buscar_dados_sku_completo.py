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
# Refinamento da Etapa 4 (30/09/2026, 1ª rodada) — reestruturado em 3
# fases explícitas:
#
#   FASE 1 (descoberta) — calcula o fecho transitivo de TODOS os SKUs
#   pendentes de uma vez, antes de qualquer chamada de API.
#
#   FASE 2 (empacotamento) — agrupa SKUs INTEIROS (nunca corta 1 SKU no
#   meio) em grupos, somando o tamanho do fecho de cada um até bater
#   ~META_MLBS_POR_GRUPO. Troca "20 SKUs por grupo" (desbalanceado) por
#   "~20 MLBs por grupo" (balanceado).
#
#   FASE 3 (execução) — pra cada grupo, achata os SKUs em itens de
#   trabalho por MLB (não por SKU) e dispara TODOS no mesmo
#   ThreadPoolExecutor(20) — paralelismo de verdade dentro de 1 SKU
#   também, sem pool aninhado. Contador de "MLBs pendentes" por SKU (só
#   a thread principal mexe) decide quando um SKU fecha.
#
# Refinamento da Etapa 4 (30/09/2026, 2ª rodada) — 2 correções encontradas
# testando em produção:
#
#   1. CHECKPOINT gravado 1x por grupo (não por SKU) — gravar a cada SKU
#      virou trabalho síncrono demais com o disparo achatado (muitos SKUs
#      pequenos terminando em rajada).
#
#   2. rich.Progress voltou a ser criado 1x POR GRUPO (não 1 só pro run
#      inteiro). Comparado com buscar_mlbs.py/buscar_detalhes.py (já
#      validados) e com o próprio código original deste arquivo: os 2
#      sempre criam o Progress de novo a cada grupo, DEPOIS do
#      console.print do cabeçalho do grupo — nunca 1 Progress abrangendo
#      vários grupos. Eu tinha quebrado esse padrão na 1ª rodada (Progress
#      único pra todos os ~300 grupos), e isso causou o bug real: o
#      console.print() do módulo (Console separado do que o Progress usa
#      internamente) escrevendo no terminal ENQUANTO a região viva do
#      Progress estava aberta — os 2 Console não se coordenam, o cursor
#      real do terminal ficava fora de sincronia com o que o Progress
#      achava que tinha pintado. Sintoma exato reportado: tela "congelada"
#      durante a execução, e ao apertar Ctrl+C (que aciona Progress.stop(),
#      fazendo 1 repaint final completo) tudo que "estava escondido"
#      aparecia de uma vez — prova de que o processamento em si nunca
#      parou, só a pintura incremental na tela é que não funcionava.
#      Corrigido voltando ao padrão dos outros 2 arquivos.
#
#   3. Aproveitado pra simplificar a exibição: 1 linha de progresso POR
#      GRUPO (não 1 por SKU) — mostra "X/Y MLBs" daquele grupo avançando.
#      Pedido explícito de Matheus (30/09/2026): não precisa granularidade
#      por SKU/MLB individual na tela, só por grupo. O bookkeeping interno
#      por SKU (contador de MLBs pendentes, checkpoint, "5 SKUs mais
#      lentos") continua exatamente igual — só a exibição ficou mais
#      simples.
#
# Refinamento da Etapa 4 (30/09/2026, 3ª rodada) — a exibição por grupo
# (item 3 acima) escondia demais: dava pra ver que o grupo avançava, mas
# não O QUE estava avançando — em especial os ~53% de 404 esperado em
# /performance ficavam invisíveis (só no .log). Pedido de Matheus: ver em
# tempo real cada MLB do grupo, com o resultado (ok/erro) já embutido na
# própria linha — sem painel separado, sem esconder nada.
#
#   O Progress volta a ter 1 task POR UNIDADE DE TRABALHO — só que agora
#   a unidade é o MLB (não o SKU), porque o disparo em si já é achatado
#   por MLB desde a 1ª rodada. É o MESMO padrão já usado em
#   buscar_mlbs.py, buscar_detalhes.py e na versão original deste
#   arquivo (tasks pré-criadas, campo "resultado" customizado por task,
#   spinner que resolve pra ✓/✗) — nenhuma mecânica nova, só aplicado na
#   granularidade que o desenho por MLB já permite.
#
#   Como cada linha de MLB já mostra o erro embutido, o log cru que
#   chamar_api() manda pro console pro mesmo evento (logger.error/
#   .warning, nível WARNING+, indo pro RichHandler configurado em
#   cliente_api.py) virou redundante — e pior, se disparasse durante a
#   região viva do Progress, quebraria a tela de novo (mesma causa raiz
#   da 2ª rodada, item 2). Por isso, só durante a Fase 3, o handler de
#   CONSOLE desse logger específico (nome_log="buscar_dados_sku_completo")
#   é removido — guardado numa variável — e devolvido no final, num
#   try/finally. O handler de ARQUIVO (nível INFO, recebe tudo) não é
#   tocado — o .log continua com o histórico completo, igual sempre foi.
#   _configurar_logger() é chamado explicitamente aqui, antes do loop de
#   grupos, porque é idempotente (só configura os handlers na 1ª vez) e
#   garante que o logger já existe ANTES de qualquer chamada de API
#   acontecer lá dentro de uma thread do pool — senão a 1ª chamada real
#   configuraria o logger sozinha (com o RichHandler de volta), driblando
#   esse silenciamento.
#
# Refinamento da Etapa 4 (30/09/2026, 4ª rodada) — Matheus rodou a base
# Magazine inteira com o código da 3ª rodada validada e teve 0 erros —
# mesmo com uma taxa de 404 em /performance já medida em ~53% antes.
# Investigação (sincronizado + git diff origin/dev, sem propor teste
# nenhum até confirmar a causa, conforme pedido): o código aplicado
# batia 100% com o diff entregue — não foi bug introduzido na aplicação.
# A causa real é estrutural, e sempre existiu (inclusive antes da
# Etapa 4, em todas as rodadas):
#
#   DadosSkuCompletoML.buscar_performance/buscar_price_to_win (Contexto,
#   ver comentário "Peça 4" acima) já capturam ErroAPI/ErroAutenticacaoAPI
#   POR DENTRO de si mesmas e devolvem o erro embutido em PacoteApi.erro,
#   em vez de deixar a exceção propagar — de propósito, é o "Padrão de
#   Robustez para Clientes de API Externa" (ver vault): 1 sub-chamada
#   falha (ex: 404 em /performance) não pode abortar o MLB/SKU inteiro.
#
#   Consequência: ResultadoMlb.erro — o sinal que a linha vermelha da 3ª
#   rodada usa — fica None nesse caso, quase sempre. O 404 nunca
#   desapareceu de verdade (sempre foi gravado certinho dentro do JSON
#   final, em mlb_pronto["performance"]["erro"]) — só ficou invisível NA
#   TELA a partir da 3ª rodada, porque o log bruto que antes vazava pro
#   console (chamar_api() -> logger.error, nível WARNING+) foi
#   silenciado de propósito (ver nota da 3ª rodada) sem que a nova linha
#   por MLB tivesse como substituí-lo pra esse caso específico.
#
# Correção (confirmada por Matheus): _detectar_avisos_mlb() olha direto
# pra mlb_pronto["performance"]["erro"] / ["price_to_win"]["erro"] depois
# que o MLB processa com sucesso (resultado.erro is None) e, se achar
# algo, mostra [yellow]⚠[/yellow] na linha daquele MLB — distinto do
# [red]✗[/red], que continua reservado só pra falha dura de verdade
# (exceção não tratada que de fato derruba o MLB, capturada em
# _processar_mlb). NADA muda no fechamento do SKU: _fechar_sku_sucesso/
# _fechar_sku_com_erro continuam exatamente iguais — um MLB com aviso
# ainda fecha o SKU como sucesso normalmente, porque é assim que o
# Padrão de Robustez já funcionava desde sempre (a ausência de
# performance/price_to_win nunca invalidou o SKU).
#
# Adicionado também (não pedido explicitamente, mas de baixo risco e
# ajuda a quantificar o volume real de 404 — pendência aberta no
# checkpoint): contador mlbs_com_aviso (total e por grupo) e campo
# total_mlbs_com_aviso no relatório final.

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI, _configurar_logger
from api_mercado_livre.dados_sku_completo_ml import PacoteApi
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

def _pacote_nao_chamado() -> PacoteApi:
    return PacoteApi(chamado=False, http=None, erro=None, dados=None)


def _chamar_performance(mlbu, api_ml, cache, lock) -> PacoteApi:
    with lock:
        if mlbu in cache:
            return cache[mlbu]
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


def _detectar_avisos_mlb(mlb_pronto: dict) -> list[str]:
    """
    Erros "soft" — ver nota "4ª rodada" no topo do arquivo. A Contexto
    (DadosSkuCompletoML) já captura ErroAPI/ErroAutenticacaoAPI por
    dentro de buscar_performance/buscar_price_to_win e devolve o erro
    embutido em PacoteApi.erro, em vez de deixar propagar — de propósito
    (Padrão de Robustez), pra 1 sub-chamada falha (ex: 404 em
    /performance) não abortar o MLB/SKU inteiro. Por isso
    ResultadoMlb.erro fica None nesses casos — o sinal real está aninhado
    aqui dentro, em mlb_pronto["performance"|"price_to_win"]["erro"].
    Só chamada quando resultado.erro já é None (MLB processou sem
    exceção). Retorna 0, 1 ou 2 mensagens.
    """
    avisos = []
    performance = (mlb_pronto or {}).get("performance") or {}
    if performance.get("erro"):
        avisos.append(f"performance: {performance['erro']}")
    price_to_win = (mlb_pronto or {}).get("price_to_win") or {}
    if price_to_win.get("erro"):
        avisos.append(f"price_to_win: {price_to_win['erro']}")
    return avisos


# ─── FASE 3 — trabalho no nível de MLB (não mais de SKU) ──────────────

@dataclass
class ResultadoMlb:
    sku: str
    mlb: str
    mlb_pronto: dict | None = None
    duracao_segundos: float = 0.0
    erro: str | None = None


def _processar_mlb(empresa_ativa, sku, mlb, registros_idx, api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw) -> ResultadoMlb:
    definir_empresa_ativa(empresa_ativa)
    inicio = time.perf_counter()
    try:
        mlb_pronto = _montar_mlb(registros_idx[mlb], api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw)
        return ResultadoMlb(sku=sku, mlb=mlb, mlb_pronto=mlb_pronto, duracao_segundos=time.perf_counter() - inicio)
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        return ResultadoMlb(sku=sku, mlb=mlb, mlb_pronto=None, duracao_segundos=time.perf_counter() - inicio, erro=str(e))


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
    total_mlbs_com_aviso: int = 0
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

    3 fases (ver comentário no topo do arquivo): descoberta -> empacotamento
    -> execução (paralelo, achatado por MLB, 1 Progress por grupo, 1 task
    por MLB dentro dele).
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

    inicio_fase3 = time.perf_counter()
    mlbs_feitos = 0
    mlbs_com_aviso = 0
    skus_feitos = 0

    if grupos:
        console.print(f"[bold]Fase 3/3[/bold] — execução paralela ({MAX_WORKERS_DADOS_SKU_COMPLETO} workers)\n")

        # Ver nota "3ª rodada" no topo do arquivo — silencia o handler de
        # CONSOLE do logger desta Fase 3 (o de ARQUIVO continua intacto),
        # porque cada MLB já mostra ok/erro na própria linha logo abaixo.
        logger_sku_completo = _configurar_logger(pasta_logs, nome_log="buscar_dados_sku_completo")
        handlers_console_originais = [
            h for h in logger_sku_completo.handlers if isinstance(h, RichHandler)
        ]
        for h in handlers_console_originais:
            logger_sku_completo.removeHandler(h)

        try:
            for indice_grupo, grupo in enumerate(grupos, start=1):
                inicio_grupo = time.perf_counter()
                soma_mlbs_grupo = sum(len(fechos[s]) for s in grupo)
                decorrido = time.perf_counter() - inicio_execucao
                sku_inicial = skus_feitos + 1
                sku_final = skus_feitos + len(grupo)

                # console.print aqui, ANTES de abrir o Progress deste grupo —
                # nunca durante uma região viva aberta (ver nota no topo do
                # arquivo).
                console.print(
                    f"[bold]GRUPO {indice_grupo}/{len(grupos)}[/bold]  "
                    f"(SKUs {sku_inicial}-{sku_final} de {len(pendentes)}, {len(grupo)} SKUs, {soma_mlbs_grupo} MLBs)  "
                    f"•  {len(blocos)} SKUs prontos até agora  •  {decorrido:.0f}s decorridos"
                )

                mlbs_pendentes_por_sku = {sku: len(fechos[sku]) for sku in grupo}
                mlbs_prontos_por_sku = {sku: [] for sku in grupo}
                inicio_sku_por_sku = {sku: time.perf_counter() for sku in grupo}
                erros_skus_processados = set()
                erros_no_grupo = 0
                avisos_no_grupo = 0

                def _fechar_sku_sucesso(sku: str):
                    nonlocal skus_feitos
                    duracao_sku = time.perf_counter() - inicio_sku_por_sku[sku]
                    mlbs_saida = sorted(mlbs_prontos_por_sku[sku], key=lambda r: r["mlb"])
                    bloco = {"sku": sku, "total_mlbs": len(mlbs_saida), "mlbs": mlbs_saida}

                    detalhe_skus.append(ResultadoSku(sku=sku, bloco=bloco, duracao_segundos=round(duracao_sku, 2)))
                    blocos[sku] = bloco
                    skus_feitos += 1

                def _fechar_sku_com_erro(sku: str, mensagem_erro: str):
                    nonlocal skus_feitos, erros_no_grupo
                    duracao_sku = time.perf_counter() - inicio_sku_por_sku[sku]

                    erros_skus.append({"sku": sku, "erro": mensagem_erro})
                    detalhe_skus.append(ResultadoSku(sku=sku, duracao_segundos=round(duracao_sku, 2), erro=mensagem_erro))
                    skus_feitos += 1
                    erros_no_grupo += 1
                    # Erro nunca vai pro checkpoint — SKU continua "pendente"
                    # numa próxima retomada, mesmo critério de antes.

                # SKUs com fecho vazio (raro) fecham de cara, sem MLB nenhum.
                for sku in grupo:
                    if mlbs_pendentes_por_sku[sku] == 0:
                        _fechar_sku_sucesso(sku)

                itens_trabalho = [(sku, mlb) for sku in grupo for mlb in fechos[sku]]

                # Progress criado AQUI, 1x por grupo — mesma regra de sempre
                # (nunca abrange mais de 1 grupo, nunca com console.print()
                # aberto no meio dele — ver nota no topo). Dentro dele, 1
                # task POR MLB (3ª rodada) — mesmo padrão já usado no resto
                # do sistema, só que na granularidade do MLB em vez do SKU.
                if itens_trabalho:
                    with Progress(
                        SpinnerColumn(finished_text="[green]✓[/green]"),
                        TextColumn("[cyan]{task.description:<45}"),
                        BarColumn(),
                        TextColumn("{task.fields[resultado]}"),
                        TimeElapsedColumn(),
                    ) as progress:

                        task_ids_por_item = {}
                        for sku, mlb in itens_trabalho:
                            task_id = progress.add_task(
                                f"{sku[:20]} · {mlb}", total=1,
                                resultado="[dim]processando...[/dim]",
                            )
                            task_ids_por_item[(sku, mlb)] = task_id

                        with ThreadPoolExecutor(max_workers=MAX_WORKERS_DADOS_SKU_COMPLETO) as executor:
                            futuros = [
                                executor.submit(
                                    _processar_mlb, empresa_ativa, sku, mlb, registros_idx,
                                    api_ml, cache_perf, cache_ptw, lock_perf, lock_ptw,
                                )
                                for sku, mlb in itens_trabalho
                            ]
                            # Toda mutação de progress/blocos/contadores só
                            # acontece aqui, na thread principal, via
                            # as_completed.
                            for futuro in as_completed(futuros):
                                resultado = futuro.result()
                                sku = resultado.sku
                                mlb = resultado.mlb
                                task_id = task_ids_por_item[(sku, mlb)]
                                mlbs_feitos += 1

                                if resultado.erro:
                                    progress.update(
                                        task_id, completed=1,
                                        resultado=f"[red]✗ {resultado.erro}[/red]",
                                    )
                                else:
                                    # 4ª rodada — ver nota no topo do arquivo:
                                    # o 404 "soft" de /performance ou
                                    # /price_to_win não vira resultado.erro
                                    # (Padrão de Robustez, capturado dentro
                                    # da Contexto) — precisa olhar dentro do
                                    # mlb_pronto pra achar.
                                    avisos = _detectar_avisos_mlb(resultado.mlb_pronto)
                                    if avisos:
                                        mlbs_com_aviso += 1
                                        avisos_no_grupo += 1
                                        progress.update(
                                            task_id, completed=1,
                                            resultado=f"[yellow]⚠ {' · '.join(avisos)}[/yellow]",
                                        )
                                    else:
                                        progress.update(
                                            task_id, completed=1,
                                            resultado="[green]✓ ok[/green]",
                                        )

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

                # Checkpoint gravado 1x por grupo, DEPOIS do Progress fechar
                # — todos os SKUs do grupo já 100% resolvidos (nenhum
                # cortado entre grupos).
                if caminho_progresso is not None:
                    with open(caminho_progresso, "w", encoding="utf-8") as f:
                        json.dump({
                            "blocos": list(blocos.values()),
                            "atualizado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }, f, ensure_ascii=False)

                duracao_grupo = time.perf_counter() - inicio_grupo
                vazao_grupo = soma_mlbs_grupo / duracao_grupo if duracao_grupo > 0 else 0.0
                linha_grupo = (
                    f"  └─ grupo concluído em {duracao_grupo:.2f}s  •  {vazao_grupo:.1f} MLBs/s  •  "
                    f"{mlbs_feitos} MLBs prontos até agora"
                )
                if avisos_no_grupo:
                    linha_grupo += f"  •  [yellow]{avisos_no_grupo} MLB(s) c/ aviso[/yellow]"
                if erros_no_grupo:
                    linha_grupo += f"  •  [red]{erros_no_grupo} SKU(s) c/ erro[/red]"
                console.print(linha_grupo + "\n")
        finally:
            for h in handlers_console_originais:
                logger_sku_completo.addHandler(h)

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
    if mlbs_com_aviso:
        resumo_linha += f"  •  [yellow]{mlbs_com_aviso} MLB(s) c/ aviso (performance/price_to_win)[/yellow]"
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
        total_mlbs_com_aviso=mlbs_com_aviso,
        total_grupos=len(grupos),
        duracao_fase1_descoberta_segundos=round(duracao_fase1, 3),
        duracao_fase2_empacotamento_segundos=round(duracao_fase2, 3),
        duracao_fase3_execucao_segundos=round(duracao_fase3, 2),
        duracao_total_segundos=round(duracao_total, 2),
        detalhe_skus=detalhe_skus,
        erros_skus=erros_skus,
        skus=resultado_final["skus"],
    )