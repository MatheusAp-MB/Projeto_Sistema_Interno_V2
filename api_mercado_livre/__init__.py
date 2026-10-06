# api_mercado_livre/__init__.py

# Função Objetivo: Ponto único de entrada da API do Mercado Livre — "a
# conexão nasce aqui e só existe aqui" (decisão de Matheus, 27/09/2026,
# mesmo padrão já validado em api_sysemp/__init__.py::ApiSysemp).
# Resolve a empresa ativa sozinho (explícita tem prioridade; senão usa
# obter_empresa_ativa(), mesmo mecanismo do Database Router), monta 1
# ClienteApiMercadoLivre (transporte, conta presa) e o user_id 1 única
# vez, e expõe cada domínio como método direto — quem usa nunca importa
# chamar_api nem sabe que existe um Contexto por trás. 7 domínios
# migrados: frete, mlbs, detalhes, sku completo, comissão real,
# categorias e atributos (características) e Full (reposição e estoque).

import os

from dotenv import load_dotenv

from .core.estrutura_api.cliente_api import ClienteApiMercadoLivre
from .frete_real_ml import FreteRealML
from .mlbs_ml import MlbsML
from .detalhes_ml import DetalhesML
from .dados_sku_completo_ml import DadosSkuCompletoML
from .comissao_real_ml import ComissaoRealML
from .categorias_ml import CategoriasML
from .atributos_ml import AtributosML
from .full_ml import FullML
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
        self._mlbs = None
        self._detalhes = None
        self._dados_sku_completo = None
        self._comissao_real = None
        self._categorias = None
        self._atributos = None
        self._full = None

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

    # Função Objetivo: Passthrough pra simulação de frete (Frente A) — sem item_id, pra
    # testar uma condição hipotética (peso/dimensão + preço candidato) dentro do goal-seek
    # de precificação. Ver FreteRealML.simular() pro formato de dimensions_str.
    def simular_frete(self, dimensions_str, item_price, category_id, listing_type_id, free_shipping=False):
        return self._contexto_frete_real.simular(
            dimensions_str, item_price, category_id, listing_type_id,
            self._user_id, self._pasta_logs, free_shipping=free_shipping,
        )

    @property
    def _contexto_mlbs(self):
        if self._mlbs is None:
            self._mlbs = MlbsML(self._cliente)
        return self._mlbs

    def varrer_mlbs(self, varrida):
        return self._contexto_mlbs.varrer(varrida, self._user_id, self._pasta_logs)

    @property
    def _contexto_detalhes(self):
        if self._detalhes is None:
            self._detalhes = DetalhesML(self._cliente)
        return self._detalhes

    def buscar_detalhes_lote(self, ids_str, meta_map):
        return self._contexto_detalhes.buscar_lote(ids_str, meta_map, self._pasta_logs)

    @property
    def _contexto_dados_sku_completo(self):
        if self._dados_sku_completo is None:
            self._dados_sku_completo = DadosSkuCompletoML(self._cliente)
        return self._dados_sku_completo

    def buscar_performance(self, mlbu):
        return self._contexto_dados_sku_completo.buscar_performance(mlbu, self._pasta_logs)

    def buscar_price_to_win(self, mlb):
        return self._contexto_dados_sku_completo.buscar_price_to_win(mlb, self._pasta_logs)

    @property
    def _contexto_comissao_real(self):
        if self._comissao_real is None:
            self._comissao_real = ComissaoRealML(self._cliente)
        return self._comissao_real

    def buscar_item_info(self, mlb):
        return self._contexto_comissao_real.buscar_item_info(mlb, self._pasta_logs)

    def buscar_listing_prices(self, price, category_id, listing_type_id):
        return self._contexto_comissao_real.buscar_listing_prices(
            price, category_id, listing_type_id, self._pasta_logs,
        )

    @property
    def _contexto_categorias(self):
        if self._categorias is None:
            self._categorias = CategoriasML(self._cliente)
        return self._categorias

    def baixar_dump_categorias(self):
        return self._contexto_categorias.baixar_dump(self._pasta_logs)

    @property
    def _contexto_atributos(self):
        if self._atributos is None:
            self._atributos = AtributosML(self._cliente)
        return self._atributos

    # Função Objetivo: O que a categoria pede no card "Características
    # principais" (2 chamadas). Só deve ser chamado por botão da tela de
    # Características dos anúncios — nunca automaticamente.
    def buscar_card_categoria(self, category_id):
        return self._contexto_atributos.buscar_card_categoria(category_id, self._pasta_logs)

    # Função Objetivo: Valores que o anúncio tem hoje no ML (1 chamada por
    # MLB). Mesma regra: só por botão da tela, nunca automático.
    def buscar_atributos_item(self, mlb):
        return self._contexto_atributos.buscar_atributos_item(mlb, self._pasta_logs)

    # Função Objetivo: ENVIA atributos novos para 1 anúncio (PUT /items/{mlb},
    # 1 tentativa, sem retentativa). É o único método deste ponto de entrada
    # que ESCREVE nas características — só o botão "Confirmar envio" da tela
    # de Características dos anúncios chama, nunca automaticamente.
    def enviar_atributos_item(self, mlb, atributos):
        return self._contexto_atributos.enviar_atributos_item(mlb, atributos, self._pasta_logs)

    @property
    def _contexto_full(self):
        if self._full is None:
            self._full = FullML(self._cliente)
        return self._full

    # Função Objetivo: Os dados da tela "Planejamento de envios" de 1 produto (vendas,
    # urgência, mínimo, sugestão, Estrela, estoque antigo) — 1 chamada GET. Só deve ser
    # chamado pelo botão "Consultar no Mercado Livre" da tela do Full — nunca
    # automaticamente.
    def buscar_full_reposicao(self, user_product_id):
        return self._contexto_full.buscar_reposicao(user_product_id, self._pasta_logs)

    # Função Objetivo: O estoque do Full de 1 inventory_id (apto, não apto e o motivo) —
    # 1 chamada GET. Mesma regra: só por botão da tela do Full, nunca automático.
    def buscar_full_estoque(self, inventory_id):
        return self._contexto_full.buscar_estoque(inventory_id, self._pasta_logs)
