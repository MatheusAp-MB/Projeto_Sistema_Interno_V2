# scripts_exploracao_ML/buscar_reclamacoes_candidatas.py
#
# Busca reclamações JÁ ENCERRADAS (status=closed) de um vendedor, dentro de
# uma janela de datas no passado, pra levantar candidatos de pedidos com
# devolução/mediação já totalmente concluídos -- prontos pra rodar o
# consultar_fluxo_devolucao.py em cima e ver o histórico ponta a ponta.
#
# So leitura. Nao grava nada no banco nem em arquivo -- so imprime na tela.
#
# Endpoint: GET /post-purchase/v1/claims/search (doc "Gerenciar Reclamações")
#   Filtro mínimo obrigatório quando não se busca por order_id/pack_id:
#   players.user_id + players.role (sempre em par). Demais filtros usados
#   aqui: status=closed, range=date_created:after:...,before:... (formato
#   exigido: milissegundos obrigatórios, offset sem dois-pontos, ex:
#   2026-07-15T00:00:00.000-0300), sort=date_created:desc.
#
# players.user_id vem do MESMO .env que o resto do projeto já usa
# ({CONTA}_USER_ID) -- mesmo padrão de
# integracao_mercado_livre/servicos/buscar_mlbs.py, não precisa configurar
# de novo aqui.

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"             # "MB" ou "SV"
DIAS_ATRAS_INICIO = 75   # início da janela de busca (mais antigo)
DIAS_ATRAS_FIM = 45      # fim da janela (mais recente) -- 45 dias de folga
                         # até hoje pra qualquer devolução/mediação já ter
                         # concluído de verdade
TIPO_RECLAMACAO_FILTRO = None  # None = todos os tipos; ou "mediations",
                                # "return", "fulfillment" etc. pra ver só 1 tipo
LIMITE_POR_PAGINA = 50   # máximo aceito pela API é 100
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
PASTA_LOGS.mkdir(parents=True, exist_ok=True)
NOME_LOG = "buscar_reclamacoes_candidatas"
FUSO_HORARIO_EXIBICAO = ZoneInfo("America/Sao_Paulo")

console = Console()

TIPO_RECLAMACAO = {
    "mediations": "Mediação (comprador abriu disputa)",
    "return": "Devolução",
    "fulfillment": "Devolução de envio FULL",
    "ml_case": "Caso aberto pelo Mercado Livre",
    "cancel_sale": "Cancelamento de venda",
    "cancel_purchase": "Cancelamento de compra",
    "change": "Troca de produto",
    "service": "Reclamação de serviço",
}

RECURSO = {
    "order": "Pedido",
    "shipment": "Envio",
    "payment": "Pagamento",
    "purchase": "Compra",
}


def _obter_user_id(conta: str) -> str:
    # Mesmo padrão de integracao_mercado_livre/servicos/buscar_mlbs.py --
    # reaproveita o {CONTA}_USER_ID que já existe no .env da raiz do repo,
    # em vez de pedir isso de novo aqui.
    load_dotenv()
    user_id = os.getenv(f"{conta}_USER_ID")
    if not user_id:
        raise RuntimeError(
            f'{conta}_USER_ID não encontrado no .env da raiz do repo — '
            f'adicione a linha {conta}_USER_ID=seu_user_id_aqui.'
        )
    return user_id


def formatar_data_para_filtro(instante):
    """Formata um datetime pro formato exato que o parâmetro 'range' da
    API exige: milissegundos obrigatórios, offset sem dois-pontos (ex:
    2026-07-15T00:00:00.000-0300), conforme o exemplo da doc oficial."""
    texto = instante.isoformat(timespec="milliseconds")
    return texto[:-6] + texto[-6:].replace(":", "")


def formatar_data_exibicao(valor_iso):
    if not valor_iso:
        return "—"
    try:
        instante = datetime.fromisoformat(valor_iso)
    except ValueError:
        return valor_iso
    instante = instante.astimezone(FUSO_HORARIO_EXIBICAO)
    return instante.strftime("%d/%m/%Y às %H:%M")


agora = datetime.now(FUSO_HORARIO_EXIBICAO)
inicio_janela = agora - timedelta(days=DIAS_ATRAS_INICIO)
fim_janela = agora - timedelta(days=DIAS_ATRAS_FIM)

try:
    user_id = _obter_user_id(CONTA)

    console.print()
    console.print(f"[bold blue]Buscando reclamações ENCERRADAS da conta {CONTA} (vendedor {user_id})[/bold blue]")
    console.print(f"  Janela: {inicio_janela.strftime('%d/%m/%Y')} até {fim_janela.strftime('%d/%m/%Y')}"
                  + (f" | tipo: {TIPO_RECLAMACAO_FILTRO}" if TIPO_RECLAMACAO_FILTRO else " | todos os tipos"))

    params = {
        "players.user_id": user_id,
        "players.role": "respondent",
        "status": "closed",
        "range": (
            f"date_created:after:{formatar_data_para_filtro(inicio_janela)},"
            f"before:{formatar_data_para_filtro(fim_janela)}"
        ),
        "sort": "date_created:desc",
        "limit": LIMITE_POR_PAGINA,
        "offset": 0,
    }
    if TIPO_RECLAMACAO_FILTRO:
        params["type"] = TIPO_RECLAMACAO_FILTRO

    with console.status("[bold green]Consultando /post-purchase/v1/claims/search...[/bold green]", spinner="dots"):
        resposta = chamar_api(
            "GET", "/post-purchase/v1/claims/search",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            params=params,
            nome_log=NOME_LOG,
        )

    dados = resposta.json()
    total = dados.get("paging", {}).get("total", 0)
    claims = dados.get("data", [])

    console.print(f"  {total} reclamação(ões) encerrada(s) no total nessa janela "
                  f"(mostrando até {LIMITE_POR_PAGINA} mais recentes).")

    if not claims:
        console.print("  Nenhuma reclamação encontrada nesse período. Ajuste "
                      "DIAS_ATRAS_INICIO/DIAS_ATRAS_FIM e tente de novo.")
        sys.exit(0)

    tabela = Table(box=box.SIMPLE_HEAD, header_style="bold")
    tabela.add_column("Recurso")
    tabela.add_column("Order/Resource ID")
    tabela.add_column("Claim ID")
    tabela.add_column("Tipo")
    tabela.add_column("Etapa")
    tabela.add_column("Encerrada em")
    for c in claims:
        tabela.add_row(
            escape(RECURSO.get(c.get("resource"), c.get("resource") or "—")),
            str(c.get("resource_id")),
            str(c.get("id")),
            escape(TIPO_RECLAMACAO.get(c.get("type"), c.get("type") or "—")),
            escape(c.get("stage") or "—"),
            formatar_data_exibicao(c.get("date_created")),
        )
    console.print()
    console.print(tabela)
    console.print()
    console.print("  Linhas com Recurso = \"Pedido\" têm o ID diretamente utilizável "
                  "como ORDER_ID em consultar_fluxo_devolucao.py.")

except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f"\n[bold red]Erro ao chamar a API:[/bold red] {escape(str(erro))}")