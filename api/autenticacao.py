# api/autenticacao.py

# Função Objetivo: Confere o token do agente em qualquer rota da API,
# de qualquer domínio — fonte única, nunca duplicada em cada view.
# Token vem do cabeçalho HTTP "Authorization: Bearer {token}", nunca da URL
# nem do corpo (é o cabeçalho o lugar certo pra credencial, padrão usado por
# qualquer API real).

from django.conf import settings


def token_valido(request):
    cabecalho = request.headers.get('Authorization', '')
    esperado = f'Bearer {settings.AGENTE_TOKEN}'
    return cabecalho == esperado