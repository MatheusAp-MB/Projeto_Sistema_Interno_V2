# api_sysemp/__init__.py

# Função Objetivo: Ponto único de entrada pra API do Sysemp — ao
# instanciar, já resolve a autenticação (token do .env da raiz do repo, ou
# injetado explícito pra teste) e constrói o ClienteApiSysemp por dentro.
# Todo o resto do sistema acessa a API só por aqui — nunca constrói
# ClienteApiSysemp nem carrega token diretamente. Cada novo endpoint/
# contexto ganha 1 propriedade nova aqui, sempre compondo o mesmo
# ClienteApiSysemp por dentro (nunca uma instância nova por contexto). Ver
# "Padrao de Robustez para Clientes de API Externa" no vault.

import os

from dotenv import load_dotenv

from .core.cliente import ClienteApiSysemp
from .impostos_entrada_xml import ImpostosEntradaXML


class ApiSysemp:
    def __init__(self, token=None):
        if token is None:
            token = self._carregar_token_do_env()
        self._cliente = ClienteApiSysemp(token)
        self._impostos_entrada = None

    # Função Objetivo: Lê o token do .env da raiz do repo — decisão
    # consciente, todas as credenciais do projeto ficam no mesmo .env, não
    # espalhadas por pasta.
    @staticmethod
    def _carregar_token_do_env():
        load_dotenv('.env')
        token = os.environ.get('MB_SYSEMP_API_TOKEN')
        if not token:
            raise RuntimeError(
                'SYSEMP_API_TOKEN não encontrado no .env da raiz do repo — '
                'adicione a linha SYSEMP_API_TOKEN=seu_token_aqui.'
            )
        return token

    # Função Objetivo: Contexto "Obter impostos de entrada vindos do XML"
    # — 1 instância só, reaproveitada enquanto a ApiSysemp viver.
    @property
    def impostos_entrada(self):
        if self._impostos_entrada is None:
            self._impostos_entrada = ImpostosEntradaXML(self._cliente)
        return self._impostos_entrada