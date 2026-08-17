# api_sysemp/core/cliente.py

# Função Objetivo: Cliente HTTP fino pra API do ERP Sysemp — encapsula a
# URL base e o header de autenticação (nome de header não-padrão: "Token",
# não "Authorization"), pra cada método da API virar 1 método Python
# simples de chamar. Nenhuma lógica de negócio aqui, só transporte HTTP,
# blindado por EspacadorDeChamadas + calcular_espera_backoff (protecao.py)
# e pela hierarquia própria de excecoes.py — nunca erro genérico, nunca
# chamada sem proteção. Fase de exploração: 0 integração com o resto do
# sistema (nem Django, nem settings.py) — token vem só de variável de
# ambiente/.env desta pasta. Sem circuit breaker por decisão explícita (ver
# "Padrão de Robustez para Clientes de API Externa" no vault) — sem dado
# real de uso pra calibrar limite/reset ainda.

import logging
import time

import requests

from .excecoes import (
    ErroAPISysemp,
    ErroAutenticacaoSysemp,
    ErroLimiteRequisicoesSysemp,
    ErroNegocioSysemp,
    ErroRedeSysemp,
    ErroServidorSysemp,
)
from .protecao import EspacadorDeChamadas, calcular_espera_backoff

logger = logging.getLogger(__name__)

MAXIMO_TENTATIVAS_PADRAO = 4


class ClienteApiSysemp:
    # * [EXPLICAÇÃO] → Achado real (17/08/2026): cada empresa é uma
    #                  instância numerada diferente na Sysemp (MB = /61,
    #                  SV = /84) — não é só o token que muda entre
    #                  empresas, a própria URL base muda junto. Foi essa
    #                  URL errada (sempre a da MB) a causa raiz real do
    #                  "Metodo não Localizado" na sincronização da SV.
    #                  URL_BASE_PADRAO continua sendo a da MB (uso mais
    #                  comum, retrocompatível com quem não passa
    #                  url_base), mas agora é sobrescrevível por instância.
    
    #* MAGAZINE
    # URL_BASE = 'https://api.sysemp.com.br/61'

    ## SAMVALE
    URL_BASE = 'https://api.sysemp.com.br/84'

    def __init__(self, token, url_base=None, maximo_tentativas=MAXIMO_TENTATIVAS_PADRAO):
        if not token:
            raise ValueError('Token da API Sysemp não informado.')
        self._token = token
        self.URL_BASE = url_base or self.URL_BASE_PADRAO
        self._maximo_tentativas = maximo_tentativas
        self._espacador = EspacadorDeChamadas(intervalo_minimo_segundos=1.0)

    @property
    def _cabecalhos(self):
        return {
            'Token': self._token,
            'Content-Type': 'application/json',
        }

    # * [EXPLICAÇÃO] → Cada categoria de erro tem uma ação diferente: rede,
    #                  limite de requisição e erro de servidor são
    #                  passageiros e valem retentativa com espera; erro de
    #                  autenticação e de negócio não são — repetir a mesma
    #                  chamada não resolve, então sobem na hora.
    def chamar(self, metodo, corpo):
        url = f'{self.URL_BASE}/{metodo}'
        ultimo_erro_passageiro = None

        for numero_tentativa in range(1, self._maximo_tentativas + 1):
            self._espacador.aguardar()

            try:
                resposta = requests.post(url, json=corpo, headers=self._cabecalhos, timeout=30)
            except requests.exceptions.RequestException as excecao_rede:
                logger.warning(
                    'Sysemp: falha de rede em %s (tentativa %d/%d)',
                    metodo, numero_tentativa, self._maximo_tentativas,
                )
                ultimo_erro_passageiro = ErroRedeSysemp(f'Falha de rede ao chamar {metodo}: {excecao_rede}')
                self._aguardar_backoff(numero_tentativa)
                continue

            if resposta.ok:
                logger.info(
                    'Sysemp: %s respondeu %d (tentativa %d/%d)',
                    metodo, resposta.status_code, numero_tentativa, self._maximo_tentativas,
                )
                return resposta.json()

            if resposta.status_code in (401, 403):
                raise ErroAutenticacaoSysemp(
                    f'Sysemp respondeu {resposta.status_code} (autenticação) em {metodo}: {resposta.text[:500]}',
                    status_code=resposta.status_code, corpo_resposta=resposta.text[:500],
                )

            if resposta.status_code == 400:
                raise ErroNegocioSysemp(
                    f'Sysemp respondeu 400 (negócio) em {metodo}: {resposta.text[:500]}',
                    status_code=400, corpo_resposta=resposta.text[:500],
                )

            if resposta.status_code == 429:
                logger.warning(
                    'Sysemp: limite de requisições em %s (tentativa %d/%d)',
                    metodo, numero_tentativa, self._maximo_tentativas,
                )
                tempo_sugerido = self._extrair_tempo_espera_sugerido(resposta)
                ultimo_erro_passageiro = ErroLimiteRequisicoesSysemp(
                    f'Sysemp respondeu 429 em {metodo}: {resposta.text[:500]}',
                    status_code=429, corpo_resposta=resposta.text[:500], tempo_espera_sugerido=tempo_sugerido,
                )
                self._aguardar_backoff(numero_tentativa, tempo_sugerido)
                continue

            if resposta.status_code >= 500:
                logger.warning(
                    'Sysemp: erro de servidor %d em %s (tentativa %d/%d)',
                    resposta.status_code, metodo, numero_tentativa, self._maximo_tentativas,
                )
                ultimo_erro_passageiro = ErroServidorSysemp(
                    f'Sysemp respondeu {resposta.status_code} (servidor) em {metodo}: {resposta.text[:500]}',
                    status_code=resposta.status_code, corpo_resposta=resposta.text[:500],
                )
                self._aguardar_backoff(numero_tentativa)
                continue

            raise ErroAPISysemp(
                f'Sysemp respondeu {resposta.status_code} em {metodo}: {resposta.text[:500]}',
                status_code=resposta.status_code, corpo_resposta=resposta.text[:500],
            )

        logger.error('Sysemp: %s esgotou %d tentativas', metodo, self._maximo_tentativas)
        raise ultimo_erro_passageiro

    def _extrair_tempo_espera_sugerido(self, resposta):
        # Função Objetivo: Lê um tempo de espera sugerido pela própria API,
        # se ela informar (ex: header padrão HTTP `Retry-After`). Ainda não
        # confirmamos se o Sysemp informa isso de verdade — por enquanto só
        # verifica o header padrão; se um dia descobrirmos um formato
        # próprio do Sysemp, ele entra aqui.
        valor_bruto = resposta.headers.get('Retry-After')
        if valor_bruto is None:
            return None
        try:
            return float(valor_bruto)
        except ValueError:
            return None

    def _aguardar_backoff(self, numero_tentativa, tempo_sugerido_pela_api=None):
        tempo_espera = calcular_espera_backoff(numero_tentativa, tempo_sugerido_pela_api)
        time.sleep(tempo_espera)
