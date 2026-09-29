# integracao_mercado_livre/servicos/buscar_mlbs.py
#
# Busca TODOS os MLBs de 1 empresa (Magazine ou Samvale) usando "get all"
# com paginação via scroll_id. 168 varridas cobrindo todas as combinações
# possíveis de status × logística × tipo × catálogo (6 × 7 × 2 × 2).
# Salva 1 lista_mlbs.json por empresa, isolado, dentro de
# integracao_mercado_livre/Arquivos_API/<Empresa>/.
#
# Migrado de APP_performance/buscar_mlbs.py (pasta separada, fora do repo).
#
# Peça 4 da reforma estrutural (27/09/2026): a chamada à API e a
# varredura por scroll_id saíram daqui e foram pra
# api_mercado_livre.mlbs_ml.MlbsML (Contexto), por trás de
# ApiMercadoLivre (Facade). Este arquivo continua 100% dono do laço
# sobre as 168 combinações e do console.
#
# Otimização e POO (29/09/2026 — Etapa 2 de "otimizar e paralelizar todas
# as etapas que envolvem integração com o ML", já com a correção de pool
# de conexão de chamar_api(), que beneficia este domínio automaticamente
# por ser transversal — ver seção 15 do Checkpoint de Comissão Real no
# vault):
#   1. Paralelismo via ThreadPoolExecutor dentro de cada grupo de status
#      (até 28 varridas por grupo) — mesmo padrão já usado em
#      calcular_grade_precificacao_ml.py e buscar_comissao_real_ml.py,
#      inclusive a correção de threading.local() (empresa ativa lida 1x
#      na thread principal, repassada, cada worker chama
#      definir_empresa_ativa() como 1ª linha). MAX_WORKERS_BUSCA_MLBS=20
#      é extrapolado do teto já confirmado com dado real pro frete e pra
#      comissão (não testado isoladamente pra este endpoint — ver
#      comentário na constante) — aplicado com cautela.
#   2. Exibição rich.Progress mantida 100% como estava (confirmado como
#      correto e funcional, não é o bug de redraw já corrigido em outro
#      lugar) — única mudança é todas as tarefas de um grupo iniciarem
#      juntas em vez de 1 de cada vez, refletindo a concorrência real.
#      Toda mutação do Progress continua só na thread principal (nunca
#      dentro do worker), mesma disciplina de buscar_comissao_real_ml.py.
#   3. Retorno de buscar_mlbs() trocado de dict solto pra @dataclass
#      (RelatorioBuscaMlbs) — mesmo padrão de RelatorioComissaoReal —, e
#      os 4 conjuntos de string solta (STATUS_LIST/LOGISTICA_LIST/
#      TIPO_LIST/CATALOGO_LIST) viraram Enum, movidos pro Contexto
#      (api_mercado_livre/mlbs_ml.py — Varrida/MlbEncontrado moram lá
#      também, ver decisão de camada no cabeçalho daquele arquivo).
#      lista_mlbs.json continua com o MESMO formato de sempre (conversão
#      manual pra dict antes do json.dump) — lido direto do disco por
#      buscar_detalhes.py, formato não pode mudar.

import json
import time
from pathlib import Path
from itertools import product
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from api_mercado_livre import ApiMercadoLivre
from api_mercado_livre.mlbs_ml import StatusAnuncio, TipoLogistica, TipoAnuncioML, CatalogoListing, Varrida, MlbEncontrado
from api_mercado_livre.core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa, obter_empresa_ativa

console = Console()

RAIZ_APP = Path(__file__).resolve().parent.parent  # integracao_mercado_livre/

NOME_PASTA_POR_EMPRESA = {
    EMPRESA_MAGAZINE: 'Magazine',
    EMPRESA_SAMVALE: 'Samvale',
}

# * [EXPLICAÇÃO] → throughput de GET /users/{user_id}/items/search (scan) sob
#                  ThreadPoolExecutor NÃO foi testado isoladamente pra este endpoint
#                  específico (diferente de /listing_prices, testado em
#                  scripts_exploracao_ML/teste_paralelismo_listing_prices.py) — aplicado por
#                  extrapolação (mesma conta, mesmo domínio de API do ML, mesmo teto de 20
#                  já confirmado independentemente pro frete e pra comissão) mais a margem de
#                  segurança que o fix de pool de conexão em chamar_api() já dá. Se algum 429
#                  aparecer de verdade nesse domínio, é sinal pra medir com dado real em vez
#                  de só reduzir no escuro.
MAX_WORKERS_BUSCA_MLBS = 20


@dataclass
class ResultadoVarrida:
    """Resultado de 1 varrida processada — objeto de processo/domínio (nunca salvo no
    banco), mesmo padrão de ResultadoComissaoVariacao (buscar_comissao_real_ml.py). erro só
    é preenchido quando a varrida falhou; mlbs_encontrados fica vazio nesse caso."""
    varrida: Varrida
    mlbs_encontrados: list[MlbEncontrado] = field(default_factory=list)
    duracao_segundos: float = 0.0
    erro: str | None = None

    @property
    def encontrados(self) -> int:
        return len(self.mlbs_encontrados)

    @property
    def label(self) -> str:
        return f"{self.varrida.status.value} | {self.varrida.label}"


@dataclass
class RelatorioBuscaMlbs:
    """Contagens e tempo de 1 execução completa do orquestrador — devolvido no lugar do
    dict cru anterior, mesmo padrão de RelatorioComissaoReal (buscar_comissao_real_ml.py) /
    RelatorioDeSincronizacao (integracao_sysemp/servicos/orquestrador.py)."""
    empresa: str
    gerado_em: str = ""
    total: int = 0
    varridas_total: int = 0
    varridas_com_resultado: int = 0
    varridas_sem_resultado: int = 0
    varridas_com_erro: int = 0
    duracao_total_segundos: float = 0.0
    detalhe_varridas: list[ResultadoVarrida] = field(default_factory=list)
    mlbs: list[MlbEncontrado] = field(default_factory=list)


# Agrupado por status — 6 grupos de 28 combinações cada (7 × 2 × 2), 168 no
# total. Cada grupo vira 1 bloco visual próprio no console (posições fixas,
# 1 linha por combinação), fechado antes do próximo abrir. Isso NÃO muda o
# que é buscado — só organiza o que é mostrado.
GRUPOS: dict[StatusAnuncio, list[Varrida]] = {}
for status in StatusAnuncio:
    GRUPOS[status] = [
        Varrida(status=status, logistic_type=logistica, listing_type_id=tipo, catalog_listing=catalogo)
        for logistica, tipo, catalogo in product(TipoLogistica, TipoAnuncioML, CatalogoListing)
    ]

TOTAL_VARRIDAS = sum(len(grupo) for grupo in GRUPOS.values())


def _pasta_empresa(empresa: str) -> str:
    if empresa not in NOME_PASTA_POR_EMPRESA:
        raise ValueError(f'Empresa inválida: "{empresa}". Use {list(NOME_PASTA_POR_EMPRESA)}.')
    return NOME_PASTA_POR_EMPRESA[empresa]


def _caminho_saida_json(empresa: str) -> Path:
    return RAIZ_APP / 'Arquivos_API' / _pasta_empresa(empresa) / 'lista_mlbs.json'


def _caminho_pasta_logs(empresa: str) -> Path:
    return RAIZ_APP / 'logs' / _pasta_empresa(empresa)


# Função Objetivo: Processa 1 varrida (chamada à API com paginação por scroll_id, já
# dentro de MlbsML.varrer) e devolve o resultado — não mexe em console nem em Progress,
# isso é 100% do chamador (thread principal).
def _processar_varrida(empresa_ativa: str, api_ml: ApiMercadoLivre, varrida: Varrida, pasta_logs) -> ResultadoVarrida:
    # * [EXPLICAÇÃO] → mesma correção já aplicada em calcular_grade_precificacao_ml.py e
    #                  buscar_comissao_real_ml.py (29/09/2026): core.empresa guarda a
    #                  empresa ativa em threading.local() — cada thread nova do
    #                  ThreadPoolExecutor nasce com esse estado vazio, mesmo a thread
    #                  principal já tendo chamado definir_empresa_ativa() antes.
    #                  empresa_ativa é lido 1x na thread principal (ver buscar_mlbs) e
    #                  repassado — barato, chamado 1x por varrida.
    definir_empresa_ativa(empresa_ativa)

    inicio_varrida = time.perf_counter()
    try:
        mlbs_varrida = api_ml.varrer_mlbs(varrida)
        erro = None
    except (ErroAPI, ErroAutenticacaoAPI) as e:
        mlbs_varrida = []
        erro = str(e)
    duracao_varrida = time.perf_counter() - inicio_varrida

    return ResultadoVarrida(
        varrida=varrida, mlbs_encontrados=mlbs_varrida,
        duracao_segundos=round(duracao_varrida, 2), erro=erro,
    )


def buscar_mlbs(empresa: str) -> RelatorioBuscaMlbs:
    """
    Ponto único de entrada. Busca todos os MLBs da empresa informada
    (EMPRESA_MAGAZINE ou EMPRESA_SAMVALE), salva lista_mlbs.json isolado
    por empresa, e devolve um relatório da execução.

    Exibição em blocos por status (28 combinações por bloco) — cada bloco
    fecha e fica no histórico do terminal antes do próximo abrir, exatamente
    como antes. Dentro de cada bloco, as até 28 varridas agora rodam
    concorrentes (ThreadPoolExecutor) em vez de 1 de cada vez. Precisa
    rodar com a empresa já ativa (definir_empresa_ativa) — quem chama isso
    é o management command.
    """
    pasta_logs = _caminho_pasta_logs(empresa)
    api_ml = ApiMercadoLivre(pasta_logs=pasta_logs, empresa=empresa)

    todos_mlbs: list[MlbEncontrado] = []
    varridas_com_resultado = 0
    varridas_sem_resultado = 0
    varridas_com_erro = 0
    detalhe_varridas: list[ResultadoVarrida] = []

    inicio_execucao = time.perf_counter()
    varridas_feitas = 0

    empresa_ativa = obter_empresa_ativa()  # lido 1x na thread principal, repassado pra cada worker

    for status, varridas_do_grupo in GRUPOS.items():
        decorrido = time.perf_counter() - inicio_execucao
        console.print(
            f"\n[bold]GRUPO: {status.value}[/bold]  "
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

            # * [EXPLICAÇÃO] → antes, cada tarefa era criada E iniciada 1 de cada vez,
            #                  junto com o processamento (mesmo ritmo sequencial da
            #                  chamada à API). Agora (29/09/2026) as até 28 tarefas do
            #                  bloco são criadas com start=False (igual antes), mas
            #                  iniciadas TODAS juntas, logo antes de submeter as 28 pro
            #                  ThreadPoolExecutor — reflete a execução concorrente real.
            #                  Formato visual em si (spinner, barra, coluna de resultado,
            #                  "⏳ na fila" até iniciar) não muda em nada — confirmado
            #                  como correto e funcional, mantido byte a byte.
            tarefas = {}
            for varrida in varridas_do_grupo:
                task_id = progress.add_task(varrida.label, total=1, resultado="⏳ na fila", start=False)
                tarefas[task_id] = varrida

            for task_id in tarefas:
                progress.start_task(task_id)
                progress.update(task_id, resultado="")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS_BUSCA_MLBS) as executor:
                futuros = {
                    executor.submit(_processar_varrida, empresa_ativa, api_ml, varrida, pasta_logs): task_id
                    for task_id, varrida in tarefas.items()
                }

                # * [EXPLICAÇÃO] → toda mutação do Progress (update/completed) só
                #                  acontece aqui, na thread principal, via as_completed —
                #                  nunca dentro de _processar_varrida (worker). Mesma
                #                  disciplina já usada em buscar_comissao_real_ml.py.
                for futuro in as_completed(futuros):
                    task_id = futuros[futuro]
                    varrida = tarefas[task_id]

                    try:
                        resultado = futuro.result()
                    except Exception as e:
                        resultado = ResultadoVarrida(varrida=varrida, erro=f"ERRO INESPERADO: {e}")

                    detalhe_varridas.append(resultado)

                    if resultado.erro:
                        varridas_com_erro += 1
                        progress.update(task_id, resultado="[red]✗ ERRO — ver .log[/red]")
                    elif resultado.encontrados:
                        todos_mlbs.extend(resultado.mlbs_encontrados)
                        varridas_com_resultado += 1
                        progress.update(task_id, resultado=f"{resultado.encontrados} MLBs")
                    else:
                        varridas_sem_resultado += 1
                        progress.update(task_id, resultado="sem resultado")

                    progress.update(task_id, completed=1)
                    varridas_feitas += 1

    duracao_total = time.perf_counter() - inicio_execucao

    caminho_json = _caminho_saida_json(empresa)
    caminho_json.parent.mkdir(parents=True, exist_ok=True)

    gerado_em = time.strftime("%Y-%m-%d %H:%M:%S")

    # * [EXPLICAÇÃO] → conversão manual pra dict antes do json.dump() (29/09/2026) —
    #                  garante que lista_mlbs.json mantém EXATAMENTE o mesmo formato de
    #                  antes (mesmas chaves, mesmos tipos primitivos: string, não Enum),
    #                  mesmo com a representação interna agora em dataclass. Esse JSON é
    #                  lido direto do disco por buscar_detalhes.py — qualquer deriva de
    #                  formato aqui quebraria esse outro script silenciosamente.
    resumo = {
        "gerado_em": gerado_em,
        "empresa": empresa,
        "total": len(todos_mlbs),
        "varridas_total": TOTAL_VARRIDAS,
        "varridas_com_resultado": varridas_com_resultado,
        "varridas_sem_resultado": varridas_sem_resultado,
        "varridas_com_erro": varridas_com_erro,
        "duracao_total_segundos": round(duracao_total, 2),
        "detalhe_varridas": [
            {
                "label": r.label,
                "encontrados": r.encontrados,
                "duracao_segundos": r.duracao_segundos,
                "erro": r.erro,
            }
            for r in detalhe_varridas
        ],
        "mlbs": [
            {
                "mlb": m.mlb,
                "status": m.status.value,
                "logistica": m.logistica.value,
                "tipo": m.tipo.value,
                "catalogo": m.catalogo.value,
            }
            for m in todos_mlbs
        ],
    }

    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    varridas_mais_lentas = sorted(detalhe_varridas, key=lambda r: r.duracao_segundos, reverse=True)[:5]

    console.print(f"\n[bold green]Concluído ({empresa}).[/bold green] Total: {len(todos_mlbs)} MLBs")
    resumo_linha = f"Varridas com resultado: {varridas_com_resultado} / {TOTAL_VARRIDAS}"
    if varridas_com_erro:
        resumo_linha += f"  •  [red]{varridas_com_erro} com erro[/red]"
    console.print(resumo_linha)
    console.print(f"Tempo total: {duracao_total:.1f}s")
    console.print("5 varridas mais lentas:")
    for r in varridas_mais_lentas:
        console.print(f"  {r.duracao_segundos:>6.2f}s — {r.label} ({r.encontrados} MLBs)")
    console.print(f"JSON: {caminho_json}")

    return RelatorioBuscaMlbs(
        empresa=empresa,
        gerado_em=gerado_em,
        total=len(todos_mlbs),
        varridas_total=TOTAL_VARRIDAS,
        varridas_com_resultado=varridas_com_resultado,
        varridas_sem_resultado=varridas_sem_resultado,
        varridas_com_erro=varridas_com_erro,
        duracao_total_segundos=round(duracao_total, 2),
        detalhe_varridas=detalhe_varridas,
        mlbs=todos_mlbs,
    )