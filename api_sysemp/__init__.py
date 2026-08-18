# api_sysemp/__init__.py

import os

from dotenv import load_dotenv

from .core.cliente import ClienteApiSysemp
from .impostos_entrada_xml import ImpostosEntradaXML
from core.empresa import obter_empresa_ativa, PREFIXO_ENV_POR_EMPRESA

# Achado real (17/08/2026): cada empresa é uma instância numerada diferente
# na Sysemp — não é credencial secreta, é infraestrutura fixa, por isso fica
# hardcoded aqui (não depende de ninguém lembrar de configurar no .env).
URL_BASE_PADRAO_POR_PREFIXO = {
    'MB': 'https://api.sysemp.com.br/61',
    'SV': 'https://api.sysemp.com.br/84',
}


class ApiSysemp:
    # * [EXPLICAÇÃO] → empresa explícito tem prioridade; sem isso, usa a
    #                  empresa ativa da sessão web ou do --empresa do
    #                  comando atual — mesmo mecanismo do Database Router.
    #                  1 só ApiSysemp() já sabe se é MB ou SV, sem token
    #                  nem URL passados na mão, sem comentar/descomentar.
    def __init__(self, empresa=None, token=None, url_base=None):
        if empresa is None:
            empresa = obter_empresa_ativa()
        if empresa is None:
            raise RuntimeError(
                'ApiSysemp precisa saber a empresa (MAGAZINE/SAMVALE) — nenhuma '
                'empresa ativa encontrada. Passe empresa=... explícito, ou rode '
                'dentro de um comando com --empresa=, ou de uma sessão web com '
                'empresa escolhida.'
            )

        if token is None:
            token = self._carregar_token_do_env(empresa)
        if url_base is None:
            url_base = self._carregar_url_base_do_env(empresa)
        self._cliente = ClienteApiSysemp(token, url_base=url_base)
        self._impostos_entrada = None

    @staticmethod
    def _carregar_token_do_env(empresa):
        load_dotenv('.env')
        prefixo = PREFIXO_ENV_POR_EMPRESA[empresa]
        nome_variavel = f'{prefixo}_SYSEMP_API_TOKEN'
        token = os.environ.get(nome_variavel)
        if not token:
            raise RuntimeError(
                f'{nome_variavel} não encontrado no .env da raiz do repo — '
                f'adicione a linha {nome_variavel}=seu_token_aqui.'
            )
        return token

    @staticmethod
    def _carregar_url_base_do_env(empresa):
        load_dotenv('.env')
        prefixo = PREFIXO_ENV_POR_EMPRESA[empresa]
        return os.environ.get(f'{prefixo}_SYSEMP_API_URL_BASE') or URL_BASE_PADRAO_POR_PREFIXO[prefixo]

    @property
    def impostos_entrada(self):
        if self._impostos_entrada is None:
            self._impostos_entrada = ImpostosEntradaXML(self._cliente)
        return self._impostos_entrada