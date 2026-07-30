# * [RESUMO] → Middleware de autenticação global do projeto.
#              Intercepta todas as requisições e verifica se o usuário
#              está autenticado antes de permitir o acesso.
#              Controlado pela flag LOGIN_REQUIRED no arquivo .env

import os
from django.shortcuts import redirect

# * [EXPLICAÇÃO] → LOGIN_URL é a URL para onde o usuário é redirecionado
#                  quando não está autenticado. Definida como constante
#                  para facilitar alteração futura.
LOGIN_URL = '/login/'

# * [EXPLICAÇÃO] → Rotas que podem ser acessadas sem autenticação.
#                  O login em si precisa estar aqui para evitar loop infinito
#                  de redirecionamento.
ROTAS_PUBLICAS = [
    LOGIN_URL,
    # * [EXPLICAÇÃO] → API usa autenticação por TOKEN (conferida dentro de
    #                  cada view, via api/autenticacao.py) — nunca por
    #                  sessão de login. Sem essa exceção, toda chamada do
    #                  agente seria redirecionada pra tela de login,
    #                  devolvendo HTML em vez do JSON esperado (foi
    #                  exatamente esse o sintoma agora).
    '/api/',
]


class AutenticacaoMiddleware:
    # * [EXPLICAÇÃO] → Todo middleware Django precisa de __init__ e __call__.
    #                  O __init__ recebe e armazena o get_response — que é
    #                  a próxima camada da requisição (outra middleware ou a view).

    def __init__(self, get_response):
        self.get_response = get_response

        # * [EXPLICAÇÃO] → Lê a flag LOGIN_REQUIRED do .env uma única vez
        #                  quando o servidor sobe — não a cada requisição.
        #                  'False' é o padrão para não quebrar em desenvolvimento.
        self.login_required = os.getenv('LOGIN_REQUIRED', 'False') == 'True'

    def __call__(self, request):
        # * [EXPLICAÇÃO] → O __call__ é executado a cada requisição.
        #                  Aqui decidimos se deixamos passar ou redirecionamos.

        if self.login_required:

            # * [EXPLICAÇÃO] → Se a rota atual é pública, deixa passar
            #                  sem verificar autenticação.
            rota_publica = any(
                request.path.startswith(rota) for rota in ROTAS_PUBLICAS
            )

            # * [EXPLICAÇÃO] → Se não é rota pública e o usuário não está
            #                  autenticado, redireciona para o login.
            #                  is_authenticated é um atributo do objeto User
            #                  do Django — True se logado, False se não.
            if not rota_publica and not request.user.is_authenticated:
                return redirect(LOGIN_URL)

        # * [EXPLICAÇÃO] → Se passou por todas as verificações, repassa
        #                  a requisição para a próxima camada.
        response = self.get_response(request)
        return response