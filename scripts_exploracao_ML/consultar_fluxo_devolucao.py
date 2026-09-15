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

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "MB"                       # "MB" ou "SV"
ORDER_ID = 2000018341680948        # numero do pedido que você já sabe ser devolução
MOSTRAR_JSON_CRU_DEVOLUCAO = True  # True = imprime o JSON cru da devolução (Etapa 2), sem
                                    # nenhuma tradução — útil pra investigar campo por campo,
                                    # ex: conferir o offset de fuso exato de cada data
# ========================================

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
NOME_LOG = "consultar_fluxo_devolucao"
HEADER_FORMATO_NOVO = {"x-format-new": "true"}
FUSO_HORARIO_EXIBICAO = ZoneInfo("America/Sao_Paulo")  # normaliza toda data exibida pra
                                                        # este fuso, já que a API do ML manda
                                                        # cada campo de data com um offset
                                                        # diferente (confirmado no JSON cru:
                                                        # date_created em +00:00, date_closed
                                                        # em -04:00, no mesmo objeto)


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
    print()
    print("=" * 78)
    print(f"ETAPA {numero} — {titulo}")
    print("=" * 78)


def campo(rotulo, valor):
    print(f"  {rotulo:<38}: {valor}")


def carregar_traducoes_de_envio():
    """Busca uma vez o dicionário oficial de status/sub-status de envio
    (GET /shipment_statuses) pra completar as traduções que não estão no
    SUBSTATUS_CONHECIDOS acima. Se essa chamada falhar, só avisa e segue —
    é um bônus, não um requisito do fluxo."""
    mapa = {}
    try:
        resposta = chamar_api(
            "GET", "/shipment_statuses",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            headers_extra=HEADER_FORMATO_NOVO,
            nome_log=NOME_LOG,
        )
        for status in resposta.json():
            for substatus in status.get("substatuses", []):
                mapa[substatus["id"]] = substatus["name"]
    except (ErroAPI, ErroAutenticacaoAPI):
        print("  (aviso: não consegui carregar o dicionário oficial de sub-status —")
        print("   sub-status desconhecidos vão aparecer só com o código original)")
    return mapa


def imprimir_timeline_envio(shipment_id, mapa_substatus):
    try:
        resposta = chamar_api(
            "GET", f"/shipments/{shipment_id}/history",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            headers_extra=HEADER_FORMATO_NOVO,
            nome_log=NOME_LOG,
        )
    except (ErroAPI, ErroAutenticacaoAPI) as erro:
        print(f"    (não consegui buscar o histórico deste envio: {erro})")
        return

    for evento in resposta.json():
        status_pt = traduzir(STATUS_ENVIO, evento.get("status"), "status de envio")
        sub_pt = nome_substatus(evento.get("substatus"), mapa_substatus)
        data_pt = formatar_data(evento.get("date")) if evento.get("date") else "?"
        print(f"    {data_pt:<22} {status_pt:<35} {sub_pt}")


try:
    imprimir_secao(0, "Carregando dicionário de tradução de sub-status de envio")
    mapa_substatus_oficial = carregar_traducoes_de_envio()
    if mapa_substatus_oficial:
        print(f"  OK — {len(mapa_substatus_oficial)} sub-status conhecidos pelo Mercado Livre carregados.")
    else:
        print("  Seguindo só com o dicionário manual do script.")

    # -----------------------------------------------------------------
    imprimir_secao(1, f"Buscando reclamação vinculada ao pedido {ORDER_ID}")
    resposta_claims = chamar_api(
        "GET", "/post-purchase/v1/claims/search",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={"order_id": ORDER_ID},
        nome_log=NOME_LOG,
    )
    claims = resposta_claims.json().get("data", [])

    if not claims:
        print("  Nenhuma reclamação encontrada pra esse pedido. Fim do fluxo aqui.")
        sys.exit(0)

    print(f"  {len(claims)} reclamação(ões) encontrada(s) nesse pedido:")
    for c in claims:
        print()
        campo("ID da reclamação", c.get("id"))
        campo("Tipo", traduzir(TIPO_RECLAMACAO, c.get("type"), "tipo de reclamação"))
        campo("Etapa", traduzir(ETAPA_RECLAMACAO, c.get("stage"), "etapa da reclamação"))
        campo("Status", traduzir(STATUS_RECLAMACAO, c.get("status"), "status da reclamação"))
        campo("Criada em", formatar_data(c.get("date_created")))

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

        if MOSTRAR_JSON_CRU_DEVOLUCAO:
            print()
            print("  --- JSON cru da devolução (sem tradução nenhuma) ---")
            print(json.dumps(devolucao, ensure_ascii=False, indent=2))
            print("  --- fim do JSON cru ---")

        break

    if devolucao is None:
        print()
        print("  Nenhuma das reclamações encontradas tem devolução associada. Fim do fluxo aqui.")
        sys.exit(0)

    print()
    print(f"  → Achei devolução na reclamação {claim_id} "
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
        print()
        print("  Itens envolvidos na devolução:")
        for item in itens_devolvidos:
            print(f"    - Item {item.get('item_id')}: devolvendo "
                  f"{formatar_quantidade(item.get('return_quantity'))} de "
                  f"{formatar_quantidade(item.get('total_quantity'))} unidade(s)")

    envios_da_devolucao = devolucao.get("shipments", [])
    shipment_id_volta_lista = []
    if envios_da_devolucao:
        print()
        print(f"  {len(envios_da_devolucao)} envio(s) de volta relacionados a essa devolução:")
        for envio in envios_da_devolucao:
            print()
            campo("  ID do envio de volta", envio.get("shipment_id"))
            campo("  Tipo dessa perna", traduzir(TIPO_ENVIO_DEVOLUCAO, envio.get("type"), "tipo de envio de devolução"))
            campo("  Status", traduzir(STATUS_ENVIO_DEVOLUCAO, envio.get("status"), "status do envio de devolução"))
            campo("  Indo para", traduzir(DESTINO_ENVIO_DEVOLUCAO, (envio.get("destination") or {}).get("name"), "destino"))
            campo("  Rastreio", envio.get("tracking_number") or "sem rastreio")
            shipment_id_volta_lista.append(envio.get("shipment_id"))
    else:
        print("  Nenhum envio de volta registrado ainda pra essa devolução.")

    # -----------------------------------------------------------------
    imprimir_secao(3, f"Buscando dados do pedido original ({ORDER_ID})")
    resposta_pedido = chamar_api(
        "GET", f"/orders/{ORDER_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log=NOME_LOG,
    )
    pedido = resposta_pedido.json()

    comprador = pedido.get("buyer") or {}
    nome_comprador = " ".join(filter(None, [comprador.get("first_name"), comprador.get("last_name")])) \
        or "(nome não informado)"
    campo("Comprador", nome_comprador)
    campo("Status do pedido", traduzir(STATUS_PEDIDO, pedido.get("status"), "status de pedido"))
    campo("Criado em", formatar_data(pedido.get("date_created")))

    print()
    print("  Itens do pedido:")
    for item in pedido.get("order_items", []):
        titulo = (item.get("item") or {}).get("title", "?")
        qtd = item.get("quantity")
        preco = item.get("unit_price")
        moeda = pedido.get("currency_id", "")
        print(f"    - {qtd}x {titulo} — {preco} {moeda} cada")

    shipping_info = pedido.get("shipping") or {}
    shipping_id_ida = shipping_info.get("id")
    print()
    campo("ID do envio de ida", shipping_id_ida or "(pedido sem envio gerenciado pelo ML)")

    if not shipping_id_ida:
        print()
        print("Fim do fluxo — esse pedido não tem envio de ida gerenciado pelo Mercado Livre.")
        sys.exit(0)

    # -----------------------------------------------------------------
    imprimir_secao(4, f"Buscando envio de ida (entrega ao cliente) — {shipping_id_ida}")
    resposta_envio_ida = chamar_api(
        "GET", f"/shipments/{shipping_id_ida}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        headers_extra=HEADER_FORMATO_NOVO,
        nome_log=NOME_LOG,
    )
    envio_ida = resposta_envio_ida.json()

    logistic = envio_ida.get("logistic") or {}
    eh_full = logistic.get("type") == "fulfillment"
    campo("Tipo de logística", "FULL (saiu de centro de distribuição do Mercado Livre)"
          if eh_full else "Comum (você mesmo despachou)")
    campo("Status atual", traduzir(STATUS_ENVIO, envio_ida.get("status"), "status de envio"))
    campo("Destinatário", (envio_ida.get("destination") or {}).get("receiver_name", "—"))
    campo("Última atualização", formatar_data(envio_ida.get("last_updated")))

    print()
    print("  Linha do tempo completa do envio de ida:")
    imprimir_timeline_envio(shipping_id_ida, mapa_substatus_oficial)

    # -----------------------------------------------------------------
    imprimir_secao(5, "Linha do tempo do(s) envio(s) de volta")
    if shipment_id_volta_lista:
        for shipment_id_volta in shipment_id_volta_lista:
            print(f"\n  Envio de volta {shipment_id_volta}:")
            imprimir_timeline_envio(shipment_id_volta, mapa_substatus_oficial)
    else:
        print("  (pulado — nenhum envio de volta foi encontrado na Etapa 2)")

    print()
    print("=" * 78)
    print("Fim do fluxo.")
    print("=" * 78)

except (ErroAPI, ErroAutenticacaoAPI) as erro:
    print(f"\nErro ao chamar a API: {erro}")