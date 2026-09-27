# api_mercado_livre/__init__.py

# Função Objetivo: Ponto único de entrada da API do Mercado Livre — "a
# conexão nasce aqui e só existe aqui" (decisão de Matheus, 27/09/2026,
# mesmo padrão já validado em api_sysemp/__init__.py::ApiSysemp).
# Resolve a empresa ativa sozinho (explícita tem prioridade; senão usa
# obter_empresa_ativa(), mesmo mecanismo do Database Router), monta 1
# ClienteApiMercadoLivre (transporte, conta presa) e o user_id 1 única
# vez, e expõe cada domínio como método direto — quem usa nunca importa
# chamar_api nem sabe que existe um Contexto (FreteRealML, por enquanto)
# por trás. Primeira fatia (frete); os outros 5 domínios (mlbs, comissão,
# detalhes, sku completo, categorias) entram do mesmo jeito, 1 de cada
# vez, depois desta ser validada de ponta a ponta.

import os

from dotenv import load_dotenv

from .core.estrutura_api.cliente_api import ClienteApiMercadoLivre
from .frete_real_ml import FreteRealML
from core.empresa import obter_empresa_ativa, PREFIXO_ENV_POR_EMPRESA


class ApiMercadoLivre:
    # * [EXPLICAÇÃO] → empresa explícito tem prioridade; sem isso, usa a
    #                  empresa ativa da sessão web ou do --empresa do
    #                  comando atual — mesmo mecanismo do ApiSysemp. 1 só
    #                  ApiMercadoLivre() já sabe qual conta/token usar,
    #                  sem precisar passar conta na mão em cada chamada.
    def __init__(self, pasta_logs, empresa=None):
        if empresa is None:
            empresa = obter_empresa_ativa()
        if empresa is None:
            raise RuntimeError(
                'ApiMercadoLivre precisa saber a empresa (MAGAZINE/SAMVALE) — nenhuma '
                'empresa ativa encontrada. Passe empresa=... explícito, ou rode dentro '
                'de um comando com --empresa=, ou de uma sessão web com empresa escolhida.'
            )

        conta = PREFIXO_ENV_POR_EMPRESA[empresa]
        self._cliente = ClienteApiMercadoLivre(conta)
        self._pasta_logs = pasta_logs
        self._user_id = self._carregar_user_id(conta)
        self._frete_real = None

    @staticmethod
    def _carregar_user_id(conta):
        load_dotenv()
        user_id = os.getenv(f"{conta}_USER_ID")
        if not user_id:
            raise RuntimeError(
                f'{conta}_USER_ID não encontrado no .env da raiz do repo — '
                f'adicione a linha {conta}_USER_ID=seu_user_id_aqui.'
            )
        return user_id

    @property
    def _contexto_frete_real(self):
        if self._frete_real is None:
            self._frete_real = FreteRealML(self._cliente)
        return self._frete_real

    def buscar_frete(self, mlb):
        return self._contexto_frete_real.buscar(mlb, self._user_id, self._pasta_logs)