# gestao_apis/funcoes_auxiliares/autorizacao_google_drive.py

# Função Objetivo: Renova, pela tela "Gestão de APIs", a autorização (login OAuth) da conta dona do Google
# Drive — o que até 14/10/2026 só dava pelo terminal (autorizar_drive_oauth.py, que continua existindo como
# alternativa). É essa autorização que mantém o "Envio e vídeos" do cartão Google Drive funcionando.
#
# * [EXPLICAÇÃO] → Funciona em 2 tempos, como todo "Entrar com o Google":
#     1) iniciar_autorizacao()  → o botão leva o navegador à tela de consentimento do Google;
#     2) concluir_autorizacao() → o Google devolve o navegador a esta tela com um código de uso único; o
#        sistema troca o código pelo login, CONFERE o login novo no Drive e só então grava o arquivo.
# * [IMPORTANTE] → O arquivo do login antigo só é substituído depois que o login NOVO abriu a pasta raiz do Drive:
#   entrar com a conta errada, ou sem permissão na pasta, nunca derruba um login que ainda funcionava.
# * [IMPORTANTE] → Nenhum token, chave ou código passa pelo HTML, pelo histórico ou pelo terminal: só entram
#   nos textos o que escrevemos aqui e o e-mail da conta autorizada.
# * [EXPLICAÇÃO] → Por que prompt='consent': o Google só entrega uma chave de renovação NOVA quando a pessoa passa
#   pela tela de consentimento de novo (doc oficial "Using OAuth 2.0 for Web Server Applications"). Sem isso, a
#   renovação poderia "dar certo" sem gravar chave nenhuma.
# * [EXPLICAÇÃO] → "state" (confere que o retorno é de um pedido feito por ESTA sessão) e "code_verifier" (PKCE: o
#   código só vale para quem pediu) ficam na sessão de quem clicou, são de uso único e vencem em 10 minutos.
# * [DECISÃO, 14/10/2026] → O Google invalida a autorização 7 dias depois do consentimento enquanto o app OAuth está em
#   modo "Testando". A tela guarda o momento de cada autorização feita por aqui (histórico, ação "autorizacao") e
#   mostra quando ela vence. GOOGLE_DRIVE_OAUTH_VALIDADE_EM_DIAS (.env) = 7 no modo "Testando"; 0 quando o app for
#   publicado em produção (aí o lembrete some).
# * [EXPLICAÇÃO] → Tipos do arquivo do cliente OAuth (o que o Google Cloud baixa em "Clientes"):
#     "computador" ("installed"): o Google só aceita devolver o navegador para um endereço LOCAL (localhost);
#     "web" ("web"): aceita qualquer endereço HTTPS, desde que cadastrado no Google Cloud — é o tipo certo para o
#     sistema hospedado (informar o endereço em GOOGLE_DRIVE_OAUTH_REDIRECT_URI e cadastrá-lo lá).

import json
import os
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from .estados import FUNCIONANDO, Resultado
from .eventos import identificar_quem, registrar_evento, ultimo_evento_da_acao
from .protecao_de_segredos import limpar_texto_externo, preparar_resposta_para_exibir
from .tempo_legivel import descrever_duracao

ID_DA_PARTE_ENVIO = 'google_drive_envio'
ACAO_NO_HISTORICO = 'autorizacao'

# * [EXPLICAÇÃO] → Começo do "Próximo passo" de toda falha que se resolve renovando a autorização. A tela usa
#                  este começo para destacar o botão Renovar autorização no cartão.
PEDIDO_DE_RENOVACAO = 'Clicar em "Renovar autorização"'

CHAVE_DA_SESSAO = 'gestao_apis_google_autorizacao'
VALIDADE_DO_PEDIDO_EM_SEGUNDOS = 600
ESPERA_MAXIMA_DO_GOOGLE_EM_SEGUNDOS = 20
DIAS_DE_VALIDADE_PADRAO = 7
HORAS_DE_ANTECEDENCIA_DO_ALERTA = 48
HOSTS_DE_LOOPBACK = ('localhost', '127.0.0.1', '::1')


@dataclass(frozen=True)
class SituacaoDaAcao:
    habilitada: bool
    motivo: str = ''


@dataclass(frozen=True)
class ValidadeDaAutorizacao:
    autorizada_em: object
    vence_em: object
    restante: timedelta
    dias_de_validade: int


# ================================================
# CONFIGURAÇÃO (.env) — só olha arquivos e nomes, nunca mostra conteúdo
# ================================================

def _configuracao(nome):
    return getattr(settings, nome, None) or ''


def tipo_do_cliente_oauth():
    """
    'web', 'installed' ou '' (arquivo ausente, ilegível ou fora do formato do Google). Lê só o NOME da
    chave de topo do arquivo — nenhum valor dele sai daqui.
    """
    caminho = _configuracao('GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_JSON')
    try:
        with open(caminho, encoding='utf-8') as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError, TypeError):
        return ''
    if isinstance(dados, dict):
        for tipo in ('web', 'installed'):
            if isinstance(dados.get(tipo), dict):
                return tipo
    return ''


def situacao_para_renovar():
    """Dá para iniciar a renovação agora? Confere o que dá para conferir SEM falar com o Google."""
    from .verificador_google_drive import _pastas_raiz_configuradas

    caminho_do_cliente = _configuracao('GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_JSON')
    if not caminho_do_cliente or not os.path.isfile(caminho_do_cliente):
        return SituacaoDaAcao(
            False,
            'O arquivo do cliente OAuth do Google não foi encontrado (variável GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_JSON do .env).',
        )
    if not tipo_do_cliente_oauth():
        return SituacaoDaAcao(
            False,
            'O arquivo do cliente OAuth do Google não está no formato esperado (o JSON baixado em Google Cloud → Clientes).',
        )

    caminho_do_login = _configuracao('GOOGLE_DRIVE_OAUTH_TOKEN_JSON')
    if not caminho_do_login:
        return SituacaoDaAcao(
            False,
            'Falta a variável GOOGLE_DRIVE_OAUTH_TOKEN_JSON no .env (o caminho onde o login renovado será gravado).',
        )
    pasta = os.path.dirname(os.path.abspath(caminho_do_login))
    if not os.path.isdir(pasta) or not os.access(pasta, os.W_OK):
        return SituacaoDaAcao(
            False, 'A pasta do arquivo do login (GOOGLE_DRIVE_OAUTH_TOKEN_JSON) não existe ou não permite gravar.',
        )
    if os.path.exists(caminho_do_login) and not os.access(caminho_do_login, os.W_OK):
        return SituacaoDaAcao(False, 'O arquivo do login (GOOGLE_DRIVE_OAUTH_TOKEN_JSON) não permite gravar.')

    if not _pastas_raiz_configuradas():
        return SituacaoDaAcao(
            False,
            'Nenhuma pasta raiz do Drive configurada (GOOGLE_DRIVE_PASTA_RAIZ_MAGAZINE / _SAMVALE): '
            'sem ela não dá para conferir o login novo antes de gravar.',
        )
    return SituacaoDaAcao(True)


def endereco_de_retorno(request):
    """Endereço para onde o Google devolve o navegador. Do .env, se houver; senão, o endereço que a pessoa está usando."""
    configurado = str(_configuracao('GOOGLE_DRIVE_OAUTH_REDIRECT_URI')).strip()
    if configurado:
        return configurado
    return request.build_absolute_uri(reverse('gestao_apis_google_retorno'))


def _recusa_por_endereco(tipo_do_cliente, endereco):
    if tipo_do_cliente == 'installed' and (urlsplit(endereco).hostname or '') not in HOSTS_DE_LOOPBACK:
        return (
            'O cliente OAuth do Google deste sistema é do tipo "computador" e só aceita voltar para um endereço local '
            f'(localhost). Você está em {urlsplit(endereco).netloc}. Abra o sistema por http://localhost:8000 ou, '
            'no servidor, crie no Google Cloud um cliente do tipo "Aplicativo da Web" com este endereço de retorno: '
            f'{endereco}'
        )
    return ''


def _montar_fluxo(endereco, code_verifier=None):
    # * [EXPLICAÇÃO] → Imports aqui dentro de propósito: se a biblioteca do Google não carregar, só este botão
    #                  avisa — a tela abre igual.
    from google_auth_oauthlib.flow import Flow

    from agenda_videos.funcoes_auxiliares.drive.cliente import SCOPES_ESCRITA

    return Flow.from_client_secrets_file(
        settings.GOOGLE_DRIVE_OAUTH_CLIENT_SECRET_JSON, scopes=SCOPES_ESCRITA,
        redirect_uri=endereco, code_verifier=code_verifier,
    )


# ================================================
# VALIDADE (modo "Testando": 7 dias)
# ================================================

def dias_de_validade_configurados():
    try:
        dias = int(getattr(settings, 'GOOGLE_DRIVE_OAUTH_VALIDADE_EM_DIAS', DIAS_DE_VALIDADE_PADRAO))
    except (TypeError, ValueError):
        dias = DIAS_DE_VALIDADE_PADRAO
    return max(dias, 0)


def situacao_da_validade(agora=None):
    """
    Quando vence a última autorização feita POR ESTA TELA. None = não dá para dizer (nunca foi autorizada por aqui,
    o histórico não está disponível, ou o app está em produção e a validade configurada é 0).
    """
    dias = dias_de_validade_configurados()
    if dias == 0:
        return None
    try:
        evento = ultimo_evento_da_acao(ID_DA_PARTE_ENVIO, ACAO_NO_HISTORICO)
    except DatabaseError:
        return None
    if evento is None:
        return None
    agora = agora or timezone.now()
    vence_em = evento.criado_em + timedelta(days=dias)
    return ValidadeDaAutorizacao(evento.criado_em, vence_em, vence_em - agora, dias)


def precisa_renovar_logo(validade):
    return validade is not None and validade.restante <= timedelta(hours=HORAS_DE_ANTECEDENCIA_DO_ALERTA)


def _formatar_momento(momento):
    return timezone.localtime(momento).strftime('%d/%m/%Y %H:%M')


def descrever_autorizacao_feita(validade):
    return f'Autorizado por esta tela em {_formatar_momento(validade.autorizada_em)}.'


def descrever_lembrete(validade):
    """Frase do "Próximo passo" enquanto o login funciona: até quando renovar."""
    vence = _formatar_momento(validade.vence_em)
    if validade.restante <= timedelta(0):
        return (
            f'Renovar a autorização agora, pelo botão "Renovar autorização": o prazo de {validade.dias_de_validade} dias '
            f'do modo "Testando" passou ({vence}).'
        )
    # * [EXPLICAÇÃO] → +30 min: arredonda para a hora mais próxima. Sem isso, uma autorização feita há 3 segundos
    #                  apareceria como "faltam 6 dias" (6 dias e 23 h 59 min, cortado para baixo).
    faltam = descrever_duracao(validade.restante.total_seconds() + 1800)
    return f'Renovar a autorização, pelo botão "Renovar autorização", até {vence} (faltam {faltam}).'


# ================================================
# 1) INICIAR: o navegador vai para o Google
# ================================================

def iniciar_autorizacao(request):
    """Devolve (endereço do Google para onde mandar o navegador, '') ou (None, motivo da recusa)."""
    situacao = situacao_para_renovar()
    if not situacao.habilitada:
        return None, situacao.motivo

    endereco = endereco_de_retorno(request)
    recusa = _recusa_por_endereco(tipo_do_cliente_oauth(), endereco)
    if recusa:
        return None, recusa

    try:
        fluxo = _montar_fluxo(endereco)
    except (OSError, ValueError, KeyError):
        return None, 'O arquivo do cliente OAuth do Google existe, mas não pôde ser lido como credencial do Google.'

    url_do_google, state = fluxo.authorization_url(prompt='consent')
    request.session[CHAVE_DA_SESSAO] = {
        'state': state,
        'code_verifier': fluxo.code_verifier,
        'redirect_uri': endereco,
        'criado_em': time.time(),
    }
    return url_do_google, ''


# ================================================
# 2) CONCLUIR: o Google devolve o navegador com um código
# ================================================

CHAVES_DO_PEDIDO = ('state', 'code_verifier', 'redirect_uri', 'criado_em')


def _pedido_vencido_ou_malformado(pedido):
    if not isinstance(pedido, dict) or not all(chave in pedido for chave in CHAVES_DO_PEDIDO):
        return True
    try:
        return time.time() - float(pedido['criado_em']) > VALIDADE_DO_PEDIDO_EM_SEGUNDOS
    except (TypeError, ValueError):
        return True


def _pedido_valido(pedido, state_recebido):
    if _pedido_vencido_ou_malformado(pedido):
        return False
    return secrets.compare_digest(str(state_recebido).encode('utf-8'), str(pedido['state']).encode('utf-8'))


def _conferir_login_novo(credenciais):
    """
    Abre a pasta raiz do Drive com o login NOVO (nada é gravado). Devolve (Resultado, e-mail da conta ou '').
    Só FUNCIONANDO autoriza a gravação.
    """
    import httplib2
    from google.auth.exceptions import RefreshError, TransportError
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    from .verificador_google_drive import _ler_pasta, _pastas_raiz_configuradas, _resultado_de_erro_do_google

    erros_esperados = (RefreshError, HttpError, TransportError, httplib2.HttpLib2Error, OSError, ValueError)
    rotulo, pasta_id = _pastas_raiz_configuradas()[0]
    try:
        servico = build('drive', 'v3', credentials=credenciais)
        arquivo = _ler_pasta(servico, pasta_id)
    except erros_esperados as erro:
        resultado = _resultado_de_erro_do_google(erro, 'envio', f'pasta raiz da {rotulo}')
        if resultado is None:
            raise
        return resultado, ''

    # * [EXPLICAÇÃO] → O e-mail é só para a pessoa conferir que entrou com a conta certa; se esta 2ª chamada falhar,
    #                  a renovação continua valendo (a pasta raiz já abriu).
    email = ''
    try:
        conta = servico.about().get(fields='user(emailAddress)').execute()
        email = limpar_texto_externo((conta.get('user') or {}).get('emailAddress', ''), 80)
    except erros_esperados:
        pass

    evidencia = f'Pasta raiz da {rotulo} ("{limpar_texto_externo(arquivo.get("name", ""), 60)}") acessível com o login novo.'
    if email:
        evidencia = f'Conta: {email} · {evidencia}'
    return Resultado(
        FUNCIONANDO,
        'Autorização renovada: o Google aceitou o login novo da conta dona do Drive.',
        evidencia=evidencia,
        resposta=preparar_resposta_para_exibir({rotulo: arquivo}),
    ), email


def _gravar_login(credenciais):
    """Grava o arquivo do login de uma vez só (arquivo temporário + troca), para nunca sobrar um arquivo pela metade."""
    caminho = settings.GOOGLE_DRIVE_OAUTH_TOKEN_JSON
    temporario = f'{caminho}.novo'
    try:
        with open(temporario, 'w', encoding='utf-8') as arquivo:
            arquivo.write(credenciais.to_json())
        with suppress(OSError):
            os.chmod(temporario, 0o600)
        os.replace(temporario, caminho)
    except OSError:
        with suppress(OSError):
            os.remove(temporario)
        raise


def concluir_autorizacao(request):
    """
    Trata a volta do Google. Devolve (tipo, texto) para o aviso da tela: tipo = 'ok' | 'info' | 'erro'.
    Só grava o arquivo (e o histórico) quando o login novo foi conferido no Drive.
    """
    pedido = request.session.get(CHAVE_DA_SESSAO)
    if not _pedido_valido(pedido, request.GET.get('state', '')):
        # * [EXPLICAÇÃO] → Retorno que não confere. Só se descarta o pedido guardado quando ele já venceu (ou está
        #                  malformado); um pedido AINDA VÁLIDO fica, para que uma janela antiga do Google (ou um endereço
        #                  forjado) não destrua a renovação que está em andamento na janela nova.
        if _pedido_vencido_ou_malformado(pedido):
            request.session.pop(CHAVE_DA_SESSAO, None)
        return 'erro', (
            'Este retorno do Google não confere com um pedido feito por esta tela (o pedido vale 10 minutos, '
            'só pode ser usado uma vez e precisa ter saído desta mesma sessão). Nada foi alterado. '
            'Clique em "Renovar autorização" de novo.'
        )

    # * [EXPLICAÇÃO] → Pedido conferido: é de uso único, sai da sessão já aqui (deu certo ou não daqui em diante).
    request.session.pop(CHAVE_DA_SESSAO, None)

    erro_do_google = request.GET.get('error', '')
    if erro_do_google:
        if erro_do_google == 'access_denied':
            return 'info', 'A autorização foi cancelada na tela do Google. Nada foi alterado.'
        return 'erro', f'O Google devolveu o erro "{limpar_texto_externo(erro_do_google, 60)}". Nada foi alterado.'

    codigo = request.GET.get('code', '')
    if not codigo:
        return 'erro', 'O Google não devolveu o código de autorização. Nada foi alterado; clique em "Renovar autorização" de novo.'

    from oauthlib.oauth2.rfc6749.errors import OAuth2Error
    from requests.exceptions import RequestException

    try:
        fluxo = _montar_fluxo(pedido['redirect_uri'], code_verifier=pedido['code_verifier'])
        fluxo.fetch_token(code=codigo, timeout=ESPERA_MAXIMA_DO_GOOGLE_EM_SEGUNDOS)
        credenciais = fluxo.credentials
    except RequestException:
        return 'erro', (
            'Não foi possível falar com o Google para concluir a autorização (internet do servidor ou instabilidade). '
            'Nada foi alterado; tente de novo.'
        )
    except OAuth2Error as erro:
        return 'erro', (
            f'O Google recusou o código de autorização ({limpar_texto_externo(getattr(erro, "error", ""), 40) or "sem detalhe"}). '
            'Nada foi alterado; clique em "Renovar autorização" de novo.'
        )
    except Warning:
        # * [EXPLICAÇÃO] → A biblioteca avisa (como exceção) quando o Google devolve permissões diferentes das pedidas.
        return 'erro', (
            'O Google devolveu permissões diferentes das pedidas (acesso completo ao Drive). Nada foi alterado. '
            'Tente de novo e deixe todas as permissões marcadas na tela do Google.'
        )

    if not credenciais.refresh_token:
        return 'erro', (
            'O Google não entregou a chave de renovação do login. Nada foi alterado. Abra "Permissões" '
            '(conta Google), remova o acesso deste app e clique em "Renovar autorização" de novo.'
        )

    resultado, email = _conferir_login_novo(credenciais)
    if resultado.estado != FUNCIONANDO:
        return 'erro', (
            f'{resultado.motivo} {resultado.como_resolver} O login anterior foi mantido (nada foi gravado). '
            'Confira se você entrou com a conta dona do Drive.'
        ).replace('  ', ' ')

    try:
        _gravar_login(credenciais)
    except OSError:
        return 'erro', (
            'O Google aceitou o login, mas não foi possível gravar o arquivo (GOOGLE_DRIVE_OAUTH_TOKEN_JSON): '
            'confira se ele não está aberto em outro programa e se a pasta permite gravar. Clique em "Renovar autorização" de novo.'
        )

    registrar_evento(ID_DA_PARTE_ENVIO, ACAO_NO_HISTORICO, resultado, identificar_quem(request))

    texto = 'Autorização do Google Drive renovada' + (f' com a conta {email}.' if email else '.')
    validade = situacao_da_validade()
    if validade is not None:
        texto += (
            f' Em modo "Testando" ela vale até {_formatar_momento(validade.vence_em)}: renove antes disso.'
        )
    return 'ok', texto
