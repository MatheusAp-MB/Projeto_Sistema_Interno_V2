# api/verificacao_aprovacao/views.py

# Função Objetivo: API que o AGENTE LOCAL consome pra Verificação de
# Aprovação — mesmo padrão de token de Postagem/Replicação. Só 1 rota:
# essa automação não cria execução nenhuma (ver /verificar-aprovacao em
# agente_local/servidor_agente.py), então não tem heartbeat/finalizar.

import json

from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from api.autenticacao import token_valido
from agenda_videos.funcoes_auxiliares.verificacao_aprovacao import aplicar_estado_lido


def _exigir_token(request):
    if not token_valido(request):
        return HttpResponseForbidden(JsonResponse({'erro': 'Token inválido ou ausente.'}).content, content_type='application/json')
    return None


@csrf_exempt
@require_POST
def view_marcar_estado(request):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    try:
        corpo = json.loads(request.body)
        mlb = corpo['mlb']
        estado = corpo['estado']
    except (json.JSONDecodeError, KeyError):
        return HttpResponseBadRequest('Corpo precisa ter mlb e estado.')

    resultado = aplicar_estado_lido(mlb, estado)
    return JsonResponse({'status': resultado})