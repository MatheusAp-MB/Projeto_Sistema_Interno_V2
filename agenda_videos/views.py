# agenda_videos/views.py

from datetime import timedelta
from django.http import HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from agenda_videos.funcoes_auxiliares.contexto_tela_agenda_videos import ContextoTelaAgendaVideos
from agenda_videos.funcoes_auxiliares.roadmap_produto import (
    calcular_roadmap_produto, obter_mapa_periodos_por_fase, FASE_DA_CHAVE_PREPARACAO,
    calcular_indicador_pool_insuficiente, calcular_indicador_divergencia_fase_concluida,
)
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda_produto
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import calcular_indicadores_atraso
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import calcular_janela_ocorrencia, calcular_janela_fase
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


# Função Objetivo: Rebusca o produto do zero, sincroniza o roadmap, calcula os
# indicadores de card (atraso/risco/pool insuficiente/divergência) e renderiza
# o parcial do card — usado por TODA ação que muda estado e precisa devolver o
# card atualizado. Extraído (26/07, pente fino) — estava copiado quase idêntico
# em 4 views (view_marcar_ponto_roadmap, view_agendar_produto,
# view_executar_acao_ciclica, view_alternar_urgente).
def _recarregar_e_renderizar_card(request, produto_id):
    from produtos.models import Produto
    produto = Produto.objects.get(id=produto_id)
    sincronizar_roadmap_agenda_produto(produto)
    data_simulada = _resolver_data_simulada(request)
    if getattr(produto, 'andamento_agenda', None) and not produto.andamento_agenda.concluido:
        calcular_indicadores_atraso(produto, produto.andamento_agenda, data_referencia=data_simulada)
        produto.pool_insuficiente_tipo = calcular_indicador_pool_insuficiente(produto, produto.andamento_agenda)
    if getattr(produto, 'andamento_agenda', None):
        produto.divergencia_fase_concluida = calcular_indicador_divergencia_fase_concluida(produto, produto.andamento_agenda)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_card_produto.html', {
        'produto': produto, 'data_simulada': data_simulada,
    })


# Função Objetivo: Avança o AndamentoAgenda pra próxima ocorrência ou próxima
# fase — assume que a ocorrência atual já foi tratada (replicada, ou pulada via
# "seguir sem repor"), quem chama decide isso antes de chamar esta função.
# Explicação em detalhe: extraída (26/07) pra ser reaproveitada em 3 lugares —
# o clique normal de "replicar", o recálculo em massa ao salvar Configuração de
# Fases, e a ação "seguir sem repor" (Recusada com cota já cumprida).
# Não chama .save() sozinha — quem chama decide quando persistir.
def avancar_ocorrencia_ou_fase(andamento, ocorrencias_completadas):
    if ocorrencias_completadas < andamento.fase_atual.periodo:
        andamento.ocorrencia_atual = ocorrencias_completadas + 1
    else:
        proxima_fase = PROXIMA_FASE.get(andamento.fase_atual.fase)
        if proxima_fase is None:
            andamento.concluido = True
            andamento.concluido_em = timezone.now().date()
            andamento.concluido_marcado_em = timezone.now()
        else:
            config_proxima = ConfiguracaoFase.objects.filter(fase=proxima_fase).first()
            if config_proxima is None:
                raise ValueError(f'Configuração da fase "{proxima_fase}" ainda não existe.')
            # * [EXPLICAÇÃO] → Referência é a data REAL do fim da última ocorrência
            #                  que de fato aconteceu (nunca andamento.fim_fase, que
            #                  fica desatualizado se o periodo mudar no meio da
            #                  fase). "ocorrencias_completadas" pode ser a que acabou
            #                  de ser replicada (clique normal) ou a última que
            #                  realmente aconteceu antes de pular direto pra próxima
            #                  fase (recálculo em massa, ver recalcular_andamentos_da_fase).
            janela_ocorrencia_referencia = calcular_janela_ocorrencia(
                andamento.fase_atual.fase, andamento.inicio_fase, ocorrencias_completadas,
            )
            referencia = janela_ocorrencia_referencia.fim + timedelta(days=1)
            janela_proxima = calcular_janela_fase(proxima_fase, referencia, config_proxima.periodo)
            andamento.fase_atual = config_proxima
            andamento.ocorrencia_atual = 1
            andamento.inicio_fase = janela_proxima.inicio
            andamento.fim_fase = janela_proxima.fim

    if not andamento.concluido:
        janela_ocorrencia_nova = calcular_janela_ocorrencia(
            andamento.fase_atual.fase, andamento.inicio_fase, andamento.ocorrencia_atual,
        )
        andamento.fim_ocorrencia_atual = janela_ocorrencia_nova.fim


# Função Objetivo: Reavalia TODO produto Ativo OU Pausado (não Descontinuado,
# não concluído) atualmente na fase informada — chamado sempre que a
# Configuração daquela fase é salva. Pausado ENTRA de propósito (26/07) —
# pausar é "temporariamente fora de atividade" (ex: falta de estoque), não
# "ignorar pra sempre"; a contagem de ocorrência/fase continua rodando por
# baixo mesmo pausado. Descontinuado fica de fora — é escopo encerrado de
# vez, só o Admin mexe nele por enquanto (decisão a repensar depois).
# NUNCA mexe numa postagem já aberta (Aguardando/Aprovado/Recusado); só
# decide avançar direto quem não tinha nada postado ainda pra ocorrência
# atual, ou atualiza fim_fase pra refletir o periodo novo em quem continua na
# mesma fase. O caso Recusado com cota já cumprida é resolvido depois, na hora
# que o usuário abrir aquele ponto (ver view_confirmar_ponto_roadmap).
def recalcular_andamentos_da_fase(config_fase):
    andamentos = AndamentoAgenda.objects.filter(
        fase_atual=config_fase, concluido=False,
        status_manual__in=[StatusManualAgenda.ATIVO, StatusManualAgenda.PAUSADO],
    ).select_related('produto')

    for andamento in andamentos:
        completadas = andamento.ocorrencia_atual - 1

        if completadas < config_fase.periodo:
            janela_fase = calcular_janela_fase(config_fase.fase, andamento.inicio_fase, config_fase.periodo)
            andamento.fim_fase = janela_fase.fim
            andamento.save(update_fields=['fim_fase'])
            continue

        postagem_atual = _buscar_postagem_atual(andamento.produto, andamento)

        if postagem_atual is None:
            # * [EXPLICAÇÃO] → Nunca postou essa ocorrência — não é mais
            #                  necessária com o periodo novo, avança direto.
            avancar_ocorrencia_ou_fase(andamento, ocorrencias_completadas=completadas)
            andamento.save()
        else:
            # * [EXPLICAÇÃO] → Aguardando/Aprovado: resolve sozinho no próximo
            #                  "já repliquei" (comparação já é ao vivo). Recusado:
            #                  o modal detecta a cota cumprida na hora de abrir.
            #                  Só atualiza a data, nunca mexe na postagem aberta.
            janela_fase = calcular_janela_fase(config_fase.fase, andamento.inicio_fase, config_fase.periodo)
            andamento.fim_fase = janela_fase.fim
            andamento.save(update_fields=['fim_fase'])


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
            # * [EXPLICAÇÃO] → Se a cota da fase já foi cumprida (periodo mudou
            #                  pra menos enquanto essa ocorrência estava recusada),
            #                  oferece a opção de seguir sem repor — ver 'seguir'
            #                  no dicionário ACOES_CICLICAS.
            completadas = andamento.ocorrencia_atual - 1
            if completadas >= andamento.fase_atual.periodo:
                contexto['tipo_acao'] = 'recusado_cota_cumprida'
            else:
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
            progresso.video_simples_marcado_em = timezone.now()
        else:
            progresso.video_base_status = StatusVideo.GERADO
            progresso.video_base_marcado_em = timezone.now()
        progresso.save()

    else:
        # * [EXPLICAÇÃO] → roteiros_diaria/completos_diaria/roteiros_semanal/
        #                  completos_semanal/roteiros_mensal/completos_mensal —
        #                  todos operam em cima do PreparacaoVideoFase DAQUELA fase.
        fase = FASE_DA_CHAVE_PREPARACAO[chave]
        periodo_atual = obter_mapa_periodos_por_fase().get(fase)
        preparacao, _ = PreparacaoVideoFase.objects.get_or_create(produto=produto, fase=fase)

        if chave.startswith('roteiros_'):
            preparacao.roteiros_gerados = True
            preparacao.roteiros_quantidade_no_clique = periodo_atual
            preparacao.roteiros_marcado_em = timezone.now()
        elif chave.startswith('completos_'):
            preparacao.completos_produzidos = True
            preparacao.completos_quantidade_no_clique = periodo_atual
            preparacao.completos_marcado_em = timezone.now()
        preparacao.save()

    return _recarregar_e_renderizar_card(request, produto.id)


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
            'concluido_marcado_em': None,
            'agendado_em': timezone.now(),
        }
    )

    # * [EXPLICAÇÃO] → Marca como "pulada" (preparação automática) toda fase ANTES
    #                  da escolhida — mesmo espírito da Decisão A já usada na
    #                  importação. Período usa o valor configurado de cada fase
    #                  pulada, pra manter "roteiros_insuficientes" consistente.
    # * [EXPLICAÇÃO] → Fases puladas NÃO ganham roteiros_marcado_em/completos_
    #                  marcado_em (26/07) — nunca aconteceu um clique real ali,
    #                  seria inventar um timestamp pra algo que foi automático.
    indice_inicial = ORDEM_FASES.index(fase_inicial)
    for fase_pulada in ORDEM_FASES[:indice_inicial]:
        PreparacaoVideoFase.objects.update_or_create(
            produto=produto, fase=fase_pulada,
            defaults={'roteiros_gerados': True, 'completos_produzidos': True},
        )

    return _recarregar_e_renderizar_card(request, produto.id)


# ===================================================================
# Ações do ciclo cíclico (Diária/Semanal/Mensal) — cada uma isolada
# numa função própria (26/07, pente fino), assinatura idêntica pras 6:
# (produto, andamento, postagem_atual, chave, agora) → HttpResponseBadRequest
# em caso de erro, ou None em caso de sucesso. view_executar_acao_ciclica
# só valida o estado geral e despacha pra função certa.
# ===================================================================

def _acao_postar(produto, andamento, postagem_atual, chave, agora):
    if postagem_atual is not None:
        return HttpResponseBadRequest('Já existe uma postagem em andamento pra essa ocorrência.')
    janela = calcular_janela_ocorrencia(chave, andamento.inicio_fase, andamento.ocorrencia_atual)
    Postagem.objects.create(
        produto=produto, fase=chave, numero_ocorrencia=andamento.ocorrencia_atual,
        inicio_ocorrencia=janela.inicio, fim_ocorrencia=janela.fim,
        status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
    )
    return None


def _acao_marcar_aprovado_ou_recusado(produto, andamento, postagem_atual, chave, agora, novo_status):
    if postagem_atual is None or postagem_atual.status != StatusPostagem.AGUARDANDO_APROVACAO:
        return HttpResponseBadRequest('Estado inválido — não há postagem aguardando aprovação.')
    postagem_atual.status = novo_status
    postagem_atual.aprovado_ou_recusado_em = agora
    postagem_atual.save()
    return None


def _acao_aprovar(produto, andamento, postagem_atual, chave, agora):
    return _acao_marcar_aprovado_ou_recusado(produto, andamento, postagem_atual, chave, agora, StatusPostagem.APROVADO)


def _acao_recusar(produto, andamento, postagem_atual, chave, agora):
    return _acao_marcar_aprovado_ou_recusado(produto, andamento, postagem_atual, chave, agora, StatusPostagem.RECUSADO)


def _acao_nova_tentativa(produto, andamento, postagem_atual, chave, agora):
    if postagem_atual is None or postagem_atual.status != StatusPostagem.RECUSADO:
        return HttpResponseBadRequest('Estado inválido — a postagem atual não foi recusada.')
    janela = calcular_janela_ocorrencia(chave, andamento.inicio_fase, andamento.ocorrencia_atual)
    Postagem.objects.create(
        produto=produto, fase=chave, numero_ocorrencia=andamento.ocorrencia_atual,
        inicio_ocorrencia=janela.inicio, fim_ocorrencia=janela.fim,
        status=StatusPostagem.AGUARDANDO_APROVACAO, aguardando_aprovacao_em=agora,
    )
    return None


def _acao_seguir_sem_repor(produto, andamento, postagem_atual, chave, agora):
    # * [EXPLICAÇÃO] → "Seguir sem repor" — só existe pra Recusada com cota já
    #                  cumprida (periodo encolheu no meio do caminho). Nunca
    #                  cria Postagem nova — a recusada fica no histórico
    #                  exatamente como ficou, sem resolução, e o produto avança
    #                  mesmo assim.
    if postagem_atual is None or postagem_atual.status != StatusPostagem.RECUSADO:
        return HttpResponseBadRequest('Estado inválido — a postagem atual não foi recusada.')
    completadas = andamento.ocorrencia_atual - 1
    if completadas < andamento.fase_atual.periodo:
        return HttpResponseBadRequest('A cota desta fase ainda não foi cumprida — não é possível seguir sem repor.')
    try:
        avancar_ocorrencia_ou_fase(andamento, ocorrencias_completadas=completadas)
    except ValueError as erro:
        return HttpResponseBadRequest(str(erro))
    andamento.save()
    return None


def _acao_replicar(produto, andamento, postagem_atual, chave, agora):
    if postagem_atual is None or postagem_atual.status != StatusPostagem.APROVADO:
        return HttpResponseBadRequest('Estado inválido — a postagem atual não foi aprovada.')
    postagem_atual.status = StatusPostagem.REPLICADO
    postagem_atual.replicado_em = agora
    postagem_atual.save()

    try:
        avancar_ocorrencia_ou_fase(andamento, ocorrencias_completadas=andamento.ocorrencia_atual)
    except ValueError as erro:
        return HttpResponseBadRequest(str(erro))
    andamento.save()
    return None


ACOES_CICLICAS = {
    'postar': _acao_postar,
    'aprovado': _acao_aprovar,
    'recusado': _acao_recusar,
    'nova_tentativa': _acao_nova_tentativa,
    'seguir': _acao_seguir_sem_repor,
    'replicar': _acao_replicar,
}


def view_executar_acao_ciclica(request, produto_id, chave, acao):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)
    andamento = getattr(produto, 'andamento_agenda', None)

    if andamento is None or andamento.fase_atual.fase != chave:
        return HttpResponseBadRequest('Estado inválido — esse produto não está nessa fase agora.')

    funcao_acao = ACOES_CICLICAS.get(acao)
    if funcao_acao is None:
        return HttpResponseBadRequest(f'Ação desconhecida: {acao}')

    postagem_atual = _buscar_postagem_atual(produto, andamento)
    agora = timezone.now()

    resposta_erro = funcao_acao(produto, andamento, postagem_atual, chave, agora)
    if resposta_erro is not None:
        return resposta_erro

    return _recarregar_e_renderizar_card(request, produto.id)


# Função Objetivo: Liga/desliga "Urgente" — qualquer produto, sem confirmação
# (reversível, baixo risco, diferente dos pontos do roadmap).
def view_alternar_urgente(request, produto_id):
    from produtos.models import Produto
    produto = get_object_or_404(Produto, id=produto_id)

    roadmap_agenda, _ = RoadmapAgenda.objects.get_or_create(produto=produto)
    roadmap_agenda.urgente = not roadmap_agenda.urgente
    roadmap_agenda.save()

    return _recarregar_e_renderizar_card(request, produto.id)


# Função Objetivo: Valida quantidade_postagens/periodo — só aceita inteiro
# >= 1 (regra de negócio: "0 vídeos a cada 0 dias" não existe). Qualquer
# coisa fora disso (vazio, texto, negativo, zero) é tratada como inválida.
def _validar_inteiro_positivo(valor):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero >= 1 else None


# Função Objetivo: Tela de Configuração das fases (Diária/Semanal/Mensal) —
# substitui o Admin como forma de editar ConfiguracaoFase. Sempre mostra as
# 3 fases fixas (Fase.choices), mesmo que uma ainda não tenha registro no
# banco — nesse caso a linha aparece vazia, com aviso "não configurado", e
# o próprio submit cria o registro (update_or_create), nunca mais precisa
# passar pelo Admin.
def view_configuracoes_agenda_videos(request):
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.urls import reverse

    if request.method == 'POST':
        from django.db import transaction

        algum_salvo = False

        with transaction.atomic():
            for fase_valor, fase_label in Fase.choices:
                quantidade = _validar_inteiro_positivo(request.POST.get(f'{fase_valor}_quantidade_postagens'))
                periodo = _validar_inteiro_positivo(request.POST.get(f'{fase_valor}_periodo'))
                config_existente = ConfiguracaoFase.objects.filter(fase=fase_valor).first()

                if quantidade is None or periodo is None:
                    if config_existente is None:
                        messages.warning(request, f'{fase_label}: valor inválido — não foi possível criar a configuração.')
                    else:
                        messages.warning(request, f'{fase_label}: valor inválido — mantido o valor anterior.')
                    continue

                config_fase, _ = ConfiguracaoFase.objects.update_or_create(
                    fase=fase_valor,
                    defaults={'quantidade_postagens': quantidade, 'periodo': periodo},
                )
                algum_salvo = True
                recalcular_andamentos_da_fase(config_fase)

        if algum_salvo:
            messages.success(request, 'Configurações de fase salvas com sucesso.')
        return redirect(reverse('agenda_videos_configuracoes'))

    fases = []
    for fase_valor, fase_label in Fase.choices:
        config = ConfiguracaoFase.objects.filter(fase=fase_valor).first()
        fases.append({
            'valor': fase_valor,
            'label': fase_label,
            'quantidade_postagens': config.quantidade_postagens if config else '',
            'periodo': config.periodo if config else '',
            'configurado': config is not None,
        })

    return render(request, 'agenda_videos/estrutura_configuracoes_agenda_videos.html', {
        'fases': fases,
    })


# Função Objetivo: Modal de histórico de 1 produto (Formato A) — disparado
# pelo ícone novo no card, sempre mostra o histórico COMPLETO daquele produto.
def view_historico_produto(request, produto_id):
    from produtos.models import Produto
    from agenda_videos.funcoes_auxiliares.historico_roadmap import montar_historico_produto

    produto = get_object_or_404(Produto, id=produto_id)
    historico = montar_historico_produto(produto)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_historico_produto.html', {
        'historico': historico,
    })


# Função Objetivo: Valida uma data vinda de input HTML (YYYY-MM-DD) — devolve
# None se vazia ou inválida, nunca deixa passar string crua pro ORM.
def _validar_data(valor):
    from datetime import datetime
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


# Função Objetivo: Tela de relatório (Formato B) — produtos que têm pelo
# menos 1 Postagem batendo com os filtros, agrupados, cada um mostrando o
# histórico completo dele quando aberto (ver historico_roadmap.py).
def view_historico_agenda_videos(request):
    from django.core.paginator import Paginator
    from agenda_videos.funcoes_auxiliares.historico_roadmap import (
        listar_produtos_com_historico, montar_historico_produto,
    )

    busca = request.GET.get('busca', '').strip()
    filtros = {
        'fase': request.GET.getlist('fase'),
        'status': request.GET.getlist('status'),
        'data_de': _validar_data(request.GET.get('data_de')),
        'data_ate': _validar_data(request.GET.get('data_ate')),
        'urgente': request.GET.getlist('urgente'),
        'marcas': request.GET.getlist('marca'),
        'status_manual': request.GET.getlist('status_manual'),
    }

    produtos = listar_produtos_com_historico(busca=busca or None, filtros=filtros)

    try:
        por_pagina = int(request.GET.get('por_pagina', '25'))
    except ValueError:
        por_pagina = 25

    paginator = Paginator(produtos, por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))
    grupos = [montar_historico_produto(produto) for produto in pagina]

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    from produtos.models import Produto
    marcas_disponiveis = (
        Produto.objects
        .exclude(marca__isnull=True).exclude(marca='')
        .values_list('marca', flat=True).distinct().order_by('marca')
    )

    return render(request, 'agenda_videos/estrutura_historico_agenda_videos.html', {
        'grupos': grupos,
        'pagina': pagina,
        'busca': busca,
        'filtros': filtros,
        'opcoes_fase': Fase.choices,
        'opcoes_status': StatusPostagem.choices,
        'opcoes_status_manual': StatusManualAgenda.choices,
        'marcas_disponiveis': marcas_disponiveis,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
    })