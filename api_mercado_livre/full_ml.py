# api_mercado_livre/full_ml.py
# ============================================================================================================================
# AVISO — ENDPOINT DE OPERAÇÕES DO FULL ABANDONADO PARA O HISTÓRICO DE VENDAS (decisão do Matheus, 10/10/2026, 20:04)
# ============================================================================================================================
# Este código usa GET /stock/fulfillment/operations/search. Ele FUNCIONA (90 dias de 1 SKU = 3 Códigos ML foram coletados),
# mas foi ABANDONADO: o endpoint é instável e a necessidade é rodar para MAIS DE MIL SKUs. NÃO APAGUE — guarda o que foi
# aprendido. Notas completas no vault: 05_Integracao_Mercado_Livre/Historico_de_Vendas/ (descoberta, decisão, dúvida, checkpoint).
#
# PROBLEMAS OBSERVADOS (10/10/2026, dado real, conta Magazine, 1 SKU = 3 Códigos ML):
#  1) 429 FREQUENTE: 8 de 25 chamadas na sondagem (18:33-18:38) e 34 de 51 tentativas nas 3 rodadas reais do coletor (19:43-19:46).
#     Corpo: {"message": "Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota", "error": "over_quota"}
#     NÃO é o texto "requests por minuto" da doc: cita uma entidade interna; o ESCOPO da cota é DESCONHECIDO (app, vendedor, global?).
#  2) SEM PISTA DE QUANDO TENTAR DE NOVO: nenhuma resposta traz Retry-After nem cabeçalho de limite.
#  3) PESO E ESPAÇAMENTO NÃO MUDAM A TAXA: chamada leve (1 Código, limit=1) 3/8 x pesada (3 Códigos, limit=1000) 2/8 com 429;
#     esperar 15 s entre as chamadas ainda deu 5 de 16 primeiras páginas com 429. Os 429 vêm em rajadas e a taxa variou no tempo
#     (32% às 18:33 x 67% às 19:43) — a causa é desconhecida.
#  4) SCROLL FRÁGIL: repetir o MESMO scroll depois de um 429 costuma virar 404 {"message": "Operation not found"} (2 de 2 nas
#     rodadas reais; 1 de 3 passou na sondagem). O coletor recomeça a janela e descarta as linhas repetidas (2000 na rodada de 90 dias).
#  5) Chamadas SEM scroll: 13 de 15 terminaram em 200 nas rodadas reais; 1 esgotou as 5 tentativas com 429 e 1 foi interrompida.
#  6) 120 e 150 dias NÃO foram testados (Ctrl+C durante a espera de 60 s, antes da parte antiga): só 90 dias foram validados.
#  7) A profundidade do histórico NÃO é a causa: o 429 apareceu também na janela dos 7 dias mais recentes (11 de 14 tentativas).
#
# NUNCA TESTADO: máximo de Códigos ML por chamada; omitir "type" (1 chamada em vez de 4 por janela); dividir a janela por data até
# caber em 1000 operações (sem scroll); se o horário muda a taxa. Não há contato com o Mercado Livre por ora.
#
# CAMINHO NOVO: GET /orders/search (ver o checkpoint 'Checkpoint - Historico de Vendas e Calendario de Vendas' no vault).
# Textos mais abaixo que dizem que o limite é "por minuto" ou que o 429 "passa depois de esperar" foram escritos ANTES desses
# testes: valem os fatos deste aviso.
#
# ESCOPO DESTE AVISO NESTE ARQUIVO: vale SÓ para o endpoint de operações (buscar_operacoes). Os outros 3 endpoints deste
# arquivo (reposição, estoque do Full, estoque por local) NÃO têm esse problema e continuam em uso.
# ============================================================================================================================

# Função Objetivo: Contexto "Full (Fulfillment) de 1 código" — sabe tudo que o
# ClienteApiMercadoLivre (transporte puro) não deve saber: os 4 endpoints
#   GET /marketplace/fbm/user-products/{user_product_id}/replenishment?country=BR
#       (doc "Planejamento de reposição": os dados da tela "Planejamento de
#       envios" — vendas, urgência, mínimo, sugestão, Estrela, estoque antigo)
#   GET /inventories/{inventory_id}/stock/fulfillment
#       (doc "Envios Fulfillment": estoque apto e não apto, com o motivo)
#   GET /user-products/{user_product_id}/stock
#       (doc "Convivência Full e Flex": o estoque do produto do vendedor POR LOCAL — o que está no
#       Full ("meli_facility") e o que está no depósito do vendedor ("seller_warehouse"); testado em
#       07/10/2026 e funciona para o MLB da Magazine)
#   GET /stock/fulfillment/operations/search
#       (doc "Envios Fulfillment" > "Consultar operações": o histórico de operações de estoque do Full — venda
#       confirmada, cancelamento, não entregue, devolução — de 1 ou mais Códigos ML; UMA página por chamada: a
#       paginação por scroll e as janelas de data são de quem chama)
# e o formato de "pacote" da resposta (endpoint/http/erro/dados). Compõe um
# ClienteApiMercadoLivre (nunca herda dele). Só leitura (GET).
#
# REGRA DO MATHEUS: NUNCA chamar a API sozinho. Estes métodos só podem ser
# chamados pelo botão "Consultar no Mercado Livre" da tela do Full — nunca por
# tela aberta, rotina agendada ou importação. As operações (buscar_operacoes) só são
# chamadas pelo coletor (integracao_mercado_livre/servicos/coletar_operacoes_full_ml.py),
# disparado por comando ou botão manual.

from dataclasses import dataclass

from api_mercado_livre.core.estrutura_api.excecoes import ErroAPI, ErroAutenticacaoAPI

NOME_LOG = "full_ml"


@dataclass
class PacoteFull:
    """Pacote de retorno de 1 chamada — o formato de resposta que o Contexto conhece.
    O 206 (resposta parcial) chega aqui como http=206 e o header X-Content-Missing diz
    quais blocos ficaram faltando. Erro de resposta do ML (404, 403...) NÃO levanta
    exceção: vira erro="texto" e dados=None, para a tela mostrar o que aconteceu."""
    endpoint: str
    params: dict | None
    http: int | None
    x_content_missing: str | None
    erro: str | None
    dados: dict | None


class FullML:
    def __init__(self, cliente):
        self._cliente = cliente

    def buscar_reposicao(self, user_product_id, pasta_logs) -> PacoteFull:
        return self._buscar(
            f"/marketplace/fbm/user-products/{user_product_id}/replenishment",
            {"country": "BR"}, pasta_logs,
        )

    def buscar_estoque(self, inventory_id, pasta_logs) -> PacoteFull:
        return self._buscar(f"/inventories/{inventory_id}/stock/fulfillment", None, pasta_logs)

    # O estoque do produto do vendedor por local (Full + depósito do vendedor). Limite do ML para este endpoint: 100 chamadas por minuto.
    def buscar_flex(self, user_product_id, pasta_logs) -> PacoteFull:
        return self._buscar(f"/user-products/{user_product_id}/stock", None, pasta_logs)

    # ATENÇÃO (10/10/2026, 20:04): ESTE endpoint foi ABANDONADO para o histórico de vendas — 429 "over quota" em 34 de 51 tentativas
    # nas rodadas reais (já com 1 SKU), sem Retry-After, e scroll repetido depois de 429 vira 404. Veja o aviso no topo deste arquivo.
    # O histórico de operações do Full (venda, cancelamento, não entregue, devolução...) de 1 ou mais Códigos ML — 1 GET = UMA página.
    # Regras da doc: date_to é EXCLUSIVO (a doc: "retorna até o dia -1"), o intervalo máximo é de 60 dias, o limit vai até 1000 e o
    # "scroll" (expira em 5 minutos) continua a mesma busca na página seguinte. O pacote devolvido NUNCA carrega o seller_id: ele
    # entra só na chamada e é trocado por *** nos params do pacote (o seller_id não vai para tela, JSON nem banco).
    def buscar_operacoes(self, seller_id, inventory_ids, tipo, data_de, data_ate, scroll, limite, pasta_logs) -> PacoteFull:
        params = {
            "seller_id": seller_id,
            "inventory_id": ",".join(inventory_ids),
            "type": tipo,
            "date_from": data_de.isoformat(),
            "date_to": data_ate.isoformat(),
            "limit": limite,
        }
        if scroll:
            params["scroll"] = scroll
        pacote = self._buscar("/stock/fulfillment/operations/search", params, pasta_logs)
        if pacote.params:
            pacote.params = {**pacote.params, "seller_id": "***"}
        return pacote

    # Função Objetivo: 1 GET. Só a autenticação recusada (401) é repassada (levanta
    # ErroAutenticacaoAPI): nenhuma chamada seguinte funcionaria, quem chama decide.
    def _buscar(self, endpoint, params, pasta_logs) -> PacoteFull:
        try:
            resposta = self._cliente.chamar(
                "GET", endpoint, pasta_logs=pasta_logs, params=params, nome_log=NOME_LOG,
            )
        except ErroAutenticacaoAPI:
            raise
        except ErroAPI as erro:
            return PacoteFull(endpoint=endpoint, params=params, http=None,
                              x_content_missing=None, erro=str(erro), dados=None)

        try:
            dados = resposta.json()
            erro = None
        except ValueError:
            dados = None
            erro = f"A resposta não veio em JSON: {resposta.text[:300]}"

        return PacoteFull(
            endpoint=endpoint, params=params, http=resposta.status_code,
            x_content_missing=resposta.headers.get("X-Content-Missing"),
            erro=erro, dados=dados,
        )
