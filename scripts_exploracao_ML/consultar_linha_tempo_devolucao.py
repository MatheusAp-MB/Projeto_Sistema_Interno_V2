# scripts_exploracao_ML/consultar_linha_tempo_devolucao.py
#
# Dado um numero de pedido de devolucao, busca na API do Mercado Livre so os
# campos que compoem a linha do tempo das 4 etapas do fluxo de devolucao
# (Compra -> Reclamacao -> Devolucao fisica -> Decisao) e imprime CADA CAMPO
# em 1 linha, sem JSON cru, sem tabela de itens, sem historico completo de
# envio -- so o que interessa pra comparar candidatos.
#
# Formato de cada linha:
#   Rotulo (campo.da.api): valor real
#
# Campo marcado com "(mapeamento nao confirmado)" = ainda nao temos certeza
# de que endpoint/campo da API corresponde aquele dado -- nesse caso o
# script mostra a melhor aproximacao disponivel hoje, sinalizada como tal,
# em vez de inventar.
#
# So leitura. Nao grava nada no banco nem em arquivo -- so imprime na tela.

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

_RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DO_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DO_PROJETO))

from api_mercado_livre.core.estrutura_api.cliente_api import chamar_api, ErroAPI, ErroAutenticacaoAPI

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CONTA = "SV"  # "MB" ou "SV"
# ========================================


def ler_order_id():
    parser = argparse.ArgumentParser(description="Consulta a linha do tempo de uma devolução do ML.")
    parser.add_argument(
        "--candidato", type=int, required=True,
        help="Número do pedido a consultar (obrigatório).",
    )
    args = parser.parse_args()
    return args.candidato


ORDER_ID = ler_order_id()

PASTA_LOGS = Path(__file__).resolve().parent / "logs"
NOME_LOG = "consultar_linha_tempo_devolucao"
HEADER_FORMATO_NOVO = {"x-format-new": "true"}
FUSO_HORARIO_EXIBICAO = ZoneInfo("America/Sao_Paulo")

console = Console()


def formatar_data(valor_iso):
    if not valor_iso or not isinstance(valor_iso, str):
        return "—"
    try:
        instante = datetime.fromisoformat(valor_iso)
    except ValueError:
        return valor_iso
    instante = instante.astimezone(FUSO_HORARIO_EXIBICAO)
    return instante.strftime("%d/%m/%Y %H:%M")


def campo(rotulo, caminho_api, valor, confirmado=True):
    marca = "" if confirmado else "  (mapeamento não confirmado)"
    console.print(f"  {rotulo} [dim]({caminho_api})[/dim]: [bold]{valor}[/bold]{marca}")


def titulo_etapa(numero, nome):
    console.print()
    console.print(f"[bold blue]ETAPA {numero} — {nome.upper()}[/bold blue]")


def primeiro_evento_com_status(eventos, status_procurado):
    for evento in eventos:
        if evento.get("status") == status_procurado:
            return evento.get("date")
    return None


def ultimo_evento_com_status(eventos, status_procurado):
    encontrado = None
    for evento in eventos:
        if evento.get("status") == status_procurado:
            encontrado = evento.get("date")
    return encontrado


def buscar_historico_envio(shipment_id):
    resposta = chamar_api(
        "GET", f"/shipments/{shipment_id}/history",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        headers_extra=HEADER_FORMATO_NOVO,
        nome_log=NOME_LOG,
    )
    return resposta.json()


def buscar_claim_detalhe(claim_id):
    # * [FONTE] → doc oficial "Gerenciar resolução de reclamações": a resposta
    #   de GET /post-purchase/v1/claims/$CLAIM_ID traz o objeto completo da
    #   reclamação (reason_id, players, resolution) -- a busca em
    #   /claims/search não confirma trazer esses campos.
    resposta = chamar_api(
        "GET", f"/post-purchase/v1/claims/{claim_id}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log=NOME_LOG,
    )
    return resposta.json()


def categorizar_motivo(reason_id):
    # * [FONTE] → doc oficial: as 3 primeiras letras do reason_id definem o
    #   tipo -- "PNR" (pago e não recebido) ou "PDD" (produto defeituoso).
    #   Não existe um texto livre de "motivo" documentado -- é sempre esse
    #   código categórico.
    if not reason_id:
        return "—"
    prefixo = reason_id[:3].upper()
    categorias = {
        "PNR": "Pago e não recebido",
        "PDD": "Produto defeituoso",
    }
    categoria = categorias.get(prefixo, "categoria desconhecida")
    return f"{reason_id} ({categoria})"


def data_abertura_disputa(claim_id):
    # * [FONTE] → doc oficial "Gerenciar mensagem de uma reclamação": cada
    #   mensagem carrega o campo "stage" -- a primeira mensagem com
    #   stage="dispute" é a melhor aproximação disponível hoje pra "quando a
    #   mediação foi aberta" (não existe campo de data dedicado pra isso).
    try:
        resposta = chamar_api(
            "GET", f"/post-purchase/v1/claims/{claim_id}/messages",
            pasta_logs=PASTA_LOGS, conta=CONTA,
            nome_log=NOME_LOG,
        )
    except (ErroAPI, ErroAutenticacaoAPI):
        return None
    mensagens = resposta.json()
    mensagens_dispute = [m for m in mensagens if m.get("stage") == "dispute"]
    if not mensagens_dispute:
        return None
    return min(m.get("date_created") for m in mensagens_dispute if m.get("date_created"))


try:
    console.print(f"[bold]Pedido {ORDER_ID}[/bold] — conta {CONTA}")

    # ----- Reclamação -----
    resposta_claims = chamar_api(
        "GET", "/post-purchase/v1/claims/search",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        params={"order_id": ORDER_ID},
        nome_log=NOME_LOG,
    )
    claims = resposta_claims.json().get("data", [])
    if not claims:
        console.print("  Nenhuma reclamação encontrada pra esse pedido. Fim aqui.")
        sys.exit(0)

    claims_em_ordem_de_tentativa = sorted(
        claims, key=lambda c: 0 if c.get("type") in ("return", "fulfillment") else 1
    )

    devolucao = None
    claim = None
    for candidata in claims_em_ordem_de_tentativa:
        try:
            resposta_devolucao = chamar_api(
                "GET", f"/post-purchase/v2/claims/{candidata['id']}/returns",
                pasta_logs=PASTA_LOGS, conta=CONTA,
                nome_log=NOME_LOG,
            )
        except (ErroAPI, ErroAutenticacaoAPI):
            continue
        devolucao = resposta_devolucao.json()
        claim = buscar_claim_detalhe(candidata["id"])
        break

    if devolucao is None:
        console.print()
        console.print("  Nenhuma reclamação tem devolução física associada (endpoint /returns deu 404 em todas).")
        console.print("  Pode significar que o caso foi resolvido sem devolução física (reembolso direto, troca, etc).")
        console.print("  Dados disponíveis direto da(s) reclamação(ões) encontrada(s):")
        for c in claims_em_ordem_de_tentativa:
            c_detalhe = buscar_claim_detalhe(c["id"])
            titulo_etapa("—", f"Reclamação {c_detalhe.get('id')}")
            campo("Tipo / Etapa", "claims/{id} → type / stage", f"{c_detalhe.get('type')} / {c_detalhe.get('stage')}")
            campo("Status", "claims/{id} → status", c_detalhe.get("status") or "—")
            campo("Motivo", "claims/{id} → reason_id", categorizar_motivo(c_detalhe.get("reason_id")))
            campo("Data de abertura", "claims/{id} → date_created", formatar_data(c_detalhe.get("date_created")))
            resolucao = c_detalhe.get("resolution")
            campo("Resolução", "claims/{id} → resolution", resolucao if resolucao else "ainda não resolvida / não informada")
        sys.exit(0)

    # ----- Pedido -----
    resposta_pedido = chamar_api(
        "GET", f"/orders/{ORDER_ID}",
        pasta_logs=PASTA_LOGS, conta=CONTA,
        nome_log=NOME_LOG,
    )
    pedido = resposta_pedido.json()

    item = (pedido.get("order_items") or [{}])[0]
    titulo_item = (item.get("item") or {}).get("title", "—")

    shipping_id_ida = (pedido.get("shipping") or {}).get("id")
    data_entrega_cliente = None
    if shipping_id_ida:
        historico_ida = buscar_historico_envio(shipping_id_ida)
        data_entrega_cliente = ultimo_evento_com_status(historico_ida, "delivered")

    # ----- Envio(s) de volta -----
    envios_volta = devolucao.get("shipments", [])
    data_postagem_cliente = None
    data_chegada_nos = None
    destino_chegada = None
    for envio in envios_volta:
        shipment_id_volta = envio.get("shipment_id")
        if not shipment_id_volta:
            continue
        historico_volta = buscar_historico_envio(shipment_id_volta)
        candidato_postagem = primeiro_evento_com_status(historico_volta, "shipped")
        candidato_chegada = ultimo_evento_com_status(historico_volta, "delivered")
        if candidato_postagem and (not data_postagem_cliente or candidato_postagem < data_postagem_cliente):
            data_postagem_cliente = candidato_postagem
        if candidato_chegada and (not data_chegada_nos or candidato_chegada > data_chegada_nos):
            data_chegada_nos = candidato_chegada
            destino_chegada = (envio.get("destination") or {}).get("name")

    # ----- Branch da etapa 4 -----
    # Nota (15/09), com base na doc oficial: um player com role="mediator"
    # SÓ aparece no array "players" quando a reclamação já escalou pra
    # stage="dispute" -- "type": "mediations" sozinho não confirma mediação
    # ativa (a doc mostra um exemplo com type mediations e stage claim, sem
    # mediador nos players ainda).
    players = claim.get("players", [])
    tem_mediador = any(p.get("role") == "mediator" for p in players)
    eh_mediacao = tem_mediador or claim.get("stage") == "dispute"
    ramo = "Mediação" if eh_mediacao else "Devolução simples (sem mediação)"

    # ================= IMPRESSÃO =================

    titulo_etapa(1, "Compra")
    campo("Data da compra", "orders.date_created", formatar_data(pedido.get("date_created")))
    campo("Item comprado", "orders.order_items[0].item.title", titulo_item)
    campo("Data de entrega ao cliente", "shipments/{id}/history → status=delivered",
          formatar_data(data_entrega_cliente) if data_entrega_cliente else "não encontrado no histórico")

    titulo_etapa(2, "Reclamação")
    campo("Data de abertura", "claims/{id} → date_created", formatar_data(claim.get("date_created")))
    campo("Tipo / Etapa", "claims/{id} → type / stage",
          f"{claim.get('type')} / {claim.get('stage')}")
    campo("Motivo da reclamação", "claims/{id} → reason_id", categorizar_motivo(claim.get("reason_id")))
    campo("Data em que virou devolução", "claims/{id}/returns → date_created",
          formatar_data(devolucao.get("date_created")))

    titulo_etapa(3, "Devolução física")
    campo("Data de postagem pelo cliente", "shipments/{id}/history (volta) → status=shipped",
          formatar_data(data_postagem_cliente) if data_postagem_cliente else "ainda não despachado")
    nota_destino = f" — destino: {destino_chegada}" if destino_chegada else ""
    campo("Data de chegada", "shipments/{id}/history (volta) → status=delivered",
          (formatar_data(data_chegada_nos) if data_chegada_nos else "ainda não chegou") + nota_destino)

    titulo_etapa(4, "Decisão")
    console.print(f"  Ramo: [bold]{ramo}[/bold]")
    campo("Status da devolução", "claims/{id}/returns → status",
          devolucao.get("status") or "—")
    resolucao = claim.get("resolution")
    campo("Resolução da reclamação", "claims/{id} → resolution",
          resolucao if resolucao else "ainda não resolvida")
    if eh_mediacao:
        data_dispute = data_abertura_disputa(claim.get("id"))
        campo("Data de abertura da mediação", "claims/{id}/messages → 1ª mensagem com stage=dispute",
              formatar_data(data_dispute) if data_dispute else "não encontrada nas mensagens",
              confirmado=bool(data_dispute))
    else:
        campo("Data de abertura da mediação", "não se aplica — sem mediador nos players", "—")
    campo("Data de encerramento", "claims/{id}/returns → date_closed",
          formatar_data(devolucao.get("date_closed")) if devolucao.get("date_closed") else "ainda em aberto")
    campo("Status do dinheiro", "claims/{id}/returns → status_money",
          devolucao.get("status_money") or "—")

    # ----- Achado automático: ordem invertida -----
    if devolucao.get("date_closed") and data_chegada_nos:
        try:
            fechamento = datetime.fromisoformat(devolucao["date_closed"])
            chegada = datetime.fromisoformat(data_chegada_nos)
            if fechamento < chegada:
                dias = (chegada - fechamento).days
                console.print()
                console.print(
                    f"[bold yellow]⚠ Ordem invertida:[/bold yellow] o caso foi encerrado "
                    f"{dias} dia(s) antes da chegada física do produto."
                )
        except ValueError:
            pass
    elif devolucao.get("date_closed") and not data_postagem_cliente:
        console.print()
        console.print(
            f"[bold yellow]⚠ Ordem invertida (mais forte):[/bold yellow] o caso já foi encerrado "
            f"em {formatar_data(devolucao['date_closed'])}, mas o cliente ainda nem despachou "
            f"a devolução de volta."
        )

    console.print()
    console.print("[dim]Fim.[/dim]")

except (ErroAPI, ErroAutenticacaoAPI) as erro:
    console.print(f"[bold red]Erro ao chamar a API:[/bold red] {erro}")