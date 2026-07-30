# api/postagem_automatica/views.py

# Função Objetivo: API que o AGENTE LOCAL consome — nunca o navegador
# diretamente. Cada rota reaproveita, sem duplicar, a lógica que já existe
# no orquestrador original (agenda_videos/funcoes_auxiliares/postagem_automatica/):
# _resolver_arquivo_da_ocorrencia, ArquivadorDrive, criar_postagem_aguardando_aprovacao,
# ja_postou_hoje. Esta camada só expõe isso via HTTP, com token — não
# reimplementa nenhuma regra de negócio nova.

import json
import os
import shutil
import tempfile

from django.http import JsonResponse, HttpResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from api.autenticacao import token_valido
from django.utils import timezone
from agenda_videos.models import ItemExecucaoPostagem, StatusItemExecucao, ExecucaoPostagemAutomatica, StatusExecucao
from agenda_videos.funcoes_auxiliares.postagem_ciclica import criar_postagem_aguardando_aprovacao, ja_postou_hoje
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from agenda_videos.funcoes_auxiliares.drive.arquivador import ArquivadorDrive, montar_caminho_local_organizado
from agenda_videos.funcoes_auxiliares.postagem_automatica.orquestrador import (
    obter_mlb_do_produto, resolver_arquivo_da_ocorrencia,
)


def _exigir_token(request):
    if not token_valido(request):
        return HttpResponseForbidden(JsonResponse({'erro': 'Token inválido ou ausente.'}).content, content_type='application/json')
    return None


@require_GET
def view_listar_itens(request, execucao_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    itens = ItemExecucaoPostagem.objects.filter(execucao_id=execucao_id).select_related('produto').order_by('ordem')

    resultado = []
    for item in itens:
        produto = item.produto
        # * [EXPLICAÇÃO] → Confere "já postou hoje" em tempo real, não só na
        #                  hora de criar a lista — cobre o caso de alguém
        #                  postar manualmente no meio do caminho (mesma
        #                  proteção que já existia no orquestrador antigo).
        ja_postado = ja_postou_hoje(produto)
        mlb = obter_mlb_do_produto(produto)
        resultado.append({
            'item_id': item.id,
            'ordem': item.ordem,
            'status_atual': item.status,
            'produto_titulo': produto.titulo,
            'produto_marca': produto.marca,
            'produto_ean': produto.ean,
            'mlb': mlb,
            'ja_postado_hoje': ja_postado,
        })

    return JsonResponse({'execucao_id': execucao_id, 'itens': resultado})


@require_GET
def view_baixar_video(request, item_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    item = ItemExecucaoPostagem.objects.select_related('produto', 'produto__andamento_agenda__fase_atual').filter(id=item_id).first()
    if item is None:
        return JsonResponse({'erro': 'Item não encontrado.'}, status=404)

    produto = item.produto
    andamento = getattr(produto, 'andamento_agenda', None)
    if andamento is None:
        return JsonResponse({'erro': 'Produto sem AndamentoAgenda.'}, status=400)

    arquivo_alvo, pasta_videos_id, motivo = resolver_arquivo_da_ocorrencia(produto, andamento)
    if arquivo_alvo is None:
        return JsonResponse({'erro': motivo or 'Vídeo não encontrado no Drive.'}, status=404)

    pasta_temporaria = tempfile.mkdtemp(prefix='api_video_')
    caminho_local = montar_caminho_local_organizado(pasta_temporaria, produto.ean, arquivo_alvo.nome_arquivo)

    arquivador = ArquivadorDrive()
    try:
        arquivador.baixar_arquivo(arquivo_alvo.drive_file_id, caminho_local)

        # * [EXPLICAÇÃO] → Corrigido (30/07) — antes, o vídeo era servido via
        #                  FileResponse mantendo o arquivo aberto no disco DO
        #                  SERVIDOR, sem nunca limpar a pasta temporária
        #                  depois. Invisível testando na mesma máquina
        #                  (poucos testes, reinícios frequentes) — mas um
        #                  vazamento real e sem limite num servidor rodando
        #                  de verdade (cada postagem de cada pessoa, todo
        #                  dia, acumulando pasta+vídeo pra sempre). Agora lê
        #                  os bytes pra memória e apaga a pasta ANTES de
        #                  responder — os vídeos são pequenos o bastante
        #                  (poucos MB) pra isso não pesar.
        with open(caminho_local, 'rb') as arquivo:
            conteudo = arquivo.read()
    except Exception as erro:
        shutil.rmtree(pasta_temporaria, ignore_errors=True)
        return JsonResponse({'erro': f'Erro ao baixar do Drive: {erro}'}, status=502)

    shutil.rmtree(pasta_temporaria, ignore_errors=True)

    resposta = HttpResponse(conteudo, content_type='application/octet-stream')
    resposta['Content-Disposition'] = f'attachment; filename="{arquivo_alvo.nome_arquivo}"'
    # * [EXPLICAÇÃO] → Devolve os IDs junto, em cabeçalho — o agente repassa
    #                  eles na hora de avisar "concluído", pra mover o
    #                  arquivo certo pra usados/ sem o servidor precisar
    #                  consultar o Drive de novo pra achar a mesma coisa.
    resposta['X-Drive-File-Id'] = arquivo_alvo.drive_file_id
    resposta['X-Drive-Pasta-Videos-Id'] = pasta_videos_id
    return resposta


@csrf_exempt
@require_POST
def view_marcar_concluido(request, item_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    item = ItemExecucaoPostagem.objects.select_related('produto', 'produto__andamento_agenda').filter(id=item_id).first()
    if item is None:
        return JsonResponse({'erro': 'Item não encontrado.'}, status=404)

    try:
        corpo = json.loads(request.body)
        drive_file_id = corpo['drive_file_id']
        pasta_videos_id = corpo['pasta_videos_id']
    except (json.JSONDecodeError, KeyError):
        return HttpResponseBadRequest('Corpo precisa ter drive_file_id e pasta_videos_id.')

    produto = item.produto
    andamento = produto.andamento_agenda

    criar_postagem_aguardando_aprovacao(produto, andamento)
    sincronizar_roadmap_agenda_produto(produto)

    try:
        arquivador = ArquivadorDrive()
        arquivador.mover_para_usados(drive_file_id, pasta_videos_id)
    except Exception as erro:
        # * [EXPLICAÇÃO] → A postagem JÁ foi registrada nesse ponto — falha
        #                  ao arquivar não desfaz isso (mesma decisão já
        #                  tomada no orquestrador original).
        item.status = StatusItemExecucao.CONCLUIDO
        item.mensagem_erro = f'Postado, mas falhou ao arquivar no Drive: {erro}'
        item.save(update_fields=['status', 'mensagem_erro', 'atualizado_em'])
        return JsonResponse({'status': 'concluido_com_aviso', 'aviso': str(erro)})

    item.status = StatusItemExecucao.CONCLUIDO
    item.save(update_fields=['status', 'atualizado_em'])
    return JsonResponse({'status': 'concluido'})


@csrf_exempt
@require_POST
def view_marcar_falhou(request, item_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    item = ItemExecucaoPostagem.objects.filter(id=item_id).first()
    if item is None:
        return JsonResponse({'erro': 'Item não encontrado.'}, status=404)

    try:
        corpo = json.loads(request.body)
        mensagem = corpo.get('mensagem', 'Falha não especificada.')
    except json.JSONDecodeError:
        mensagem = 'Falha não especificada.'

    item.status = StatusItemExecucao.FALHOU
    item.mensagem_erro = mensagem
    item.save(update_fields=['status', 'mensagem_erro', 'atualizado_em'])
    return JsonResponse({'status': 'falhou_registrado'})


@csrf_exempt
@require_POST
def view_heartbeat(request, execucao_id):
    recusado = _exigir_token(request)
    if recusado:
        return recusado

    atualizados = ExecucaoPostagemAutomatica.objects.filter(id=execucao_id).update(
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
    atualizados = ExecucaoPostagemAutomatica.objects.filter(id=execucao_id).update(
        status=status_final, finalizado_em=timezone.now(),
    )
    if not atualizados:
        return JsonResponse({'erro': 'Execução não encontrada.'}, status=404)
    return JsonResponse({'status': 'ok', 'status_final': status_final})