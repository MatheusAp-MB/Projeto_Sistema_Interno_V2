# core/tests/test_nivel_2__autenticacao_middleware.py

# Função Objetivo: Testa AutenticacaoMiddleware isoladamente (RequestFactory +
# get_response falso + usuário falso via dataclass) — Nível 2, não toca banco
# nenhum. Fecha o gap de cobertura encontrado em 25/08: o ramo LOGIN_REQUIRED=
# True nunca era exercitado por nenhum teste da suíte (o ambiente de teste
# sempre roda com a flag desligada), deixando 3 statements/1 branch sem
# cobertura em core/middleware.py. EmpresaMiddleware (a outra classe do mesmo
# arquivo) já tem sua própria suíte em test_nivel_2__empresa_middleware.py.
# Ver nota "Modelo Padrao de Arquivo de Teste" no Obsidian.

from dataclasses import dataclass

from django.http import HttpResponse
from django.test import RequestFactory

from core.middleware import LOGIN_URL, AutenticacaoMiddleware
from testes_apoio.apoio_visual import registrar_resultado

TITULO_CAMADA = 'Nível 2 — core.middleware.AutenticacaoMiddleware (isolado, sem banco)'

fabrica = RequestFactory()


@dataclass
class _UsuarioFalso:
    # Função Objetivo: request.user normalmente é montado pelo middleware de
    # autenticação real do Django — como testamos AutenticacaoMiddleware
    # isolada via RequestFactory, precisamos fabricar só o atributo que ela
    # de fato lê (is_authenticated), sem precisar de um User real de banco.
    is_authenticated: bool


def _get_response_capturando(estado):
    def _dummy(request):
        estado['chamado'] = True
        return HttpResponse('ok', status=200)
    return _dummy


def _montar_middleware(estado, monkeypatch, login_required):
    # Função Objetivo: self.login_required é lido de os.getenv() dentro do
    # __init__ — por isso a variável de ambiente precisa estar setada ANTES
    # de instanciar a middleware, nunca depois.
    monkeypatch.setenv('LOGIN_REQUIRED', 'True' if login_required else 'False')
    return AutenticacaoMiddleware(_get_response_capturando(estado))


# ===================================================================
# LOGIN_REQUIRED=False — comportamento de desenvolvimento, ignora tudo
# ===================================================================

def test_login_required_desligado_deixa_passar_mesmo_sem_login_em_rota_privada(tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado, monkeypatch, login_required=False)
    request = fabrica.get('/agenda-videos/')
    request.user = _UsuarioFalso(is_authenticated=False)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['chamado'] is True
    registrar_resultado(
        tabela_resultados, teste='LOGIN_REQUIRED=False, rota privada, usuário não autenticado',
        entrada='LOGIN_REQUIRED=False, path=/agenda-videos/, is_authenticated=False',
        esperado='200, view real chamada — flag desligada ignora autenticação por completo',
        motivo='Padrão de desenvolvimento (.env sem a flag) nunca pode travar o acesso',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


# ===================================================================
# LOGIN_REQUIRED=True, rota pública — deixa passar sem checar autenticação
# ===================================================================

def test_login_required_ligado_rota_login_deixa_passar_sem_checar_autenticacao(tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado, monkeypatch, login_required=True)
    request = fabrica.get(LOGIN_URL)
    request.user = _UsuarioFalso(is_authenticated=False)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['chamado'] is True
    registrar_resultado(
        tabela_resultados, teste='LOGIN_REQUIRED=True, rota pública /login/',
        entrada=f'LOGIN_REQUIRED=True, path={LOGIN_URL}, is_authenticated=False',
        esperado='200, view real chamada — sem essa exceção o login trava num loop infinito',
        motivo='O próprio /login/ precisa ser público, senão o redirect pro login redireciona pro login pra sempre',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_login_required_ligado_rota_api_deixa_passar_sem_checar_autenticacao(tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado, monkeypatch, login_required=True)
    request = fabrica.post('/api/postagem-automatica/execucao/1/heartbeat/')
    request.user = _UsuarioFalso(is_authenticated=False)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['chamado'] is True
    registrar_resultado(
        tabela_resultados, teste='LOGIN_REQUIRED=True, rota pública /api/',
        entrada='LOGIN_REQUIRED=True, path=/api/postagem-automatica/execucao/1/heartbeat/, is_authenticated=False',
        esperado='200, view real chamada — API do agente local nunca loga por sessão, só por token',
        motivo='Sem essa exceção, o agente local seria redirecionado pro HTML de login em vez de receber o JSON esperado',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_login_required_ligado_rota_empresa_deixa_passar_sem_checar_autenticacao(tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado, monkeypatch, login_required=True)
    request = fabrica.get('/empresa/trocar/')
    request.user = _UsuarioFalso(is_authenticated=False)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['chamado'] is True
    registrar_resultado(
        tabela_resultados, teste='LOGIN_REQUIRED=True, rota pública /empresa/',
        entrada='LOGIN_REQUIRED=True, path=/empresa/trocar/, is_authenticated=False',
        esperado='200, view real chamada — escolher empresa precisa ser possível antes de logar',
        motivo='Sem essa exceção viraria loop: login exige saber a empresa, trocar empresa exigiria estar logado',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


# ===================================================================
# LOGIN_REQUIRED=True, rota privada — depende de is_authenticated
# ===================================================================

def test_login_required_ligado_rota_privada_usuario_autenticado_deixa_passar(tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado, monkeypatch, login_required=True)
    request = fabrica.get('/agenda-videos/')
    request.user = _UsuarioFalso(is_authenticated=True)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 200 and estado['chamado'] is True
    registrar_resultado(
        tabela_resultados, teste='LOGIN_REQUIRED=True, rota privada, usuário autenticado',
        entrada='LOGIN_REQUIRED=True, path=/agenda-videos/, is_authenticated=True',
        esperado='200, view real chamada — usuário logado nunca é redirecionado',
        motivo='Caminho feliz do dia a dia: usuário já logado navegando pelo sistema',
        obtido=f'status={resposta.status_code}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou


def test_login_required_ligado_rota_privada_usuario_nao_autenticado_redireciona_pro_login(tabela_resultados, monkeypatch):
    # Setup:
    estado = {'chamado': False}
    middleware = _montar_middleware(estado, monkeypatch, login_required=True)
    request = fabrica.get('/agenda-videos/')
    request.user = _UsuarioFalso(is_authenticated=False)

    # Exercise:
    resposta = middleware(request)

    # Assert:
    passou = resposta.status_code == 302 and resposta.url == LOGIN_URL and estado['chamado'] is False
    registrar_resultado(
        tabela_resultados, teste='LOGIN_REQUIRED=True, rota privada, usuário NÃO autenticado',
        entrada='LOGIN_REQUIRED=True, path=/agenda-videos/, is_authenticated=False',
        esperado=f'302 pra {LOGIN_URL}, view real NUNCA chamada',
        motivo='Único caminho que de fato bloqueia — todos os outros testes acima provam as exceções corretas',
        obtido=f'status={resposta.status_code}, url={getattr(resposta, "url", None)}, chamado={estado["chamado"]}',
        passou=passou,
    )
    assert passou