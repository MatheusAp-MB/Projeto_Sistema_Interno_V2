# api/replicacao_automatica/views.py

# Função Objetivo: API que o AGENTE LOCAL consome pra Replicação Automática —
# mesmo padrão exato da API de Postagem (token, sem sessão de navegador).
# Diferença central: não existe download de arquivo aqui — a Replicação só
# age no navegador (marcar checkboxes de outros anúncios), nunca baixa nada
# do Drive.

import json

from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from api.autenticacao import token_valido
from mercado_livre.models import VariacaoAnuncioMercadoLivre
from agenda_videos.models import (
    ItemExecucaoReplicacao, StatusItemExecucaoReplicacao,
    ExecucaoReplicacaoAutomatica, StatusExecucao,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from agenda_videos.funcoes_auxiliares.avancar_ocorrencia_ou_fase import avancar_ocorrencia_ou_fase
from agenda_videos.funcoes_auxiliares.postagem_automatica.orquestrador import obter_mlb_do_produto


def _exigir_token(request):
    if not token_valido(request):
        return HttpResponseForbidden(JsonResponse({'erro': 'Token inválido ou ausente.'}).content, content_type='application/json')
    return None


# Função Objetivo: Todos os OUTROS MLBs (anúncios) do mesmo produto — exclui
# o MLB que já recebeu o clip. Fonte: VariacaoAnuncioMercadoLivre, que já
# liga 1 produto (por SKU) a vários anúncios/MLBs diferentes.
def _obter_outros_mlbs(produto, mlb_atual):
    outros = VariacaoAnuncioMercadoLivre.objects.filter(
        produto=produto,
    ).exclude(anuncio__mlb=mlb_atual).values_list('anuncio__mlb', flat=True).distinct()
    return sorted(set(outros))


@require_GET
def view_listar_itens(request, execucao_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    itens = ItemExecucaoReplicacao.objects.filter(
        execucao_id=execucao_id,
    ).select_related('produto').order_by('ordem')

    resultado = []
    for item in itens:
        produto = item.produto
        mlb = obter_mlb_do_produto(produto)
        outros_mlbs = _obter_outros_mlbs(produto, mlb) if mlb else []
        resultado.append({
            'item_id': item.id,
            'ordem': item.ordem,
            'status_atual': item.status,
            'produto_titulo': produto.titulo,
            'produto_marca': produto.marca,
            'produto_ean': produto.ean,
            'mlb': mlb,
            'outros_mlbs': outros_mlbs,
        })

    return JsonResponse({'execucao_id': execucao_id, 'itens': resultado})


@csrf_exempt
@require_POST
def view_marcar_concluido(request, item_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    item = ItemExecucaoReplicacao.objects.select_related('produto').filter(id=item_id).first()
    if item is None:
        return JsonResponse({'erro': 'Item não encontrado.'}, status=404)

    produto = item.produto

    try:
        corpo = json.loads(request.body)
    except json.JSONDecodeError:
        corpo = {}
    mlbs_replicados = corpo.get('mlbs_replicados') or []
    mlbs_nao_encontrados = corpo.get('mlbs_nao_encontrados') or []

    # * [EXPLICAÇÃO] → Replicar, no nosso sistema, corresponde exatamente à
    #                  ação já existente no roadmap (avançar ocorrência,
    #                  marcar Postagem como Replicado) — reaproveitando a
    #                  MESMA função que o clique manual já usa (extraída de
    #                  views.py pra cá existir 1 fonte só), nunca uma 2ª
    #                  implementação da mesma regra de negócio.
    from agenda_videos.models import Postagem, StatusPostagem

    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento is None:
        return JsonResponse({'erro': 'Produto sem AndamentoAgenda.'}, status=400)

    postagem_atual = Postagem.objects.filter(
        produto=produto, fase=andamento.fase_atual.fase, numero_ocorrencia=andamento.ocorrencia_atual,
    ).order_by('-criado_em').first()

    if postagem_atual is None or postagem_atual.status != StatusPostagem.APROVADO:
        return JsonResponse({'erro': 'Estado inválido — a postagem atual não está Aprovada.'}, status=400)

    postagem_atual.status = StatusPostagem.REPLICADO
    postagem_atual.replicado_em = timezone.now()
    postagem_atual.mlbs_replicados = mlbs_replicados
    postagem_atual.mlbs_nao_encontrados = mlbs_nao_encontrados
    postagem_atual.save(update_fields=['status', 'replicado_em', 'mlbs_replicados', 'mlbs_nao_encontrados'])

    # * [EXPLICAÇÃO] → Assinatura real: recebe SÓ o andamento (não o
    #                  produto), e NÃO salva sozinha — quem chama precisa
    #                  persistir depois (mesmo contrato que views.py já
    #                  respeita nos outros 3 chamadores).
    try:
        avancar_ocorrencia_ou_fase(andamento, ocorrencias_completadas=andamento.ocorrencia_atual)
    except ValueError as erro:
        return JsonResponse({'erro': str(erro)}, status=400)
    andamento.save()

    sincronizar_roadmap_agenda_produto(produto)

    item.status = StatusItemExecucaoReplicacao.CONCLUIDO
    item.finalizado_em = timezone.now()
    item.save(update_fields=['status', 'finalizado_em', 'atualizado_em'])
    return JsonResponse({'status': 'concluido'})


@csrf_exempt
@require_POST
def view_marcar_falhou(request, item_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    item = ItemExecucaoReplicacao.objects.filter(id=item_id).first()
    if item is None:
        return JsonResponse({'erro': 'Item não encontrado.'}, status=404)

    try:
        corpo = json.loads(request.body)
        mensagem = corpo.get('mensagem', 'Falha não especificada.')
    except json.JSONDecodeError:
        mensagem = 'Falha não especificada.'

    item.status = StatusItemExecucaoReplicacao.FALHOU
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

    atualizados = ExecucaoReplicacaoAutomatica.objects.filter(id=execucao_id).update(
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
    atualizados = ExecucaoReplicacaoAutomatica.objects.filter(id=execucao_id).update(
        status=status_final, finalizado_em=timezone.now(),
    )
    if not atualizados:
        return JsonResponse({'erro': 'Execução não encontrada.'}, status=404)
    return JsonResponse({'status': 'ok', 'status_final': status_final})