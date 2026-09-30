# api_mercado_livre/dados_sku_completo_ml.py

# Função Objetivo: Contexto "Performance e Price to Win por MLB" — sabe
# tudo que o ClienteApiMercadoLivre (transporte puro) não deve saber:
# os 2 endpoints (GET /user-product/{mlbu}/performance e
# GET /items/{mlb}/price_to_win) e o formato de "pacote" da resposta
# (chamado/http/erro/dados). Compõe um ClienteApiMercadoLivre (nunca
# herda dele). O cache por execução continua no Orquestrador (é
# controle de "evitar chamada repetida nesse run", não conhecimento de
# API). Ver "Padrao de Robustez para Clientes de API Externa" no vault.
# Peça 4 da reforma estrutural (27/09/2026) — extraído de
# integracao_mercado_livre/servicos/buscar_dados_sku_completo.py, mesma
# lógica, byte a byte.
#
# Otimização e POO (29/09/2026 — Etapa 4): o pacote de retorno virou
# PacoteApi (@dataclass) no lugar do dict solto — é exatamente "o
# formato da resposta" que a regra do vault atribui ao Contexto. Esse
# pacote também vai parar dentro do JSON de saída
# (dados_completos_por_sku.json, campos "performance"/"price_to_win" de
# cada MLB) — o Orquestrador converte de volta pra dict com
# dataclasses.asdict() na hora de montar cada registro, então o formato
# do arquivo final não muda em nada.

from dataclasses import dataclass

from .core.estrutura_api.cliente_api import ErroAPI, ErroAutenticacaoAPI


@dataclass
class PacoteApi:
    """Pacote de retorno de 1 chamada (performance ou price_to_win) — objeto de
    processo/domínio, o formato de resposta que o Contexto conhece. chamado é sempre
    True quando devolvido daqui (as 2 funções abaixo só devolvem isso depois de tentar
    a chamada de verdade) — o caso "não chamado" (MLB sem mlbu, ou não é catálogo) é
    decidido no Orquestrador, que nem chega a invocar este método nesse caso."""
    chamado: bool
    http: int | None
    erro: str | None
    dados: dict | None


class DadosSkuCompletoML:
    def __init__(self, cliente):
        self._cliente = cliente

    def buscar_performance(self, mlbu, pasta_logs) -> PacoteApi:
        try:
            r = self._cliente.chamar(
                "GET", f"/user-product/{mlbu}/performance",
                pasta_logs=pasta_logs, nome_log="buscar_dados_sku_completo",
            )
            return PacoteApi(chamado=True, http=r.status_code, erro=None, dados=r.json())
        except (ErroAPI, ErroAutenticacaoAPI) as e:
            return PacoteApi(chamado=True, http=None, erro=str(e), dados=None)

    def buscar_price_to_win(self, mlb, pasta_logs) -> PacoteApi:
        try:
            r = self._cliente.chamar(
                "GET", f"/items/{mlb}/price_to_win",
                pasta_logs=pasta_logs, params={"version": "v2"},
                nome_log="buscar_dados_sku_completo",
            )
            return PacoteApi(chamado=True, http=r.status_code, erro=None, dados=r.json())
        except (ErroAPI, ErroAutenticacaoAPI) as e:
            return PacoteApi(chamado=True, http=None, erro=str(e), dados=None)