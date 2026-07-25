# agenda_videos/views.py

from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from agenda_videos.funcoes_auxiliares.contexto_tela_diarios import ContextoTelaDiarios
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    calcular_roadmap_produto, obter_mapa_periodos_por_fase,
)
from agenda_videos.models import StatusVideo, Fase


def view_diarios(request):
    contexto = ContextoTelaDiarios(request).montar()
    return render(request, 'agenda_videos/estrutura_diarios.html', contexto)


# Função Objetivo: Busca o ponto do roadmap e valida que ele realmente pode ser
# confirmado agora — nunca confia cegamente no que vem da URL.
def _buscar_ponto_clicavel_ou_none(produto, chave):
    roadmap = calcular_roadmap_produto(produto)
    return next((p for p in roadmap.pontos if p.chave == chave and p.clicavel), None)


# Função Objetivo: Renderiza o modal de confirmação pro ponto clicado.
def view_confirmar_ponto_roadmap(request, produto_id, chave):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    ponto = _buscar_ponto_clicavel_ou_none(produto, chave)

    if ponto is None:
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    # * [EXPLICAÇÃO] → "Roteiros" tem mensagem própria — a confirmação já assume
    #                  que foram gerados roteiros suficientes pros X dias da Diária
    #                  (X = período configurado), sem pedir número nenhum digitado.
    periodo_diaria = None
    if chave == 'roteiros':
        periodo_diaria = obter_mapa_periodos_por_fase().get(Fase.DIARIA)

    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_roadmap.html', {
        'produto_id': produto_id, 'chave': chave, 'ponto': ponto, 'periodo_diaria': periodo_diaria,
    })


# Função Objetivo: Confirma o ponto — marca o campo real como concluído, sem reversão.
def view_marcar_ponto_roadmap(request, produto_id, chave):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    ponto = _buscar_ponto_clicavel_ou_none(produto, chave)

    if ponto is None:
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    progresso = produto.progresso_producao_video
    if chave == 'simples':
        progresso.video_simples_status = StatusVideo.GERADO
    elif chave == 'base':
        progresso.video_base_status = StatusVideo.GERADO
    elif chave == 'roteiros':
        progresso.roteiros_gerados = True
        # * [EXPLICAÇÃO] → Padronizado (24/07): confirmar "Roteiros" assume que
        #                  foram gerados roteiros suficientes pros X dias da
        #                  Diária — quantidade_roteiros vira igual ao período
        #                  configurado, nunca um número digitado à mão.
        periodo_diaria = obter_mapa_periodos_por_fase().get(Fase.DIARIA)
        if periodo_diaria:
            progresso.quantidade_roteiros = periodo_diaria
    elif chave == 'completos':
        progresso.completos_produzidos = True
    progresso.save()

    roadmap_atualizado = calcular_roadmap_produto(produto)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_roadmap_produto.html', {
        'roadmap': roadmap_atualizado,
    })