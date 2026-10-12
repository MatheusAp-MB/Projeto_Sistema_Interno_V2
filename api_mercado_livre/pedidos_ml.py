# api_mercado_livre/pedidos_ml.py
#
# Função Objetivo: A chamada GET /orders/search (pedidos do vendedor) — 1 chamada = UMA página de até 50 pedidos, de 1 período de datas
# e, se pedido, de 1 MLB (filtro "item", da doc de Orders: "ID ou título"; validado com dado real em 10/10/2026: 1 MLB em 90 dias =
# 78 pedidos em 2 páginas). É o caminho do histórico de vendas depois que o endpoint de operações do Full foi abandonado.
#
# O que se sabe do endpoint (medido em 10/10/2026, conta Magazine, 42 chamadas, 0 erro 429, sem cabeçalho de limite):
#   - limit 50 por página e paginação por "offset"; o teto é offset + limit <= 10000 (offset 9950 respondeu 200; offset 82100 respondeu
#     400 "Limit must be a lower or equal than 10000"). Quem chama precisa fatiar o período para nunca passar disso.
#   - o filtro de data usa "order.date_created" e ignora minutos, segundos e milissegundos. Vale para o "from" E para o "to" (medido em 12/10/2026, dia 24/11/2025, conta Magazine):
#     to = 25/11 00:00 devolveu 477 pedidos (os 465 do dia 24 + 12 criados entre 00:00 e 00:59 do dia 25); to = 24/11 23:00 devolveu 465, o dia exato (a hora 23 entra inteira).
#     Esta função NÃO corrige isso: manda o que recebe. Quem quer [inicio, fim) em horas cheias manda to = fim − 1 hora (o coletor faz; ver _buscar_pagina em coletar_vendas_ml.py).
#   - sort=date_desc ordena pela data de FECHAMENTO do pedido (date_closed), não pela de criação: a doc de Orders diz "Sellers por date_closed" e o teste de 12/10/2026 (20 pedidos,
#     0 pares fora de ordem em date_closed; 5 fora de ordem em date_created) confirmou. Pedido criado de manhã e fechado dias depois vem no topo. Dois pedidos fechados no mesmo segundo
#     não têm ordem definida entre si: na fronteira de duas páginas (offset 50, 100...) um pode vir 2 vezes e outro nenhuma. O coletor relê a janela quando o total não fecha.
#   - a busca do vendedor TRAZ os pedidos cancelados (status "cancelled").
#   - todas as datas voltam com fuso -04:00 (Brasília é -03:00): quem lê precisa converter.
# O seller_id entra só na chamada e é trocado por *** nos params do pacote devolvido.

from dataclasses import dataclass
from datetime import datetime

from api_mercado_livre.core.estrutura_api.excecoes import ErroAPI, ErroAutenticacaoAPI

NOME_LOG = "pedidos_ml"
ENDPOINT_PEDIDOS = "/orders/search"


@dataclass
class PacotePedidos:
    """Pacote de retorno de 1 chamada. Erro de resposta do ML (400, 404...) NÃO levanta exceção: vira erro="texto" e dados=None."""
    endpoint: str
    params: dict | None
    http: int | None
    erro: str | None
    dados: dict | None


# Função Objetivo: Data no formato que o filtro do ML já aceitou com 200 OK (ex.: 2026-10-10T00:00:00.000-0300).
def formatar_data_para_filtro(instante: datetime) -> str:
    texto = instante.isoformat(timespec="milliseconds")
    return texto[:-6] + texto[-6:].replace(":", "")


class PedidosML:
    def __init__(self, cliente):
        self._cliente = cliente

    # Função Objetivo: 1 GET = UMA página de pedidos criados entre inicio e fim (datetimes COM fuso). Com `mlb`, só os pedidos que têm
    # esse item. Só a autenticação recusada (401) é repassada (levanta ErroAutenticacaoAPI): nenhuma chamada seguinte funcionaria.
    def buscar_pagina(self, seller_id, inicio, fim, offset, limite, pasta_logs, mlb=None) -> PacotePedidos:
        params = {
            "seller": seller_id,
            "order.date_created.from": formatar_data_para_filtro(inicio),
            "order.date_created.to": formatar_data_para_filtro(fim),
            "sort": "date_desc",
            "limit": limite,
        }
        if mlb:
            params["item"] = mlb
        if offset:
            params["offset"] = offset
        try:
            resposta = self._cliente.chamar("GET", ENDPOINT_PEDIDOS, pasta_logs=pasta_logs, params=params, nome_log=NOME_LOG)
        except ErroAutenticacaoAPI:
            raise
        except ErroAPI as erro:
            return PacotePedidos(ENDPOINT_PEDIDOS, {**params, "seller": "***"}, None, str(erro), None)

        params_sem_id = {**params, "seller": "***"}
        try:
            dados = resposta.json()
            erro = None
        except ValueError:
            dados = None
            erro = f"A resposta não veio em JSON: {resposta.text[:300]}"
        return PacotePedidos(ENDPOINT_PEDIDOS, params_sem_id, resposta.status_code, erro, dados)
