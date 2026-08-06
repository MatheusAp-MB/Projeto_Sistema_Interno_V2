# scripts_exploracao_ERP/cliente_sysemp.py

# Função Objetivo: Cliente HTTP fino pra API do ERP Sysemp — encapsula a
# URL base e o header de autenticação (nome de header não-padrão: "Token",
# não "Authorization"), pra cada método da API virar 1 método Python
# simples de chamar. Nenhuma lógica de negócio aqui, só transporte HTTP.
# Fase de exploração: 0 integração com o resto do sistema (nem Django, nem
# settings.py) — token vem só de variável de ambiente/.env desta pasta.

import requests


class ClienteApiSysemp:
    URL_BASE = 'https://api.sysemp.com.br/61'

    def __init__(self, token):
        if not token:
            raise ValueError('Token da API Sysemp não informado.')
        self._token = token

    @property
    def _cabecalhos(self):
        return {
            'Token': self._token,
            'Content-Type': 'application/json',
        }

    # * [EXPLICAÇÃO] → Erro detalhado de propósito (corpo da resposta, não
    #                  só o status code) — essencial numa API sem doc
    #                  completa, onde o corpo do erro é a única pista real
    #                  de o que está errado num parâmetro.
    def _post(self, metodo, corpo):
        url = f'{self.URL_BASE}/{metodo}'
        resposta = requests.post(url, json=corpo, headers=self._cabecalhos, timeout=30)
        if not resposta.ok:
            raise RuntimeError(f'Sysemp respondeu {resposta.status_code} em {metodo}: {resposta.text[:500]}')
        return resposta.json()

    # Função Objetivo: Único endpoint documentado até agora — lista as
    # notas fiscais de entrada (compras) manifestadas, por período.
    # Formato de data e comportamento de offset (paginação) não estão na
    # doc — parte do que vamos descobrir explorando de verdade.
    def listar_manifesto_nota_entrada(self, data_inicial='', data_final='', offset=''):
        corpo = {'datainicial': data_inicial, 'datafinal': data_final, 'offset': offset}
        return self._post('listarManifestoNotaEntrada', corpo)