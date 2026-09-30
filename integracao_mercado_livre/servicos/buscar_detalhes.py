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
# de lotes/progresso/retomada.
#
# Otimização e POO (29/09/2026 — Etapa 3 de "otimizar e paralelizar todas
# as etapas que envolvem integração com o ML", já com a correção de pool
# de conexão de chamar_api() beneficiando este domínio automaticamente):
#   1. Paralelismo via ThreadPoolExecutor dentro de cada bloco de exibição
#      (até 20 lotes concorrentes por bloco) — mesmo padrão de buscar_mlbs.py
#      e buscar_comissao_real_ml.py, mesma correção de threading.local().
#      MAX_WORKERS_BUSCA_DETALHES=20 é extrapolado do teto já confirmado
#      nos outros domínios — não testado isoladamente pra este endpoint
#      (multiget /items?ids=) antes desta rodada.
#   2. rich.Progress mantido 100% como estava — só o momento de start_task
#      muda (todas as tarefas do bloco juntas, refletindo a concorrência
#      real). Toda mutação de Progress/estado compartilhado continua só na
#      thread principal, via as_completed, nunca dentro do worker.
#   3. Retorno trocado de dict solto pra @dataclass (RelatorioBuscaDetalhes/
#      ResultadoLote) — mesmo padrão de RelatorioBuscaMlbs/RelatorioComissaoReal.
#      DECISÃO CONSCIENTE, diferente de buscar_mlbs: o registro de ~50 campos
#      por MLB (_extrair_campos_pai/_processar_item, em detalhes_ml.py)
#      CONTINUA como dict solto, não virou dataclass — é gravado direto em
#      detalhes_mlbs.json, hoje lido por pelo menos 5 arquivos reais
#      (importar_anuncios_ml.py, importar_dimensoes_declaradas_ml.py,
#      classificacao_catalogo.py, variacao.py, gerar_relatorio_frete_erp_vs_ml.py)
#      — é dado bruto 1:1 com o JSON de saída, sem lógica derivada; a
#      pendência do vault fala em dataclass pros retornos dos
#      ORQUESTRADORES, não em qualquer dict do sistema. Sem Enum neste
#      arquivo também — os IDs de atributo usados na extração (SELLER_SKU,
#      DIMENSIONS, etc.) aparecem 1 vez cada, não são um conjunto
#      combinatório repetido como os 4 _LIST de buscar_mlbs.
#   4. Trade-off de resiliência sob paralelismo: o progresso continua
#      salvo a cada lote CONCLUÍDO (não só ao fim do bloco), só que agora
#      vários lotes podem estar em voo ao mesmo tempo — um crash no pior
#      caso perde até MAX_WORKERS_BUSCA_DETALHES lotes em andamento, não só
#      1. Sem risco de corrupção: é leitura idempotente da API, a retomada
#      só refaz o que não ficou salvo. Mesmo espírito do trade-off já
#      aceito em buscar_comissao_real_ml.py (bulk_update por grupo).

import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa, obter_empresa_ativa

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

TAMANHO_LOTE = 20            # quantos MLBs por chamada multiget (limite da API)
TAMANHO_GRUPO_EXIBICAO = 20  # quantos lotes por bloco visual no console — também é
                              # o tamanho do lote de paralelismo (ver nota de
                              # otimização 29/09/2026 no cabeçalho do arquivo)

# * [EXPLICAÇÃO] → throughput de GET /items?ids= (multiget) sob ThreadPoolExecutor
#                  NÃO foi testado isoladamente pra este endpoint específico —
#                  aplicado por extrapolação (mesma conta, mesmo domínio de API do
#                  ML, mesmo teto de 20 já confirmado independentemente pro frete,
#                  comissão e mlbs) mais a margem de segurança que o fix de pool de
#                  conexão em chamar_api() já dá. Se algum 429 aparecer de verdade
#                  nesse domínio, é sinal pra medir com dado real em vez de só
#                  reduzir no escuro.
MAX_WORKERS_BUSCA_DETALHES = 20


@dataclass
class ResultadoLote:
    """Resultado de 1 lote processado (até 20 MLBs via multiget) — objeto de
    processo/domínio (nunca salvo no banco), mesmo padrão de ResultadoVarrida
    (buscar_mlbs.py). erro só é preenchido quando o LOTE INTEIRO falhou
    (ErroAPI/ErroAutenticacaoAPI) — item individual com erro (código != 200 dentro
    de um lote OK) continua em erros_itens, sem invalidar o lote inteiro."""
    lote: int
    tamanho: int
    registros: list[dict] = field(default_factory=list)
    erros_itens: list[dict] = field(default_factory=list)
    duracao_segundos: float = 0.0
    erro: str | None = None

    @property
    def registros_gerados(self) -> int:
        return len(self.registros)

    @property
    def itens_com_erro(self) -> int:
        return len(self.erros_itens)


@dataclass
class RelatorioBuscaDetalhes:
    """Contagens e tempo de 1 execução completa do orquestrador — devolvido no
    lugar do dict cru anterior, mesmo padrão de RelatorioBuscaMlbs/RelatorioComissaoReal."""
    empresa: str
    gerado_em: str = ""
    total_registros: int = 0
    total_mlbs_processados: int = 0
    total_mlbs_na_lista: int = 0
    lotes_total: int = 0
    lotes_com_erro: int = 0
    duracao_total_segundos: float = 0.0
    detalhe_lotes: list[ResultadoLote] = field(default_factory=list)
    erros_itens: list[dict] = field(default_factory=list)
    erros_lotes: list[dict] = field(default_factory=list)
    registros: list[dict] = field(default_factory=list)


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


# ─── WORKER ─────────────────────────────────────────────────────────────

# Função Objetivo: Processa 1 lote (multiget de até 20 MLBs, já dentro de
# DetalhesML.buscar_lote) e devolve o resultado — não mexe em console, Progress
# nem arquivo de progresso, isso é 100% do chamador (thread principal).
def _processar_lote(
    empresa_ativa: str, api_ml: ApiMercadoLivre, indice_absoluto: int, lote: list[dict], meta_map: dict, pasta_logs,
) -> ResultadoLote:
    # * [EXPLICAÇÃO] → mesma correção já aplicada em calcular_grade_precificacao_ml.py,
    #                  buscar_comissao_real_ml.py e buscar_mlbs.py (29/09/2026):
    #                  core.empresa guarda a empresa ativa em threading.local() —
    #                  cada thread nova do ThreadPoolExecutor nasce com esse estado
    #                  vazio, mesmo a thread principal já tendo chamado
    #                  definir_empresa_ativa() antes.
    definir_empresa_ativa(empresa_ativa)

    ids_str = ",".join(m["mlb"] for m in lote)
    inicio_lote = time.perf_counter()

    try:
        registros_lote, erros_lote_itens = api_ml.buscar_detalhes_lote(ids_str, meta_map)
        erro = None
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        registros_lote, erros_lote_itens = [], []
        erro = str(e)

    duracao_lote = time.perf_counter() - inicio_lote

    return ResultadoLote(
        lote=indice_absoluto, tamanho=len(lote),
        registros=registros_lote, erros_itens=erros_lote_itens,
        duracao_segundos=round(duracao_lote, 2), erro=erro,
    )


# ─── MAIN ────────────────────────────────────────────────────────────────

def buscar_detalhes(empresa: str) -> RelatorioBuscaDetalhes:
    """
    Ponto único de entrada. Busca o detalhe completo de cada MLB da
    empresa informada (EMPRESA_MAGAZINE ou EMPRESA_SAMVALE), a partir do
    lista_mlbs.json gerado pelo ponto 02 (buscar_mlbs). Salva
    detalhes_mlbs.json isolado por empresa, e devolve um relatório da execução.
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
    detalhe_lotes: list[ResultadoLote] = []
    inicio_execucao = time.perf_counter()
    lotes_feitos = 0

    empresa_ativa = obter_empresa_ativa()  # lido 1x na thread principal, repassado pra cada worker

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

            # * [EXPLICAÇÃO] → mesma mudança de buscar_mlbs.py (29/09/2026): tarefas
            #                  criadas com start=False (igual antes) mas iniciadas
            #                  TODAS juntas, logo antes de submeter pro
            #                  ThreadPoolExecutor — reflete a execução concorrente
            #                  real. Formato visual em si não muda em nada.
            tarefas = {}
            for i, lote in enumerate(grupo):
                indice_absoluto = lotes_feitos + i + 1
                task_id = progress.add_task(
                    f"lote {indice_absoluto}/{total_lotes}", total=1, resultado="⏳ na fila", start=False
                )
                tarefas[task_id] = (indice_absoluto, lote)

            for task_id in tarefas:
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS_BUSCA_DETALHES) as executor:
                futuros = {
                    executor.submit(
                        _processar_lote, empresa_ativa, api_ml, indice_absoluto, lote, meta_map, pasta_logs,
                    ): task_id
                    for task_id, (indice_absoluto, lote) in tarefas.items()
                }

                # * [EXPLICAÇÃO] → toda mutação de Progress/processados_ids/
                #                  todos_registros/erros_itens só acontece aqui, na
                #                  thread principal, via as_completed — nunca dentro
                #                  de _processar_lote (worker). Mesma disciplina já
                #                  usada em buscar_comissao_real_ml.py/buscar_mlbs.py.
                for futuro in as_completed(futuros):
                    task_id = futuros[futuro]
                    indice_absoluto, lote = tarefas[task_id]

                    try:
                        resultado = futuro.result()
                    except Exception as e:
                        resultado = ResultadoLote(
                            lote=indice_absoluto, tamanho=len(lote), erro=f"ERRO INESPERADO: {e}",
                        )

                    detalhe_lotes.append(resultado)

                    if resultado.erro:
                        erros_lotes.append({"lote": resultado.lote, "erro": resultado.erro})
                        progress.update(task_id, resultado="[red]✗ ERRO — ver .log[/red]")
                    else:
                        todos_registros.extend(resultado.registros)
                        erros_itens.extend(resultado.erros_itens)
                        for reg in resultado.registros:
                            processados_ids.add(reg["mlb"])

                        texto_resultado = f"{resultado.registros_gerados} registros"
                        if resultado.itens_com_erro:
                            texto_resultado += f" [yellow]({resultado.itens_com_erro} c/ erro)[/yellow]"
                        progress.update(task_id, resultado=texto_resultado)

                    progress.update(task_id, completed=1)
                    lotes_feitos += 1

                    # Salva progresso a cada lote CONCLUÍDO — dado de API é caro,
                    # não perder o que já foi buscado se cair no meio. Sob
                    # paralelismo, vários lotes podem estar em voo ao mesmo tempo
                    # (até MAX_WORKERS_BUSCA_DETALHES) — ver nota de resiliência no
                    # cabeçalho do arquivo.
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

    gerado_em = time.strftime("%Y-%m-%d %H:%M:%S")

    # * [EXPLICAÇÃO] → conversão manual pra dict antes do json.dump() (29/09/2026) —
    #                  garante que detalhes_mlbs.json mantém EXATAMENTE o mesmo
    #                  formato de antes. Lido direto do disco por pelo menos 5
    #                  arquivos reais (ver cabeçalho) — qualquer deriva de formato
    #                  aqui quebraria esses scripts silenciosamente.
    resumo = {
        "gerado_em": gerado_em,
        "empresa": empresa,
        "total_registros": len(todos_registros),
        "total_mlbs_processados": len(processados_ids),
        "total_mlbs_na_lista": total_geral,
        "lotes_total": total_lotes,
        "lotes_com_erro": len(erros_lotes),
        "duracao_total_segundos": round(duracao_total, 2),
        "detalhe_lotes": [
            {
                "lote": r.lote,
                "tamanho": r.tamanho,
                "registros_gerados": r.registros_gerados,
                "itens_com_erro": r.itens_com_erro,
                "duracao_segundos": r.duracao_segundos,
                "erro": r.erro,
            }
            for r in detalhe_lotes
        ],
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

    lotes_mais_lentos = sorted(detalhe_lotes, key=lambda r: r.duracao_segundos, reverse=True)[:5]

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green] Registros: {len(todos_registros)} (inclui variações)")
    resumo_linha = f"MLBs processados: {len(processados_ids)}/{total_geral}"
    if erros_itens:
        resumo_linha += f"  •  [yellow]{len(erros_itens)} itens c/ erro[/yellow]"
    if erros_lotes:
        resumo_linha += f"  •  [red]{len(erros_lotes)} lotes c/ erro[/red]"
    console.print(resumo_linha)
    console.print(f"Tempo total: {duracao_total:.1f}s")
    console.print("5 lotes mais lentos:")
    for r in lotes_mais_lentos:
        console.print(f"  {r.duracao_segundos:>6.2f}s — lote {r.lote} ({r.registros_gerados} registros)")
    console.print(f"JSON: {caminho_json}")

    return RelatorioBuscaDetalhes(
        empresa=empresa,
        gerado_em=gerado_em,
        total_registros=len(todos_registros),
        total_mlbs_processados=len(processados_ids),
        total_mlbs_na_lista=total_geral,
        lotes_total=total_lotes,
        lotes_com_erro=len(erros_lotes),
        duracao_total_segundos=round(duracao_total, 2),
        detalhe_lotes=detalhe_lotes,
        erros_itens=erros_itens,
        erros_lotes=erros_lotes,
        registros=todos_registros,
    )