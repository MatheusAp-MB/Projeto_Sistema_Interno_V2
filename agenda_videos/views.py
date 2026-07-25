# agenda_videos/views.py

from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from agenda_videos.funcoes_auxiliares.contexto_tela_agenda_videos import ContextoTelaAgendaVideos
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_roadmap_produto
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from agenda_videos.funcoes_auxiliares.roadmap_produto import obter_mapa_periodos_por_fase
from agenda_videos.models import StatusVideo, Fase


def view_agenda_videos(request):
    contexto = ContextoTelaAgendaVideos(request).montar()
    return render(request, 'agenda_videos/estrutura_agenda_videos.html', contexto)


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

    periodo_diaria = None
    if chave == 'roteiros':
        periodo_diaria = obter_mapa_periodos_por_fase().get(Fase.DIARIA)

    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_roadmap.html', {
        'produto_id': produto_id, 'chave': chave, 'ponto': ponto, 'periodo_diaria': periodo_diaria,
    })


# Função Objetivo: Confirma o ponto — marca o campo real como concluído, sem reversão,
# e sincroniza o RoadmapAgenda na hora (recálculo direto, 1 dos 2 mecanismos de sincronização).
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
        periodo_diaria = obter_mapa_periodos_por_fase().get(Fase.DIARIA)
        if periodo_diaria:
            progresso.quantidade_roteiros = periodo_diaria
    elif chave == 'completos':
        progresso.completos_produzidos = True
    progresso.save()

    sincronizar_roadmap_agenda_produto(produto)

    roadmap_atualizado = calcular_roadmap_produto(produto)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_roadmap_produto.html', {
        'roadmap': roadmap_atualizado,
    })