# agenda_videos/views.py

from datetime import timedelta
from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.contexto_tela_agenda_videos import ContextoTelaAgendaVideos
from agenda_videos.funcoes_auxiliares.roadmap_produto import calcular_roadmap_produto, obter_mapa_periodos_por_fase
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import (
    sincronizar_roadmap_agenda_produto, CHAVES_PREPARACAO,
)
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia, calcular_janela_fase
from agenda_videos.models import StatusVideo, StatusPostagem, Fase, ConfiguracaoFase, Postagem

# * [EXPLICAÇÃO] → Qual fase vem depois de qual — só Diária e Semanal têm "próxima"
#                  (Mensal, ao terminar, não vira outra fase, vira Otimizado).
PROXIMA_FASE = {Fase.DIARIA: Fase.SEMANAL, Fase.SEMANAL: Fase.MENSAL}


def view_agenda_videos(request):
    contexto = ContextoTelaAgendaVideos(request).montar()
    return render(request, 'agenda_videos/estrutura_agenda_videos.html', contexto)


# Função Objetivo: Busca o ponto do roadmap e valida que ele realmente pode ser
# confirmado agora — nunca confia cegamente no que vem da URL.
def _buscar_ponto_clicavel_ou_none(produto, chave):
    roadmap = calcular_roadmap_produto(produto)
    return next((p for p in roadmap.pontos if p.chave == chave and p.clicavel), None)


# Função Objetivo: Busca a Postagem mais recente da ocorrência ATUAL do produto.
def _buscar_postagem_atual(produto, andamento):
    return Postagem.objects.filter(
        produto=produto, fase=andamento.fase_atual.fase, numero_ocorrencia=andamento.ocorrencia_atual,
    ).order_by('-criado_em').first()


# Função Objetivo: Renderiza o modal certo — 5 variações possíveis (1 pros 4 pontos de
# preparação + 4 pro sub-estado do ponto cíclico, dependendo da Postagem mais recente).
def view_confirmar_ponto_roadmap(request, produto_id, chave):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    ponto = _buscar_ponto_clicavel_ou_none(produto, chave)

    if ponto is None:
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    contexto = {'produto_id': produto_id, 'chave': chave, 'ponto': ponto}

    if chave in CHAVES_PREPARACAO:
        contexto['tipo_acao'] = 'confirmar_simples'
        if chave == 'roteiros':
            contexto['periodo_diaria'] = obter_mapa_periodos_por_fase().get(Fase.DIARIA)
        return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_roadmap.html', contexto)

    # * [EXPLICAÇÃO] → Ponto cíclico (Diária/Semanal/Mensal) — o sub-estado vem da
    #                  Postagem mais recente daquela ocorrência específica.
    andamento = produto.andamento_agenda
    postagem_atual = _buscar_postagem_atual(produto, andamento)

    if postagem_atual is None:
        contexto['tipo_acao'] = 'postar'
    elif postagem_atual.status == StatusPostagem.AGUARDANDO_APROVACAO:
        contexto['tipo_acao'] = 'resolver_aprovacao'
    elif postagem_atual.status == StatusPostagem.APROVADO:
        contexto['tipo_acao'] = 'replicar'
    elif postagem_atual.status == StatusPostagem.RECUSADO:
        contexto['tipo_acao'] = 'nova_tentativa'
    else:
        # * [EXPLICAÇÃO] → REPLICADO não deveria chegar aqui na prática — assim que
        #                  vira Replicado, a ocorrência já avança, e a nova ocorrência
        #                  não tem Postagem ainda (cai em 'postar'). Fallback defensivo.
        contexto['tipo_acao'] = 'postar'

    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_roadmap.html', contexto)


# Função Objetivo: Confirma 1 dos 4 pontos de preparação (Simples/Base/Roteiros/Completos).
def view_marcar_ponto_roadmap(request, produto_id, chave):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    ponto = _buscar_ponto_clicavel_ou_none(produto, chave)

    if ponto is None or chave not in CHAVES_PREPARACAO:
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
    return render(request, 'agenda_videos/parciais/estrutura_parcial_roadmap_produto.html', {'roadmap': roadmap_atualizado})


# Função Objetivo: Executa 1 das 5 ações do ciclo de postagem (postar/aprovado/
# recusado/replicar/nova_tentativa) — a máquina de estados do ponto cíclico.
def view_executar_acao_ciclica(request, produto_id, chave, acao):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    andamento = getattr(produto, 'andamento_agenda', None)

    if andamento is None or andamento.fase_atual.fase != chave:
        return HttpResponseBadRequest('Estado inválido — esse produto não está nessa fase agora.')

    postagem_atual = _buscar_postagem_atual(produto, andamento)
    agora = timezone.now()

    if acao == 'postar':
        if postagem_atual is not None:
            return HttpResponseBadRequest('Já existe uma postagem em andamento pra essa ocorrência.')
        janela = calcular_janela_ocorrencia(chave, andamento.inicio_fase, andamento.ocorrencia_atual)
        Postagem.objects.create(
            produto=produto, fase=chave, numero_ocorrencia=andamento.ocorrencia_atual,
            inicio_ocorrencia=janela.inicio, fim_ocorrencia=janela.fim,
            status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
        )

    elif acao in ('aprovado', 'recusado'):
        if postagem_atual is None or postagem_atual.status != StatusPostagem.AGUARDANDO_APROVACAO:
            return HttpResponseBadRequest('Estado inválido — não há postagem aguardando aprovação.')
        postagem_atual.status = StatusPostagem.APROVADO if acao == 'aprovado' else StatusPostagem.RECUSADO
        postagem_atual.aprovado_ou_recusado_em = agora
        postagem_atual.save()

    elif acao == 'nova_tentativa':
        # * [EXPLICAÇÃO] → Cria Postagem NOVA (não reaproveita a recusada) — decisão
        #                  do usuário: manter histórico de quantas tentativas levou.
        if postagem_atual is None or postagem_atual.status != StatusPostagem.RECUSADO:
            return HttpResponseBadRequest('Estado inválido — a postagem atual não foi recusada.')
        janela = calcular_janela_ocorrencia(chave, andamento.inicio_fase, andamento.ocorrencia_atual)
        Postagem.objects.create(
            produto=produto, fase=chave, numero_ocorrencia=andamento.ocorrencia_atual,
            inicio_ocorrencia=janela.inicio, fim_ocorrencia=janela.fim,
            status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
        )

    elif acao == 'replicar':
        if postagem_atual is None or postagem_atual.status != StatusPostagem.APROVADO:
            return HttpResponseBadRequest('Estado inválido — a postagem atual não foi aprovada.')
        postagem_atual.status = StatusPostagem.REPLICADO
        postagem_atual.replicado_em = agora
        postagem_atual.save()

        # * [EXPLICAÇÃO] → Avança a ocorrência, ou muda de fase se era a última —
        #                  reaproveita calcular_janela_fase (os mesmos 39 casos já
        #                  testados), nunca recalcula data na mão aqui.
        if andamento.ocorrencia_atual < andamento.fase_atual.periodo:
            andamento.ocorrencia_atual += 1
        else:
            proxima_fase = PROXIMA_FASE.get(andamento.fase_atual.fase)
            if proxima_fase is None:
                andamento.concluido = True
                andamento.concluido_em = timezone.now().date()
            else:
                config_proxima = ConfiguracaoFase.objects.filter(fase=proxima_fase).first()
                if config_proxima is None:
                    return HttpResponseBadRequest(
                        f'Configuração da fase "{proxima_fase}" ainda não existe — crie ela pelo admin antes.'
                    )
                referencia = andamento.fim_fase + timedelta(days=1)
                janela_proxima = calcular_janela_fase(proxima_fase, referencia, config_proxima.periodo)
                andamento.fase_atual = config_proxima
                andamento.ocorrencia_atual = 1
                andamento.inicio_fase = janela_proxima.inicio
                andamento.fim_fase = janela_proxima.fim
        andamento.save()

    else:
        return HttpResponseBadRequest(f'Ação desconhecida: {acao}')

    sincronizar_roadmap_agenda_produto(produto)
    roadmap_atualizado = calcular_roadmap_produto(produto)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_roadmap_produto.html', {'roadmap': roadmap_atualizado})