# api/agente/views.py

# Função Objetivo: Rota de "ping" do agente local (14/10/2026) — só confirma que o token do agente chegou certo;
# não lê nem grava nada. É o que a rota /ping do agente (agente_local/servidor_agente.py) chama para a tela
# "Gestão de APIs" poder dizer se o sistema aceita a chave do agente.

from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_GET

from api.autenticacao import token_valido


@require_GET
def view_ping(request):
    if not token_valido(request):
        return HttpResponseForbidden(JsonResponse({'erro': 'Token inválido ou ausente.'}).content, content_type='application/json')
    return JsonResponse({'status': 'ok'})
