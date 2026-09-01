# api/verificacao_aprovacao/views.py

# Função Objetivo: API que o AGENTE LOCAL consome pra Verificação de
# Aprovação — mesmo padrão exato da API de Replicação (token, sem sessão
# de navegador, item_id + execucao_id). Substitui a rota única
# "marcar-estado/" da Fase 1/2 sem progresso (01/09) — agora a Verificação
# também tem execução rastreada no banco, igual Postagem/Replicação.

import json

from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from api.autenticacao import token_valido
from agenda_videos.models import (
    ItemExecucaoVerificacao, StatusItemExecucaoVerificacao,
    ExecucaoVerificacaoAprovacao, StatusExecucao,
)
from agenda_videos.funcoes_auxiliares.verificacao_aprovacao import aplicar_estado_lido
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto


def _exigir_token(request):
    if not token_valido(request):
        return HttpResponseForbidden(JsonResponse({'erro': 'Token inválido ou ausente.'}).content, content_type='application/json')
    return None


@require_GET
def view_listar_itens(request, execucao_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    itens = ItemExecucaoVerificacao.objects.filter(
        execucao_id=execucao_id,
    ).select_related('produto').order_by('ordem')

    resultado = []
    for item in itens:
        resultado.append({
            'item_id': item.id,
            'ordem': item.ordem,
            'status_atual': item.status,
            'produto_titulo': item.produto.titulo,
            'produto_marca': item.produto.marca,
            'mlb': item.mlb,
        })

    return JsonResponse({'execucao_id': execucao_id, 'itens': resultado})


# * [EXPLICAÇÃO] → Único ponto de escrita — reaproveita aplicar_estado_lido
#                  (agenda_videos/funcoes_auxiliares/verificacao_aprovacao.py),
#                  já validado na Fase 2 sem progresso. Nunca reimplementar
#                  essa regra de negócio aqui de novo.
@csrf_exempt
@require_POST
def view_marcar_concluido(request, item_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    item = ItemExecucaoVerificacao.objects.select_related('produto').filter(id=item_id).first()
    if item is None:
        return JsonResponse({'erro': 'Item não encontrado.'}, status=404)

    try:
        corpo = json.loads(request.body)
        estado = corpo.get('estado')
    except json.JSONDecodeError:
        estado = None

    resultado = aplicar_estado_lido(item.mlb, estado)

    # * [CORREÇÃO, bug real 01/09] → aplicar_estado_lido só escreve em
    #                  CicloVideo — sem isso, IndicadoresAgendaProduto
    #                  (cache que toda tela da Agenda usa pra filtrar) fica
    #                  desatualizado SILENCIOSAMENTE, e o produto nunca sai
    #                  de "Aguardando Aprovação" na tela, mesmo com o banco
    #                  já certo. Mesma chamada que api/replicacao_automatica/
    #                  views.py já faz depois de marcar_replicado — faltou
    #                  aqui na primeira versão. Só precisa rodar quando
    #                  realmente mudou algo (resultado == 'atualizado');
    #                  sem_mudanca/ciclo_nao_encontrado não alteram nada.
    if resultado == 'atualizado':
        sincronizar_indicadores_agenda_produto(item.produto)

    item.status = StatusItemExecucaoVerificacao.CONCLUIDO
    item.estado_lido = estado
    item.resultado_aplicado = resultado
    item.finalizado_em = timezone.now()
    item.save(update_fields=['status', 'estado_lido', 'resultado_aplicado', 'finalizado_em', 'atualizado_em'])
    return JsonResponse({'status': 'concluido', 'resultado': resultado})


@csrf_exempt
@require_POST
def view_marcar_falhou(request, item_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    item = ItemExecucaoVerificacao.objects.filter(id=item_id).first()
    if item is None:
        return JsonResponse({'erro': 'Item não encontrado.'}, status=404)

    try:
        corpo = json.loads(request.body)
        mensagem = corpo.get('mensagem', 'Falha não especificada.')
    except json.JSONDecodeError:
        mensagem = 'Falha não especificada.'

    item.status = StatusItemExecucaoVerificacao.FALHOU
    item.mensagem_erro = mensagem
    item.finalizado_em = timezone.now()
    item.save(update_fields=['status', 'mensagem_erro', 'finalizado_em', 'atualizado_em'])
    return JsonResponse({'status': 'falhou_registrado'})


@csrf_exempt
@require_POST
def view_heartbeat(request, execucao_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    atualizados = ExecucaoVerificacaoAprovacao.objects.filter(id=execucao_id).update(
        ultimo_heartbeat_agente=timezone.now(), status=StatusExecucao.RODANDO,
    )
    if not atualizados:
        return JsonResponse({'erro': 'Execução não encontrada.'}, status=404)
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@require_POST
def view_finalizar_execucao(request, execucao_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    try:
        corpo = json.loads(request.body)
        cancelada = corpo.get('cancelada', False)
    except json.JSONDecodeError:
        cancelada = False

    status_final = StatusExecucao.CANCELADO if cancelada else StatusExecucao.CONCLUIDO
    atualizados = ExecucaoVerificacaoAprovacao.objects.filter(id=execucao_id).update(
        status=status_final, finalizado_em=timezone.now(),
    )
    if not atualizados:
        return JsonResponse({'erro': 'Execução não encontrada.'}, status=404)
    return JsonResponse({'status': 'ok', 'status_final': status_final})