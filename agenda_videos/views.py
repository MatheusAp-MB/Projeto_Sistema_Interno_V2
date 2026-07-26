# agenda_videos/views.py

from datetime import timedelta
from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.contexto_tela_agenda_videos import ContextoTelaAgendaVideos
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    calcular_roadmap_produto, obter_mapa_periodos_por_fase, FASE_DA_CHAVE_PREPARACAO,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import calcular_indicadores_atraso
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia, calcular_janela_fase
from django.utils import timezone
from agenda_videos.models import (
    StatusVideo, StatusPostagem, Fase, ConfiguracaoFase, Postagem,
    ProgressoProducaoVideo, PreparacaoVideoFase, AndamentoAgenda, StatusManualAgenda,
    RoadmapAgenda,
)

# * [EXPLICAÇÃO] → Ordem das fases — usado pra saber quais ficam "puladas" quando o
#                  usuário escolhe começar direto numa fase mais adiante (ex: Mensal
#                  pula Diária e Semanal). Mesmo espírito da Decisão A já usada na
#                  importação da planilha — fase pulada não exige preparação real.
ORDEM_FASES = [Fase.DIARIA, Fase.SEMANAL, Fase.MENSAL]

PROXIMA_FASE = {Fase.DIARIA: Fase.SEMANAL, Fase.SEMANAL: Fase.MENSAL}

# * [EXPLICAÇÃO] → As 3 chaves cíclicas (têm sub-estado de Postagem) — todo o resto
#                  clicável usa o modal simples de 1 confirmação.
CHAVES_CICLICAS = {'diaria', 'semanal', 'mensal'}


def view_agenda_videos(request):
    contexto = ContextoTelaAgendaVideos(request).montar()
    return render(request, 'agenda_videos/estrutura_agenda_videos.html', contexto)


def _buscar_ponto_clicavel_ou_none(produto, chave):
    roadmap = calcular_roadmap_produto(produto)
    return next((p for p in roadmap.pontos if p.chave == chave and p.clicavel), None)


def _buscar_postagem_atual(produto, andamento):
    return Postagem.objects.filter(
        produto=produto, fase=andamento.fase_atual.fase, numero_ocorrencia=andamento.ocorrencia_atual,
    ).order_by('-criado_em').first()


# Função Objetivo: Lê a data simulada — só funciona com DEBUG=True, igual a tela
# principal (mesma regra de segurança: nunca em produção, mesmo que forjada na URL).
def _resolver_data_simulada(request):
    from datetime import datetime
    from django.conf import settings
    if not settings.DEBUG:
        return None
    valor_bruto = request.POST.get('simular_data') or request.GET.get('simular_data', '')
    valor_bruto = valor_bruto.strip()
    if not valor_bruto:
        return None
    try:
        return datetime.strptime(valor_bruto, '%Y-%m-%d').date()
    except ValueError:
        return None


def view_confirmar_ponto_roadmap(request, produto_id, chave):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    ponto = _buscar_ponto_clicavel_ou_none(produto, chave)

    if ponto is None:
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    # * [EXPLICAÇÃO] → Propaga a data simulada (se houver) pros botões do modal —
    #                  "se eu tô simulando, quero que TUDO use a data simulada".
    simular_data = request.GET.get('simular_data', '')
    contexto = {'produto_id': produto_id, 'chave': chave, 'ponto': ponto, 'simular_data': simular_data}

    if chave == 'pronto_agendamento':
        contexto['tipo_acao'] = 'escolher_fase_inicial'
        return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_roadmap.html', contexto)

    if chave in CHAVES_CICLICAS:
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
            contexto['tipo_acao'] = 'postar'
    else:
        contexto['tipo_acao'] = 'confirmar_simples'
        # * [EXPLICAÇÃO] → "Roteiros de X" precisa do período DAQUELA fase, não
        #                  sempre da Diária como era antes.
        if chave in FASE_DA_CHAVE_PREPARACAO and 'roteiros' in chave:
            fase_do_ponto = FASE_DA_CHAVE_PREPARACAO[chave]
            contexto['periodo_fase'] = obter_mapa_periodos_por_fase().get(fase_do_ponto)

    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_roadmap.html', contexto)


def view_marcar_ponto_roadmap(request, produto_id, chave):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    ponto = _buscar_ponto_clicavel_ou_none(produto, chave)

    if ponto is None or chave in CHAVES_CICLICAS or chave == 'pronto_agendamento':
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    if chave in ('simples', 'base'):
        progresso, _ = ProgressoProducaoVideo.objects.get_or_create(produto=produto)
        if chave == 'simples':
            progresso.video_simples_status = StatusVideo.GERADO
        else:
            progresso.video_base_status = StatusVideo.GERADO
        progresso.save()

    else:
        # * [EXPLICAÇÃO] → roteiros_diaria/completos_diaria/roteiros_semanal/
        #                  completos_semanal/roteiros_mensal/completos_mensal —
        #                  todos operam em cima do PreparacaoVideoFase DAQUELA fase.
        fase = FASE_DA_CHAVE_PREPARACAO[chave]
        preparacao, _ = PreparacaoVideoFase.objects.get_or_create(produto=produto, fase=fase)

        if chave.startswith('roteiros_'):
            preparacao.roteiros_gerados = True
        elif chave.startswith('completos_'):
            preparacao.completos_produzidos = True
        preparacao.save()

    # * [EXPLICAÇÃO] → Busca o produto DE NOVO, do zero — Django guarda ("cacheia")
    #                  no objeto `produto` a 1ª versão de progresso_producao_video
    #                  que ele buscar (lá em _buscar_ponto_clicavel_ou_none, no topo
    #                  desta view). Salvar um OBJETO SEPARADO (via get_or_create)
    #                  não atualiza esse cache — sem isso, a resposta do clique
    #                  mostraria o estado antigo, mesmo o banco já estando certo.
    produto = Produto.objects.get(id=produto.id)
    sincronizar_roadmap_agenda_produto(produto)
    data_simulada = _resolver_data_simulada(request)
    if getattr(produto, 'andamento_agenda', None) and not produto.andamento_agenda.concluido:
        calcular_indicadores_atraso(produto, produto.andamento_agenda, data_referencia=data_simulada)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_card_produto.html', {
        'produto': produto, 'data_simulada': data_simulada,
    })


# Função Objetivo: Agenda o produto formalmente — cria AndamentoAgenda na fase
# escolhida, e marca como "puladas" (preparação automática, sem exigir trabalho
# real) todas as fases ANTES da escolhida.
def view_agendar_produto(request, produto_id, fase_inicial):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    ponto = _buscar_ponto_clicavel_ou_none(produto, 'pronto_agendamento')

    if ponto is None:
        return HttpResponseBadRequest('Esse produto não está pronto pra ser agendado agora.')

    if fase_inicial not in ORDEM_FASES:
        return HttpResponseBadRequest(f'Fase inválida: {fase_inicial}')

    config_fase_inicial = ConfiguracaoFase.objects.filter(fase=fase_inicial).first()
    if config_fase_inicial is None:
        return HttpResponseBadRequest(f'Configuração da fase "{fase_inicial}" ainda não existe — crie ela pelo admin antes.')

    hoje = timezone.now().date()
    janela = calcular_janela_fase(fase_inicial, hoje, config_fase_inicial.periodo)
    # * [EXPLICAÇÃO] → fim_ocorrencia_atual da 1ª ocorrência (ocorrencia_atual=1
    #                  sempre no agendamento) — nunca da janela da fase inteira.
    janela_ocorrencia_1 = calcular_janela_ocorrencia(fase_inicial, janela.inicio, 1)

    AndamentoAgenda.objects.update_or_create(
        produto=produto,
        defaults={
            'fase_atual': config_fase_inicial,
            'ocorrencia_atual': 1,
            'inicio_fase': janela.inicio,
            'fim_fase': janela.fim,
            'fim_ocorrencia_atual': janela_ocorrencia_1.fim,
            'status_manual': StatusManualAgenda.ATIVO,
            'concluido': False,
            'concluido_em': None,
        }
    )

    # * [EXPLICAÇÃO] → Marca como "pulada" (preparação automática) toda fase ANTES
    #                  da escolhida — mesmo espírito da Decisão A já usada na
    #                  importação. Período usa o valor configurado de cada fase
    #                  pulada, pra manter "roteiros_insuficientes" consistente.
    indice_inicial = ORDEM_FASES.index(fase_inicial)
    for fase_pulada in ORDEM_FASES[:indice_inicial]:
        PreparacaoVideoFase.objects.update_or_create(
            produto=produto, fase=fase_pulada,
            defaults={'roteiros_gerados': True, 'completos_produzidos': True},
        )

    produto = Produto.objects.get(id=produto.id)
    sincronizar_roadmap_agenda_produto(produto)
    data_simulada = _resolver_data_simulada(request)
    if getattr(produto, 'andamento_agenda', None) and not produto.andamento_agenda.concluido:
        calcular_indicadores_atraso(produto, produto.andamento_agenda, data_referencia=data_simulada)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_card_produto.html', {
        'produto': produto, 'data_simulada': data_simulada,
    })


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
                    return HttpResponseBadRequest(f'Configuração da fase "{proxima_fase}" ainda não existe.')
                referencia = andamento.fim_fase + timedelta(days=1)
                janela_proxima = calcular_janela_fase(proxima_fase, referencia, config_proxima.periodo)
                andamento.fase_atual = config_proxima
                andamento.ocorrencia_atual = 1
                andamento.inicio_fase = janela_proxima.inicio
                andamento.fim_fase = janela_proxima.fim

        # * [EXPLICAÇÃO] → Recalcula o vencimento da ocorrência (nova ou a mesma
        #                  fase, avançada) — cobre os 2 casos do if/else acima.
        if not andamento.concluido:
            janela_ocorrencia_nova = calcular_janela_ocorrencia(
                andamento.fase_atual.fase, andamento.inicio_fase, andamento.ocorrencia_atual,
            )
            andamento.fim_ocorrencia_atual = janela_ocorrencia_nova.fim
        andamento.save()

    else:
        return HttpResponseBadRequest(f'Ação desconhecida: {acao}')

    # * [EXPLICAÇÃO] → Mesmo motivo do view_marcar_ponto_roadmap — busca fresco,
    #                  sem cache de relação grudado, antes de montar a resposta.
    produto = Produto.objects.get(id=produto.id)
    sincronizar_roadmap_agenda_produto(produto)
    data_simulada = _resolver_data_simulada(request)
    if getattr(produto, 'andamento_agenda', None) and not produto.andamento_agenda.concluido:
        calcular_indicadores_atraso(produto, produto.andamento_agenda, data_referencia=data_simulada)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_card_produto.html', {
        'produto': produto, 'data_simulada': data_simulada,
    })


# Função Objetivo: Liga/desliga "Urgente" — qualquer produto, sem confirmação
# (reversível, baixo risco, diferente dos pontos do roadmap).
def view_alternar_urgente(request, produto_id):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)

    roadmap_agenda, _ = RoadmapAgenda.objects.get_or_create(produto=produto)
    roadmap_agenda.urgente = not roadmap_agenda.urgente
    roadmap_agenda.save()

    produto = Produto.objects.get(id=produto.id)
    data_simulada = _resolver_data_simulada(request)
    if getattr(produto, 'andamento_agenda', None) and not produto.andamento_agenda.concluido:
        calcular_indicadores_atraso(produto, produto.andamento_agenda, data_referencia=data_simulada)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_card_produto.html', {
        'produto': produto, 'data_simulada': data_simulada,
    })