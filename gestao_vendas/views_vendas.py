# gestao_vendas/views_vendas.py
#
# Views da tela "Vendas — Histórico de vendas" (Mercado Livre → Vendas → Histórico de vendas): o ritmo de vendas de UM produto (SKU), lido do banco.
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML SOZINHA. Abrir, trocar o período, o nível ou o produto só LÊ o banco. A API só é chamada por
# CLIQUE, em 3 botões, todos granulares (nem sempre a varredura completa de todos os SKUs):
#   - "Atualizar" de um MLB (e "Atualizar produto", que a tela faz em TRECHOS CURTOS, vários ao mesmo tempo): primeiro pergunta o PLANO (só o que
#     falta: view_vendas_planejar, que não chama o ML) e depois chama view_vendas_atualizar_mlb uma vez por trecho
#   - "Atualizar dia" (1 dia da conta toda, o ícone dentro de cada dia do calendário)                              → view_vendas_atualizar_dia
#   - "Coletar período da conta" (um período por calendário da conta toda, em segundo plano) → view_vendas_periodo_iniciar (com _status para a barra e _parar)
# Depois de uma atualização que deu certo a tela recarrega e lê o banco de novo.

import traceback
from datetime import date, datetime

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from api_mercado_livre.core.estrutura_api.excecoes import ErroAutenticacaoAPI
from core.empresa import obter_empresa_ativa
from gestao_full.views_full import _ler_json
from mercado_livre.models import ColetaVendasMercadoLivre
from mercado_livre.views_caracteristicas import _nome_usuario

MSG_PERIODO_RODANDO = 'Há uma coleta de período da conta em andamento. Espere terminar (ou clique em Parar) para atualizar um MLB ou um dia.'
MSG_TOKEN = 'O Mercado Livre recusou o acesso (token inválido ou vencido). Nada foi gravado.'
MSG_INESPERADA = 'Falha inesperada ao consultar o Mercado Livre. O detalhe está no terminal do servidor.'


def _inteiro(valor, padrao):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _data_iso(valor):
    """'2026-10-09' → date; qualquer outra coisa → ValueError."""
    return date.fromisoformat(str(valor or ''))


def _verdadeiro(valor):
    return str(valor).strip().lower() in ('1', 'true', 'sim', 'on')


# Função Objetivo: A tela. LÊ SÓ DO BANCO. Os parâmetros da URL (sku, q, periodo, nivel, item, visao) são validados dentro de montar_pagina.
@require_GET
def view_vendas(request):
    from gestao_vendas.funcoes_auxiliares.vendas_ml import montar_pagina
    from integracao_mercado_livre.servicos.cobertura_vendas_ml import DIAS_DE_REVISAO, periodos_de_hoje
    from integracao_mercado_livre.servicos.coletar_vendas_ml import dias_padrao, estimar_opcoes_do_periodo

    base = reverse('gestao_vendas_principal')
    pagina = montar_pagina(request.GET, base)
    return render(request, 'gestao_vendas/estrutura_vendas.html', {
        'pagina': pagina,
        'url_vendas': base,
        # Opções da janela "Coletar período da conta": os mesmos 5 períodos dos botões (com as datas de hoje), e para cada um quantos dias faltam,
        # quantas chamadas e quantos minutos se espera (estimativa), só o que falta e "reler tudo".
        'opcoes_coleta': estimar_opcoes_do_periodo(periodos_de_hoje(pagina['hoje'])),
        'dias_padrao_coleta': dias_padrao(),
        'dias_de_revisao': DIAS_DE_REVISAO,
        # Endereços que o JS usa (só são chamados depois de um clique).
        'url_planejar': reverse('gestao_vendas_planejar'),
        'url_atualizar_mlb': reverse('gestao_vendas_atualizar_mlb'),
        'url_atualizar_dia': reverse('gestao_vendas_atualizar_dia'),
        'url_periodo_iniciar': reverse('gestao_vendas_periodo_iniciar'),
        'url_periodo_status': reverse('gestao_vendas_periodo_status'),
        'url_periodo_parar': reverse('gestao_vendas_periodo_parar'),
    })


# Função Objetivo: Executa uma coleta síncrona e traduz as exceções para a resposta que a tela entende. O acesso recusado (502) e a coleta de
# período rodando (409) vêm com "interromper": a tela para a fila do "Atualizar produto".
def _responder_coleta(coletar):
    from integracao_mercado_livre.servicos.coletar_vendas_ml import ColetaOcupada, ErroColetaVendas, JanelaGrande

    try:
        relatorio = coletar()
    except JanelaGrande as grande:
        # Não é erro: a janela tem pedidos demais para 1 requisição. Nada foi gravado; a tela refaz com os pedaços.
        return JsonResponse({'ok': False, 'dividir': True, 'total': grande.total,
                             'partes': [{'de': de.isoformat(), 'ate': ate.isoformat()} for de, ate in grande.partes]})
    except ColetaOcupada as erro:
        if erro.args and erro.args[0] == 'periodo':
            return JsonResponse({'ok': False, 'mensagem': MSG_PERIODO_RODANDO, 'interromper': True}, status=409)
        return JsonResponse({'ok': False, 'mensagem': 'Essa coleta já está rodando (em outra aba?). Espere um instante.'}, status=409)
    except ErroColetaVendas as erro:
        return JsonResponse({'ok': False, 'mensagem': str(erro)}, status=422)
    except ErroAutenticacaoAPI:
        traceback.print_exc()
        return JsonResponse({'ok': False, 'interromper': True, 'mensagem': MSG_TOKEN}, status=502)
    except Exception:
        traceback.print_exc()
        return JsonResponse({'ok': False, 'mensagem': MSG_INESPERADA}, status=500)

    if relatorio.status == ColetaVendasMercadoLivre.Status.FALHA:
        return JsonResponse({'ok': False, 'mensagem': relatorio.mensagem or 'A coleta falhou.', 'erros_429': relatorio.erros_429}, status=422)
    return JsonResponse({'ok': True, 'mensagem': relatorio.mensagem, 'avisos': len(relatorio.avisos), 'pedidos': relatorio.pedidos_lidos,
                         'chamadas': relatorio.chamadas, 'erros_429': relatorio.erros_429})


# Função Objetivo: Coleta os pedidos de UM MLB e grava no banco: de (hoje − `dias`) até hoje (`dias` = dias para trás) ou, se vierem `de` e `ate` (AAAA-MM-DD), só nesse trecho
# (é assim que a tela faz o "Atualizar", em trechos curtos). `max_pedidos` (50 a 5000, opcional): se o ML anunciar mais que isso para o trecho, NADA
# é gravado e a resposta vem com "dividir" e os pedaços. Recusa se uma coleta de período está rodando ou se o mesmo trecho já está sendo coletado.
@require_POST
def view_vendas_atualizar_mlb(request):
    from integracao_mercado_livre.servicos.coletar_vendas_ml import coletar_mlb, dias_padrao

    corpo = _ler_json(request) or {}
    mlb = str(corpo.get('mlb') or '').strip().upper()
    if not mlb.startswith('MLB'):
        return JsonResponse({'ok': False, 'mensagem': 'MLB inválido. Recarregue a página e tente de novo.'}, status=400)
    dias = _inteiro(corpo.get('dias'), dias_padrao())
    sku = str(corpo.get('sku') or '').strip()
    de = ate = None
    if corpo.get('de') or corpo.get('ate'):
        try:
            de, ate = _data_iso(corpo.get('de')), _data_iso(corpo.get('ate'))
        except ValueError:
            return JsonResponse({'ok': False, 'mensagem': 'Trecho inválido. Recarregue a página e tente de novo.'}, status=400)
    maximo = _inteiro(corpo.get('max_pedidos'), None)
    maximo = maximo if maximo is not None and 50 <= maximo <= 5000 else None
    empresa, usuario = obter_empresa_ativa(), _nome_usuario(request)
    return _responder_coleta(lambda: coletar_mlb(empresa, mlb, dias, usuario, sku, de=de, ate=ate, max_pedidos=maximo))


# Função Objetivo: O PLANO do "Atualizar" — NÃO chama o Mercado Livre, só lê o registro de coletas. Para o `sku` (todos os MLBs dele) ou para um
# `mlb`, de (hoje − `dias`) até hoje, devolve os trechos que faltam buscar (dia nunca coletado, só parcial, ou dentro dos últimos 30 dias) e quantos
# pedidos no máximo cada requisição deve ler. `tudo=1` = reler tudo.
@require_GET
def view_vendas_planejar(request):
    from gestao_vendas.funcoes_auxiliares.vendas_ml import carregar_produto
    from integracao_mercado_livre.servicos.coletar_vendas_ml import (
        MAX_PEDIDOS_POR_REQUISICAO, ErroColetaVendas, dias_padrao, planejar_trechos)

    dias = _inteiro(request.GET.get('dias'), dias_padrao())
    mlb = str(request.GET.get('mlb') or '').strip().upper()
    if mlb:
        if not mlb.startswith('MLB'):
            return JsonResponse({'ok': False, 'mensagem': 'MLB inválido. Recarregue a página e tente de novo.'}, status=400)
        mlbs = [mlb]
    else:
        produto = carregar_produto(str(request.GET.get('sku') or '').strip())
        mlbs = sorted(produto['mlbs']) if produto else []
        if not mlbs:
            return JsonResponse({'ok': False, 'mensagem': 'O banco não liga nenhum MLB a este SKU. Use "Coletar período da conta".'}, status=422)
    try:
        plano = planejar_trechos(mlbs, dias, reler_tudo=_verdadeiro(request.GET.get('tudo')))
    except ErroColetaVendas as erro:
        return JsonResponse({'ok': False, 'mensagem': str(erro)}, status=422)
    return JsonResponse({'ok': True, 'max_pedidos': MAX_PEDIDOS_POR_REQUISICAO, **plano})


# Função Objetivo: Botão "Atualizar dia" (o ícone dentro de cada dia do calendário): coleta 1 dia INTEIRO da conta toda (todos os SKUs).
@require_POST
def view_vendas_atualizar_dia(request):
    from integracao_mercado_livre.servicos.coletar_vendas_ml import coletar_dia

    corpo = _ler_json(request) or {}
    try:
        dia = datetime.strptime(str(corpo.get('dia') or ''), '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'ok': False, 'mensagem': 'Dia inválido. Recarregue a página e tente de novo.'}, status=400)
    empresa, usuario = obter_empresa_ativa(), _nome_usuario(request)
    return _responder_coleta(lambda: coletar_dia(empresa, dia, usuario))


# Função Objetivo: Botão "Coletar período da conta" (depois da confirmação na janela): só dispara a coleta em segundo plano e responde na hora.
# Se já há uma rodando, devolve o estado dela em vez de começar outra.
@require_POST
def view_vendas_periodo_iniciar(request):
    from integracao_mercado_livre.servicos.coletar_vendas_ml import ErroColetaVendas, dias_padrao, iniciar_periodo

    corpo = _ler_json(request) or {}
    try:
        estado, _ = iniciar_periodo(obter_empresa_ativa(), _inteiro(corpo.get('dias'), dias_padrao()), _nome_usuario(request),
                                    reler_tudo=_verdadeiro(corpo.get('reler_tudo')))
    except ErroColetaVendas as erro:
        return JsonResponse({'status': 'erro', 'mensagem': str(erro)}, status=422)
    return JsonResponse(estado)


# Função Objetivo: Polling da barra de andamento (GET simples, só lê o cache). Terminou ou deu erro: entrega o resultado UMA vez.
@require_GET
def view_vendas_periodo_status(request):
    from integracao_mercado_livre.servicos.coletar_vendas_ml import ler_estado_periodo

    return JsonResponse(ler_estado_periodo(obter_empresa_ativa()))


# Função Objetivo: Botão "Parar": a coleta termina o dia que está lendo e encerra (o que já foi coletado fica salvo e conta como coberto).
@require_POST
def view_vendas_periodo_parar(request):
    from integracao_mercado_livre.servicos.coletar_vendas_ml import pedir_parada

    estado = pedir_parada(obter_empresa_ativa())
    if estado is None:
        return JsonResponse({'status': 'ocioso', 'mensagem': 'Não há coleta de período em andamento.'})
    return JsonResponse(estado)
