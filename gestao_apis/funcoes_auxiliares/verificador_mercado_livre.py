# gestao_apis/funcoes_auxiliares/verificador_mercado_livre.py

# Função Objetivo: Lê e testa a conexão com o Mercado Livre de UMA conta ("MB" ou "SV").
#
# * [EXPLICAÇÃO] → ler_local_mercado_livre(conta) NÃO chama a internet: só olha o .env (se as
#   variáveis existem e quanto falta pro token de acesso vencer, pelo relógio). Nunca devolve
#   "Funcionando" — o relógio não prova que o Mercado Livre aceita o token (senha trocada,
#   acesso revogado ou Client Secret renovado derrubam o token antes da hora).
#
# * [EXPLICAÇÃO] → testar_mercado_livre(conta) faz, no máximo:
#     1) obter_token_valido(conta) — o MESMO ponto de entrada que o sistema todo usa. Só vai ao ML
#        se o token tem menos de 30 min de vida (aí renova, e grava o par novo no .env, como sempre).
#     2) 1 chamada GET /users/me com o token — a prova de que o ML aceita. 1 chamada por clique.
#
# * [FATOS CONFERIDOS NA DOCUMENTAÇÃO OFICIAL] → o refresh token só vale uma vez (o último emitido);
#   vale 6 meses; é invalidado por troca de senha, revogação do acesso ou renovação do Client
#   Secret; 4 meses sem nenhuma chamada também invalida. Só o administrador principal da conta
#   consegue autorizar.
#
# * [IMPORTANTE] → O texto do erro do ML nunca vai pra tela: só o código de status e frases nossas.

import re
import time

import requests

from api_mercado_livre.core.auth.gerenciador_token import (
    DURACAO_TOKEN_SEGUNDOS,
    RENOVAR_ANTES_SEGUNDOS,
    FalhaAutenticacao,
    FalhaAutenticacaoTemporaria,
    _ler_estado_env,
    obter_token_valido,
)

from .estados import (
    ATENCAO, COM_PROBLEMA, FUNCIONANDO, NAO_CONFIGURADA, NAO_VERIFICADA, Resultado,
)
from .tempo_legivel import descrever_duracao

URL_USUARIO_LOGADO = 'https://api.mercadolibre.com/users/me'
TIMEOUT_DO_TESTE_SEGUNDOS = 15

TEXTO_COMO_REAUTORIZAR = (
    'Autorizar a conta de novo (só o administrador principal da conta consegue). '
    'O botão para isso nesta tela entra no próximo ciclo.'
)


def _descrever_validade_do_token(estado):
    if not estado['access_token'] or not estado['token_criado_em']:
        return 'Sem token de acesso salvo (será gerado na primeira chamada).'
    restante = estado['token_criado_em'] + DURACAO_TOKEN_SEGUNDOS - int(time.time())
    if restante > RENOVAR_ANTES_SEGUNDOS:
        return f'Token de acesso válido por mais {descrever_duracao(restante)} (pelo relógio).'
    if restante > 0:
        return 'Token de acesso perto de vencer; será renovado no próximo uso.'
    return 'Token de acesso vencido; será renovado no próximo uso.'


def ler_local_mercado_livre(conta):
    try:
        estado = _ler_estado_env(conta)
    except ValueError:
        return Resultado(
            ATENCAO,
            f'O valor de {conta}_TOKEN_CRIADO_EM no .env não é um número válido.',
            como_resolver='Corrigir essa linha do .env ou autorizar a conta de novo.',
        )

    campos = (
        ('CLIENT_ID', 'client_id'),
        ('CLIENT_SECRET', 'client_secret'),
        ('REFRESH_TOKEN', 'refresh_token'),
    )
    faltando = [f'{conta}_{nome}' for nome, chave in campos if not estado[chave]]
    if faltando:
        return Resultado(
            NAO_CONFIGURADA,
            f'Faltam no .env: {", ".join(faltando)}.',
            como_resolver='Cadastrar a aplicação no DevCenter e autorizar a conta.',
        )

    return Resultado(
        NAO_VERIFICADA,
        'Configuração completa. Falta testar a conexão com o Mercado Livre.',
        evidencia=_descrever_validade_do_token(estado),
    )


def _extrair_status(texto_do_erro):
    achado = re.search(r'status (\d{3})', texto_do_erro)
    return achado.group(1) if achado else ''


def testar_mercado_livre(conta):
    local = ler_local_mercado_livre(conta)
    if local.estado in (NAO_CONFIGURADA, ATENCAO):
        return local

    try:
        token = obter_token_valido(conta)
    except FalhaAutenticacaoTemporaria:
        return Resultado(
            ATENCAO,
            'O Mercado Livre (ou a internet) falhou na hora de renovar o token. '
            'O refresh token NÃO foi considerado inválido.',
            como_resolver='Testar de novo em alguns minutos. Não precisa autorizar a conta de novo por causa disso.',
            evidencia=local.evidencia,
        )
    except FalhaAutenticacao as erro:
        status = _extrair_status(str(erro))
        if status:
            return Resultado(
                COM_PROBLEMA,
                f'O Mercado Livre recusou renovar o token (status {status}). Causas comuns: senha trocada, '
                'acesso revogado, Client Secret renovado ou conta sem nenhuma chamada por meses.',
                como_resolver=TEXTO_COMO_REAUTORIZAR,
                evidencia=local.evidencia,
            )
        return Resultado(
            ATENCAO,
            'Outro processo estava renovando o token desta conta e o tempo de espera acabou.',
            como_resolver='Testar de novo em instantes.',
            evidencia=local.evidencia,
        )

    try:
        resposta = requests.get(
            URL_USUARIO_LOGADO,
            headers={'Authorization': f'Bearer {token}'},
            timeout=TIMEOUT_DO_TESTE_SEGUNDOS,
        )
    except requests.exceptions.RequestException as erro:
        return Resultado(
            ATENCAO,
            f'O token foi obtido, mas a chamada de teste não chegou ao Mercado Livre ({type(erro).__name__}).',
            como_resolver='Conferir a internet do servidor e testar de novo.',
        )

    status = resposta.status_code
    if status == 200:
        return Resultado(
            FUNCIONANDO,
            'O Mercado Livre aceitou o token desta conta.',
            evidencia='Teste: GET /users/me respondeu 200.',
        )
    if status in (401, 403):
        return Resultado(
            COM_PROBLEMA,
            f'O Mercado Livre recusou o token (status {status}) mesmo com o token em dia.',
            como_resolver=TEXTO_COMO_REAUTORIZAR,
            evidencia=f'Teste: GET /users/me respondeu {status}.',
        )
    if status == 429 or status == 408 or status >= 500:
        return Resultado(
            ATENCAO,
            f'O Mercado Livre está instável ou limitou o uso agora (status {status}).',
            como_resolver='Esperar alguns minutos e testar de novo.',
            evidencia=f'Teste: GET /users/me respondeu {status}.',
        )
    return Resultado(
        ATENCAO,
        f'O Mercado Livre respondeu algo inesperado ao teste (status {status}).',
        como_resolver='Testar de novo; se repetir, ver o terminal do servidor.',
        evidencia=f'Teste: GET /users/me respondeu {status}.',
    )
