# scripts_exploracao_ML/consultar_fluxo_devolucao.py
#
# Dado um numero de pedido que voce ja sabe ser uma devolucao, percorre a
# cadeia de recursos da API do Mercado Livre (reclamacao -> devolucao ->
# pedido -> envio de ida -> envio(s) de volta) e imprime no terminal, uma
# etapa de cada vez, o que cada resposta trouxe -- com rotulos em
# portugues, nunca o nome cru do campo da API.
#
# So leitura. Nao grava nada no banco nem em arquivo -- so imprime na tela.
#
# Endpoints chamados, nesta ordem:
#   0. GET /shipment_statuses                              (uma vez, bonus de traducao)
#   1. GET /post-purchase/v1/claims/search?order_id=...
#   2. GET /post-purchase/v2/claims/$CLAIM_ID/returns   (tenta cada reclamação
#      encontrada até achar uma com devolução — "type" sozinho não é confiável,
#      ver comentário no código)
#   3. GET /orders/$ORDER_ID
#   4. GET /shipments/$SHIPPING_ID_IDA                       (header x-format-new)
#      GET /shipments/$SHIPPING_ID_IDA/history                (header x-format-new)
#   5. GET /shipments/$SHIPPING_ID_VOLTA/history               (um por perna de volta)
#
# Exige o chamar_api() já aceitando headers_extra (mudança aplicada antes
# do script investigar_shipment.py).
#
# JSON cru de cada uma dessas chamadas aparece quando MOSTRAR_JSON_CRU = True.
# Toda a saída do terminal usa a lib rich (painéis, tabelas, JSON colorido,
# spinner enquanto cada chamada está em andamento).

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                # "MB" ou "SV"
ORDER_ID = 2000017597909662 # numero do pedido que você já sabe ser devolução
MOSTRAR_JSON_CRU = True     # True = imprime o JSON cru de TODAS as etapas (0 a 5), sem
                             # nenhuma tradução — útil pra investigar campo por campo
                             # qualquer resposta da API, não só a devolução
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
PASTA_LOGS.mkdir(parents=True, exist_ok=True)  # garante que a pasta existe mesmo se o
                                                # script quebrar antes da 1ª chamada de API
NOME_LOG = "consultar_fluxo_devolucao"
HEADER_FORMATO_NOVO = {"x-format-new": "true"}
FUSO_HORARIO_EXIBICAO = ZoneInfo("America/Sao_Paulo")  # normaliza toda data exibida pra
                                                        # este fuso, já que a API do ML manda
                                                        # cada campo de data com um offset
                                                        # diferente (confirmado no JSON cru:
                                                        # date_created em +00:00, date_closed
                                                        # em -04:00, no mesmo objeto)
ARQUIVO_SAIDA_CONSOLE = PASTA_LOGS / "saida_console.txt"  # tudo que aparece no terminal
                                                           # também é salvo aqui (sobrescrito
                                                           # a cada execução), pra poder
                                                           # copiar/mandar quando não coube
                                                           # no console
console = Console(record=True)  # record=True é o que permite exportar tudo depois


# ---------------------------------------------------------------------------
# Traduções: código da API -> texto entendível. Tiradas direto da
# documentação oficial (Gerenciar Reclamações, Devoluções, Envios). Um
# código que aparecer e não estiver aqui é mostrado com o código original e
# um aviso "(sem tradução conhecida)" — nunca inventamos texto pra um valor
# que a gente não confirmou na doc.
# ---------------------------------------------------------------------------

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

ETAPA_RECLAMACAO = {
    "claim": "Reclamação simples",
    "dispute": "Disputa/mediação",
    "recontact": "Recontato (reaberta)",
    "stale": "Parada/inativa",
    "none": "Sem etapa definida",
}

STATUS_RECLAMACAO = {
    "opened": "Aberta",
    "closed": "Fechada",
}

STATUS_DINHEIRO = {
    "retained": "Retido na sua conta (aguardando desfecho)",
    "refunded": "Devolvido ao comprador",
    "available": "Liberado / disponível pra você",
}

QUANDO_REEMBOLSA = {
    "shipped": "assim que o comprador despachar a devolução",
    "delivered": "3 dias depois de você receber a devolução de volta",
    "n/a": "não se aplica (caso sem devolução física do produto)",
}

TIPO_RECURSO = {
    "order": "Pedido",
    "claim": "Reclamação",
    "shipment": "Envio",
    "other": "Outro",
}

# Status GERAL da devolução (campo "status" do /v2/claims/$ID/returns) —
# esse é o campo mais importante e tinha ficado de fora da primeira
# versão do script; achei o dicionário completo revisando a doc de novo.
STATUS_DEVOLUCAO = {
    "pending_cancel": "Em processo de cancelamento",
    "pending": "Criada, gerando o envio de volta",
    "failed": "Falha ao criar/gerar o envio de volta",
    "shipped": "Enviada de volta — dinheiro retido",
    "pending_delivered": "Em processo de confirmar entrega",
    "return_to_buyer": "Retornando ao comprador",
    "pending_expiration": "Em processo de expiração",
    "scheduled": "Retirada programada",
    "pending_failure": "Em processo de registrar falha",
    "label_generated": "Etiqueta gerada — pronta pra envio",
    "cancelled": "Cancelada — dinheiro disponível",
    "not_delivered": "Não entregue",
    "expired": "Expirada",
    "delivered": "Nas suas mãos (você já recebeu de volta)",
}

SUBTIPO_DEVOLUCAO = {
    "low_cost": "Devolução automática (low cost)",
    "return_partial": "Devolução parcial",
    "return_total": "Devolução total",
}

STATUS_ENVIO_DEVOLUCAO = {
    "pending": "Aguardando geração do envio",
    "ready_to_ship": "Etiqueta pronta pra despacho",
    "shipped": "Despachado",
    "not_delivered": "Não entregue",
    "delivered": "Entregue",
    "cancelled": "Cancelado",
}

TIPO_ENVIO_DEVOLUCAO = {
    "return": "Envio de volta (comprador/CD → depósito Mercado Livre)",
    "return_from_triage": "Envio de triagem (depósito → revisão interna)",
}

DESTINO_ENVIO_DEVOLUCAO = {
    "seller_address": "Seu endereço (vendedor)",
    "warehouse": "Depósito do Mercado Livre",
}

STATUS_PEDIDO = {
    "confirmed": "Confirmado",
    "payment_required": "Aguardando pagamento",
    "payment_in_process": "Pagamento em processamento",
    "paid": "Pago",
    "cancelled": "Cancelado",
    "invalid": "Inválido",
}

# Nomes curtos de propósito (≤20 caracteres) pra alinhar bonitinho na
# coluna da linha do tempo — o detalhe fica por conta do sub-status ao lado.
STATUS_ENVIO = {
    "to_be_agreed": "A combinar",
    "pending": "Pendente",
    "handling": "Em processamento",
    "ready_to_ship": "Pronto pra envio",
    "shipped": "Despachado",
    "delivered": "Entregue",
    "not_delivered": "Não entregue",
    "cancelled": "Cancelado",
}

# Sub-status mais comuns, já confirmados na doc/nos testes reais (envio de
# ida e de volta). Qualquer outro vem do /shipment_statuses (bônus, ver
# carregar_traducoes_de_envio).
SUBSTATUS_CONHECIDOS = {
    "ready_to_print": "Etiqueta pronta pra impressão",
    "printed": "Etiqueta impressa",
    "in_warehouse": "No depósito/CD",
    "ready_to_pack": "Pronto pra embalar",
    "packed": "Embalado",
    "in_packing_list": "Na lista de coleta (romaneio)",
    "first_visit": "1ª tentativa de entrega",
    "second_visit": "2ª tentativa de entrega",
    "invoice_pending": "Aguardando nota fiscal",
    "waiting_for_label_generation": "Aguardando geração da etiqueta",
    "in_pickup_list": "Na lista de coleta pra retirada",
    "dropped_off": "Deixado em ponto de coleta pelo comprador",
    "picked_up": "Coletado pela transportadora",
    "in_hub": "No hub de triagem da transportadora",
}


def formatar_data(valor_iso):
    """Formata uma data ISO 8601 da API (ex: '2026-09-14T17:21:43.611+00:00')
    pro formato dd/MM/yyyy às HH:mm. Se não conseguir interpretar (valor
    vazio, já é um texto tipo '—', ou formato inesperado), devolve o valor
    original sem travar o script."""
    if not valor_iso or not isinstance(valor_iso, str):
        return valor_iso or "—"
    try:
        instante = datetime.fromisoformat(valor_iso)
    except ValueError:
        return valor_iso
    instante = instante.astimezone(FUSO_HORARIO_EXIBICAO)
    return instante.strftime("%d/%m/%Y às %H:%M")


def traduzir(dicionario, codigo, rotulo_generico="valor"):
    """Traduz um código da API pro texto entendível. Se não tiver no
    dicionário, mostra o código cru com um aviso em vez de arriscar um chute."""
    if codigo is None:
        return "—"
    return dicionario.get(codigo, f"{codigo} (sem tradução conhecida — {rotulo_generico})")


def formatar_quantidade(valor):
    """A API manda quantidade como texto tipo '1.0' — mostra '1' quando é
    um número redondo, e mantém a casa decimal só quando ela importa (ex:
    '0.5', pra produto vendido fracionado)."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor
    return str(int(numero)) if numero.is_integer() else str(numero)


def nome_substatus(substatus_id, mapa_oficial):
    if substatus_id is None:
        return "—"
    if substatus_id in SUBSTATUS_CONHECIDOS:
        return SUBSTATUS_CONHECIDOS[substatus_id]
    if substatus_id in mapa_oficial:
        return f"{mapa_oficial[substatus_id]} (nome oficial do ML, em inglês)"
    return f"{substatus_id} (sem tradução conhecida)"


def imprimir_secao(numero, titulo):
    console.print()
    console.print(Panel(titulo, title=f"ETAPA {numero}", title_align="left", border_style="bold blue", expand=False))


def campo(rotulo, valor):
    console.print(f"  [bold cyan]{rotulo:<38}[/bold cyan]: {escape(str(valor))}")


def imprimir_json_cru(rotulo, dados):
    """Imprime o JSON cru de uma resposta da API, sem nenhuma tradução —
    controlado pela flag MOSTRAR_JSON_CRU, pra poder investigar campo por
    campo qualquer etapa do fluxo (não só a devolução) quando o dicionário
    de tradução do script não é suficiente."""
    if not MOSTRAR_JSON_CRU:
        return
    texto_json = json.dumps(dados, ensure_ascii=False, indent=2)
    console.print()
    console.print(Panel(
        Syntax(texto_json, "json", theme="ansi_dark", word_wrap=True, background_color="default"),
        title=f"JSON cru — {rotulo}",
        title_align="left",
        border_style="grey42",
    ))


def carregar_traducoes_de_envio():
    """Busca uma vez o dicionário oficial de status/sub-status de envio
    (GET /shipment_statuses) pra completar as traduções que não estão no
    SUBSTATUS_CONHECIDOS acima. Se essa chamada falhar, só avisa e segue —
    é um bônus, não um requisito do fluxo."""
    mapa = {}
    with console.status("[bold green]Carregando dicionário oficial de status de envio...[/bold green]", spinner="dots"):
        try:
            resposta = chamar_api(
                "GET", "/shipment_statuses",
                pasta_logs=PASTA_LOGS, conta=CONTA,
                headers_extra=HEADER_FORMATO_NOVO,
                nome_log=NOME_LOG,
            )
        except (ErroAPI, ErroAutenticacaoAPI):
            resposta = None

    if resposta is None:
        console.print("  [yellow](aviso: não consegui carregar o dicionário oficial de sub-status —[/yellow]")
        console.print("   [yellow]sub-status desconhecidos vão aparecer só com o código original)[/yellow]")
        return mapa

    dados = resposta.json()
    imprimir_json_cru("dicionário de status de envio (/shipment_statuses)", dados)
    for status in dados:
        for substatus in status.get("substatuses", []):
            mapa[substatus["id"]] = substatus["name"]
    return mapa


def imprimir_timeline_envio(shipment_id, mapa_substatus):
    with console.status(f"[bold green]Buscando histórico do envio {shipment_id}...[/bold green]", spinner="dots"):
        try:
            resposta = chamar_api(
                "GET", f"/shipments/{shipment_id}/history",
                pasta_logs=PASTA_LOGS, conta=CONTA,
                headers_extra=HEADER_FORMATO_NOVO,
                nome_log=NOME_LOG,
            )
        except (ErroAPI, ErroAutenticacaoAPI) as erro:
            console.print(f"    [red](não consegui buscar o histórico deste envio: {escape(str(erro))})[/red]")
            return

    eventos = resposta.json()
    imprimir_json_cru(f"histórico do envio {shipment_id} (/shipments/{shipment_id}/history)", eventos)

    tabela = Table(box=box.SIMPLE_HEAD, header_style="bold")
    tabela.add_column("Data")
    tabela.add_column("Status")
    tabela.add_column("Sub-status")
    for evento in eventos:
        status_pt = traduzir(STATUS_ENVIO, evento.get("status"), "status de envio")
        sub_pt = nome_substatus(evento.get("substatus"), mapa_substatus)
        data_pt = formatar_data(evento.get("date")) if evento.get("date") else "?"
        tabela.add_row(data_pt, escape(status_pt), escape(sub_pt))
    console.print(tabela)


try:
    imprimir_secao(0, "Carregando dicionário de tradução de sub-status de envio")
    mapa_substatus_oficial = carregar_traducoes_de_envio()
    if mapa_substatus_oficial:
        console.print(f"  [green]OK[/green] — {len(mapa_substatus_oficial)} sub-status conhecidos pelo Mercado Livre carregados.")
    else:
        console.print("  Seguindo só com o dicionário manual do script.")

    # -----------------------------------------------------------------
    imprimir_secao(1, f"Buscando reclamação vinculada ao pedido {ORDER_ID}")
    with console.status(f"[bold green]Buscando reclamações do pedido {ORDER_ID}...[/bold green]", spinner="dots"):
        resposta_claims = chamar_api(
            "GET", "/post-purchase/v1/claims/search",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            params={"order_id": ORDER_ID},
            nome_log=NOME_LOG,
        )
    dados_claims = resposta_claims.json()
    imprimir_json_cru("busca de reclamações (/post-purchase/v1/claims/search)", dados_claims)
    claims = dados_claims.get("data", [])

    if not claims:
        console.print("  Nenhuma reclamação encontrada pra esse pedido. Fim do fluxo aqui.")
        sys.exit(0)

    tabela_claims = Table(title=f"{len(claims)} reclamação(ões) encontrada(s) nesse pedido", box=box.SIMPLE_HEAD, header_style="bold")
    tabela_claims.add_column("ID")
    tabela_claims.add_column("Tipo")
    tabela_claims.add_column("Etapa")
    tabela_claims.add_column("Status")
    tabela_claims.add_column("Criada em")
    for c in claims:
        tabela_claims.add_row(
            str(c.get("id")),
            escape(traduzir(TIPO_RECLAMACAO, c.get("type"), "tipo de reclamação")),
            escape(traduzir(ETAPA_RECLAMACAO, c.get("stage"), "etapa da reclamação")),
            escape(traduzir(STATUS_RECLAMACAO, c.get("status"), "status da reclamação")),
            formatar_data(c.get("date_created")),
        )
    console.print(tabela_claims)

    # IMPORTANTE (achado testando com pedido real): o campo "type" da
    # reclamação NÃO é confiável pra saber se ela tem devolução — uma
    # devolução que virou disputa aparece como type "mediations", não
    # "return"/"fulfillment". Então, em vez de confiar só no "type", a
    # gente tenta de fato o endpoint de devolução em cada reclamação
    # encontrada (começando pelas de type return/fulfillment, só como
    # prioridade de tentativa) e usa a primeira que responder com sucesso.
    claims_em_ordem_de_tentativa = sorted(
        claims, key=lambda c: 0 if c.get("type") in ("return", "fulfillment") else 1
    )

    devolucao = None
    claim_id = None
    for candidata in claims_em_ordem_de_tentativa:
        with console.status(f"[bold green]Verificando devolução na reclamação {candidata['id']}...[/bold green]", spinner="dots"):
            try:
                resposta_devolucao = chamar_api(
                    "GET", f"/post-purchase/v2/claims/{candidata['id']}/returns",
                    pasta_logs=PASTA_LOGS, conta=CONTA,
                    nome_log=NOME_LOG,
                )
            except (ErroAPI, ErroAutenticacaoAPI):
                continue  # essa reclamação não tem devolução associada — tenta a próxima
        devolucao = resposta_devolucao.json()
        claim_id = candidata["id"]
        imprimir_json_cru(f"devolução da reclamação {claim_id} (/post-purchase/v2/claims/{claim_id}/returns)", devolucao)
        break

    if devolucao is None:
        console.print()
        console.print("  Nenhuma das reclamações encontradas tem devolução associada. Fim do fluxo aqui.")
        sys.exit(0)

    console.print()
    console.print(f"  → Achei devolução na reclamação {claim_id} "
          f"({traduzir(TIPO_RECLAMACAO, next(c for c in claims if c['id'] == claim_id).get('type'))})")

    # -----------------------------------------------------------------
    imprimir_secao(2, f"Detalhes da devolução (reclamação {claim_id})")

    campo("ID da devolução", devolucao.get("id"))
    campo("Status da devolução", traduzir(STATUS_DEVOLUCAO, devolucao.get("status"), "status de devolução"))
    campo("Subtipo da devolução", traduzir(SUBTIPO_DEVOLUCAO, devolucao.get("subtype"), "subtipo de devolução"))
    campo("Última atualização", formatar_data(devolucao.get("last_updated")))
    campo("Criada em", formatar_data(devolucao.get("date_created")))
    campo("Encerrada em", formatar_data(devolucao.get("date_closed")) if devolucao.get("date_closed") else "ainda em aberto")
    campo("Situação do dinheiro", traduzir(STATUS_DINHEIRO, devolucao.get("status_money"), "status do dinheiro"))
    campo("Quando o reembolso libera", traduzir(QUANDO_REEMBOLSA, devolucao.get("refund_at"), "regra de reembolso"))
    campo("Ligada a que tipo de recurso", traduzir(TIPO_RECURSO, devolucao.get("resource_type"), "tipo de recurso"))

    itens_devolvidos = devolucao.get("orders", [])
    if itens_devolvidos:
        tabela_itens = Table(title="Itens envolvidos na devolução", box=box.SIMPLE_HEAD, header_style="bold")
        tabela_itens.add_column("Item ID")
        tabela_itens.add_column("Devolvendo")
        tabela_itens.add_column("De")
        for item in itens_devolvidos:
            tabela_itens.add_row(
                str(item.get("item_id")),
                formatar_quantidade(item.get("return_quantity")),
                f"{formatar_quantidade(item.get('total_quantity'))} unidade(s)",
            )
        console.print()
        console.print(tabela_itens)

    envios_da_devolucao = devolucao.get("shipments", [])
    shipment_id_volta_lista = []
    if envios_da_devolucao:
        tabela_envios_volta = Table(title=f"{len(envios_da_devolucao)} envio(s) de volta relacionados a essa devolução", box=box.SIMPLE_HEAD, header_style="bold")
        tabela_envios_volta.add_column("ID do envio")
        tabela_envios_volta.add_column("Tipo dessa perna")
        tabela_envios_volta.add_column("Status")
        tabela_envios_volta.add_column("Indo para")
        tabela_envios_volta.add_column("Rastreio")
        for envio in envios_da_devolucao:
            tabela_envios_volta.add_row(
                str(envio.get("shipment_id")),
                escape(traduzir(TIPO_ENVIO_DEVOLUCAO, envio.get("type"), "tipo de envio de devolução")),
                escape(traduzir(STATUS_ENVIO_DEVOLUCAO, envio.get("status"), "status do envio de devolução")),
                escape(traduzir(DESTINO_ENVIO_DEVOLUCAO, (envio.get("destination") or {}).get("name"), "destino")),
                envio.get("tracking_number") or "sem rastreio",
            )
            shipment_id_volta_lista.append(envio.get("shipment_id"))
        console.print()
        console.print(tabela_envios_volta)
    else:
        console.print("  Nenhum envio de volta registrado ainda pra essa devolução.")

    # -----------------------------------------------------------------
    imprimir_secao(3, f"Buscando dados do pedido original ({ORDER_ID})")
    with console.status(f"[bold green]Buscando pedido {ORDER_ID}...[/bold green]", spinner="dots"):
        resposta_pedido = chamar_api(
            "GET", f"/orders/{ORDER_ID}",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            nome_log=NOME_LOG,
        )
    pedido = resposta_pedido.json()
    imprimir_json_cru(f"pedido {ORDER_ID} (/orders/{ORDER_ID})", pedido)

    comprador = pedido.get("buyer") or {}
    nome_comprador = " ".join(filter(None, [comprador.get("first_name"), comprador.get("last_name")])) \
        or "(nome não informado)"
    campo("Comprador", nome_comprador)
    campo("Status do pedido", traduzir(STATUS_PEDIDO, pedido.get("status"), "status de pedido"))
    campo("Criado em", formatar_data(pedido.get("date_created")))

    tabela_itens_pedido = Table(title="Itens do pedido", box=box.SIMPLE_HEAD, header_style="bold")
    tabela_itens_pedido.add_column("Qtd")
    tabela_itens_pedido.add_column("Título")
    tabela_itens_pedido.add_column("Preço unitário")
    for item in pedido.get("order_items", []):
        titulo = (item.get("item") or {}).get("title", "?")
        qtd = item.get("quantity")
        preco = item.get("unit_price")
        moeda = pedido.get("currency_id", "")
        tabela_itens_pedido.add_row(str(qtd), escape(titulo), f"{preco} {moeda}")
    console.print()
    console.print(tabela_itens_pedido)

    shipping_info = pedido.get("shipping") or {}
    shipping_id_ida = shipping_info.get("id")
    console.print()
    campo("ID do envio de ida", shipping_id_ida or "(pedido sem envio gerenciado pelo ML)")

    if not shipping_id_ida:
        console.print()
        console.print("Fim do fluxo — esse pedido não tem envio de ida gerenciado pelo Mercado Livre.")
        sys.exit(0)

    # -----------------------------------------------------------------
    imprimir_secao(4, f"Buscando envio de ida (entrega ao cliente) — {shipping_id_ida}")
    with console.status(f"[bold green]Buscando envio {shipping_id_ida}...[/bold green]", spinner="dots"):
        resposta_envio_ida = chamar_api(
            "GET", f"/shipments/{shipping_id_ida}",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            headers_extra=HEADER_FORMATO_NOVO,
            nome_log=NOME_LOG,
        )
    envio_ida = resposta_envio_ida.json()
    imprimir_json_cru(f"envio de ida {shipping_id_ida} (/shipments/{shipping_id_ida})", envio_ida)

    logistic = envio_ida.get("logistic") or {}
    eh_full = logistic.get("type") == "fulfillment"
    campo("Tipo de logística", "FULL (saiu de centro de distribuição do Mercado Livre)"
          if eh_full else "Comum (você mesmo despachou)")
    campo("Status atual", traduzir(STATUS_ENVIO, envio_ida.get("status"), "status de envio"))
    campo("Destinatário", (envio_ida.get("destination") or {}).get("receiver_name", "—"))
    campo("Última atualização", formatar_data(envio_ida.get("last_updated")))

    console.print()
    console.print("  Linha do tempo completa do envio de ida:")
    imprimir_timeline_envio(shipping_id_ida, mapa_substatus_oficial)

    # -----------------------------------------------------------------
    imprimir_secao(5, "Linha do tempo do(s) envio(s) de volta")
    if shipment_id_volta_lista:
        for shipment_id_volta in shipment_id_volta_lista:
            console.print(f"\n  Envio de volta {shipment_id_volta}:")
            imprimir_timeline_envio(shipment_id_volta, mapa_substatus_oficial)
    else:
        console.print("  (pulado — nenhum envio de volta foi encontrado na Etapa 2)")

    console.print()
    console.print(Panel("Fim do fluxo.", border_style="bold blue", expand=False))

except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f"\n[bold red]Erro ao chamar a API:[/bold red] {escape(str(erro))}")

finally:
    # roda sempre — mesmo se o script quebrar com uma exceção que não é
    # ErroAPI/ErroAutenticacaoAPI (ex: um bug no próprio script) — pra nunca
    # perder a saída de uma execução que travou no meio do caminho
    console.save_text(str(ARQUIVO_SAIDA_CONSOLE), styles=False)
    print(f"\n(saída completa também salva em: {ARQUIVO_SAIDA_CONSOLE})")