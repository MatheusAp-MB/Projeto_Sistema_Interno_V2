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
#     2) 1 chamada GET /users/{USER_ID}/items/search?limit=1 com o token — a prova de que o ML aceita.
#        1 chamada por clique, resposta pequena (só 1 anúncio).
#
# * [DECISÃO, 14/10/2026] → O teste NÃO usa mais o GET /users/me: ele devolve dados pessoais da conta, e agora a
#   resposta real da API aparece em "Ver detalhes". A busca de anúncios é o endpoint que o sistema já usa de
#   verdade (api_mercado_livre/mlbs_ml.py), então prova token + conta + leitura de anúncios de uma vez.
#   Ela precisa do {conta}_USER_ID do .env (o mesmo que o ApiMercadoLivre exige).
#
# * [FATOS CONFERIDOS NA DOCUMENTAÇÃO OFICIAL] → o refresh token só vale uma vez (o último emitido);
#   vale 6 meses; é invalidado por troca de senha, revogação do acesso ou renovação do Client
#   Secret; 4 meses sem nenhuma chamada também invalida. Só o administrador principal da conta
#   consegue autorizar.
#
# * [IMPORTANTE] → Os textos de "O que aconteceu / Próximo passo" são sempre nossos (só o código de status
#   vem do ML). A resposta REAL do ML (ou o erro que ele devolveu) aparece num bloco à parte em "Ver detalhes",
#   depois de passar por preparar_resposta_para_exibir() (tira tokens e corta o tamanho).

import json
import os
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
from .protecao_de_segredos import preparar_resposta_para_exibir
from .tempo_legivel import descrever_duracao

URL_BUSCA_DE_ANUNCIOS = 'https://api.mercadolibre.com/users/{user_id}/items/search'
PARAMETROS_DO_TESTE = {'limit': 1}
# * [EXPLICAÇÃO] → Texto que aparece nas evidências. O número da conta não é escrito: fica só "{id}".
DESCRICAO_DA_CHAMADA = 'GET /users/{id}/items/search?limit=1'
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
    so_falta_o_user_id = not faltando and not os.environ.get(f'{conta}_USER_ID')
    if not os.environ.get(f'{conta}_USER_ID'):
        faltando.append(f'{conta}_USER_ID')
    if faltando:
        if so_falta_o_user_id:
            como_resolver = (
                f'Adicionar a linha {conta}_USER_ID=... no .env (o número da conta no Mercado Livre, o mesmo '
                'que o sistema usa para listar os anúncios).'
            )
        else:
            como_resolver = 'Cadastrar a aplicação no DevCenter e autorizar a conta.'
        return Resultado(
            NAO_CONFIGURADA,
            f'Faltam no .env: {", ".join(faltando)}.',
            como_resolver=como_resolver,
        )

    return Resultado(
        NAO_VERIFICADA,
        'Configuração completa. Falta testar a conexão com o Mercado Livre.',
        evidencia=_descrever_validade_do_token(estado),
    )


def _resposta_do_refresh(texto_do_erro):
    # * [EXPLICAÇÃO] → A mensagem da FalhaAutenticacao termina com "Resposta: <corpo que o ML devolveu>" (e às
    #                  vezes uma observação depois). Aqui só sai o corpo do ML (JSON, quando for JSON).
    marcador = 'Resposta: '
    posicao = texto_do_erro.find(marcador)
    if posicao < 0:
        return ''
    resto = texto_do_erro[posicao + len(marcador):].lstrip()
    try:
        corpo, _ = json.JSONDecoder().raw_decode(resto)
    except ValueError:
        corpo = resto.split(' Observação:')[0]
    return preparar_resposta_para_exibir(corpo)


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
                resposta=_resposta_do_refresh(str(erro)),
            )
        return Resultado(
            ATENCAO,
            'Outro processo estava renovando o token desta conta e o tempo de espera acabou.',
            como_resolver='Testar de novo em instantes.',
            evidencia=local.evidencia,
        )

    user_id = os.environ.get(f'{conta}_USER_ID')
    try:
        resposta = requests.get(
            URL_BUSCA_DE_ANUNCIOS.format(user_id=user_id),
            headers={'Authorization': f'Bearer {token}'},
            params=PARAMETROS_DO_TESTE,
            timeout=TIMEOUT_DO_TESTE_SEGUNDOS,
        )
    except requests.exceptions.RequestException as erro:
        return Resultado(
            ATENCAO,
            f'O token foi obtido, mas a chamada de teste não chegou ao Mercado Livre ({type(erro).__name__}).',
            como_resolver='Conferir a internet do servidor e testar de novo.',
        )

    status = resposta.status_code
    evidencia = f'Teste: {DESCRICAO_DA_CHAMADA} respondeu {status}.'
    corpo = preparar_resposta_para_exibir(getattr(resposta, 'text', ''), (token,))
    if status == 200:
        return Resultado(
            FUNCIONANDO,
            'O Mercado Livre aceitou o token desta conta e respondeu à busca de anúncios.',
            evidencia=evidencia,
            resposta=corpo,
        )
    if status == 401:
        return Resultado(
            COM_PROBLEMA,
            'O Mercado Livre recusou o token (status 401) mesmo com o token em dia.',
            como_resolver=TEXTO_COMO_REAUTORIZAR,
            evidencia=evidencia,
            resposta=corpo,
        )
    if status == 403:
        return Resultado(
            COM_PROBLEMA,
            f'O Mercado Livre negou o acesso (status 403): o token não vale para esta conta ou o {conta}_USER_ID não é o desta conta.',
            como_resolver=f'Conferir o {conta}_USER_ID no .env. Se estiver certo, {TEXTO_COMO_REAUTORIZAR[0].lower()}{TEXTO_COMO_REAUTORIZAR[1:]}',
            evidencia=evidencia,
            resposta=corpo,
        )
    if status == 429 or status == 408 or status >= 500:
        return Resultado(
            ATENCAO,
            f'O Mercado Livre está instável ou limitou o uso agora (status {status}).',
            como_resolver='Esperar alguns minutos e testar de novo.',
            evidencia=evidencia,
            resposta=corpo,
        )
    return Resultado(
        ATENCAO,
        f'O Mercado Livre respondeu algo inesperado ao teste (status {status}).',
        como_resolver='Testar de novo; se repetir, ver o terminal do servidor.',
        evidencia=evidencia,
        resposta=corpo,
    )
