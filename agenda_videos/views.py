# agenda_videos/views.py

# Função Objetivo: Views das 4 telas do app agenda_videos — Agenda de Vídeos
# (tela principal), Configurações (regras de cada fase), Histórico (relatório
# e modal por produto) e Postagem/Replicação Automática (execução em lote).
# Views de Postagem/Replicação Automática ainda não passaram por revisão de
# regras — só limpeza de import aqui; reescrita fica pra quando auditarmos
# agenda_videos/funcoes_auxiliares/postagem_automatica/orquestrador.py.

from datetime import date, datetime

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.contexto_tela_agenda_videos import ContextoTelaAgendaVideos
from agenda_videos.funcoes_auxiliares.drive import (
    calcular_diagnostico_preparo_drive, verificar_produto_no_drive, verificar_todos_no_drive,
)
from agenda_videos.funcoes_auxiliares.postagem_ciclica import ja_postou_hoje
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import calcular_indicadores_ciclo, listar_a_fazer_hoje
from agenda_videos.funcoes_auxiliares.historico_roadmap import listar_produtos_com_historico, montar_historico_produto
from agenda_videos.funcoes_auxiliares.postagem_automatica import listar_produtos_elegiveis
from agenda_videos.models import (
    StatusPostagem, Fase, ConfiguracaoFase, CicloVideo, StatusManualAgenda, ParticipacaoAgenda,
    ExecucaoPostagemAutomatica, ItemExecucaoPostagem, StatusItemExecucao,
    ExecucaoReplicacaoAutomatica, ItemExecucaoReplicacao, StatusExecucao, StatusItemExecucaoReplicacao,
)


# ===================================================================
# Agenda de Vídeos
# ===================================================================

def view_agenda_videos(request: HttpRequest) -> HttpResponse:
    contexto = ContextoTelaAgendaVideos(request).montar()
    return render(request, 'agenda_videos/estrutura_agenda_videos.html', contexto)


def _buscar_ciclo_atual(produto: Produto) -> CicloVideo | None:
    return produto.ciclos_video.first()


# Função Objetivo: Lê a data simulada — só funciona com DEBUG=True, igual a tela
# principal (mesma regra de segurança: nunca em produção, mesmo que forjada na URL).
def _resolver_data_simulada(request: HttpRequest) -> date | None:
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


# Função Objetivo: Rebusca o produto do zero, sincroniza os indicadores e
# renderiza o parcial do card — usado por TODA ação que muda estado e precisa
# devolver o card atualizado.
def _recarregar_e_renderizar_card(request: HttpRequest, produto_id: int, contexto_extra: dict | None = None) -> HttpResponse:
    produto = Produto.objects.get(id=produto_id)
    sincronizar_indicadores_agenda_produto(produto)
    data_simulada = _resolver_data_simulada(request)
    ciclo = _buscar_ciclo_atual(produto)
    if ciclo is not None:
        calcular_indicadores_ciclo(produto, ciclo, data_referencia=data_simulada)
        produto.ja_postou_hoje = ja_postou_hoje(produto, data_referencia=data_simulada)
    produto.diagnostico_drive = calcular_diagnostico_preparo_drive(produto)
    contexto = {'produto': produto, 'data_simulada': data_simulada}
    if contexto_extra:
        contexto.update(contexto_extra)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_card_produto.html', contexto)


# Função Objetivo: Modal de confirmação antes de marcar qualquer ponto —
# revalida que a etapa pedida ainda é a etapa REAL atual (evita agir em cima
# de estado desatualizado, ex: 2 abas abertas).
def view_confirmar_ponto_roadmap(request: HttpRequest, produto_id: int, chave: str) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)
    ciclo = _buscar_ciclo_atual(produto)

    if ciclo is None:
        return HttpResponseBadRequest('Este produto ainda não entrou na Agenda.')

    if ciclo.status == StatusPostagem.RECUSADO and chave == 'completo':
        tipo_acao = 'nova_tentativa'
    elif ciclo.etapa_atual() == chave:
        tipo_acao = {
            'base': 'confirmar_simples', 'roteiro': 'confirmar_simples', 'completo': 'confirmar_simples',
            'postar': 'postar', 'aguardando_aprovacao': 'resolver_aprovacao', 'replicar': 'replicar',
        }.get(chave)
    else:
        tipo_acao = None

    if tipo_acao is None:
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    simular_data = request.GET.get('simular_data', '')
    contexto = {
        'produto_id': produto_id, 'chave': chave, 'ciclo': ciclo,
        'tipo_acao': tipo_acao, 'simular_data': simular_data,
    }
    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_roadmap.html', contexto)


# Função Objetivo: Marca Base/Roteiro/Completo como feito — sem trava de
# data (podem ser feitos com antecedência, decisão confirmada na Frente 1).
def view_marcar_ponto_roadmap(request: HttpRequest, produto_id: int, chave: str) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)
    ciclo = _buscar_ciclo_atual(produto)

    if ciclo is None or chave not in ('base', 'roteiro', 'completo') or ciclo.etapa_atual() != chave:
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    agora = timezone.now()
    campo = f'{chave}_concluido_em'
    setattr(ciclo, campo, agora)
    ciclo.save(update_fields=[campo])

    return _recarregar_e_renderizar_card(request, produto.id)


# Função Objetivo: Agenda o produto formalmente — cria o 1º CicloVideo
# (Simples #1). Não existe mais "escolher fase inicial" (decisão da
# reestruturação, 30/07) — todo produto sempre começa do zero, no Simples.
def view_agendar_produto(request: HttpRequest, produto_id: int) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)

    if produto.ciclos_video.exists():
        return HttpResponseBadRequest('Este produto já está na Agenda.')

    CicloVideo.iniciar_agenda(produto)
    return _recarregar_e_renderizar_card(request, produto.id)


# ===================================================================
# Ações do ciclo (Base/Roteiro/Completo já ficaram em view_marcar_ponto_
# roadmap acima) — Postar/Aprovar/Recusar/Nova tentativa/Seguir sem
# repor/Replicar, cada uma isolada, assinatura idêntica: (produto, ciclo,
# agora) → HttpResponseBadRequest em erro, ou None em sucesso.
# ===================================================================

def _acao_postar(produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    if ciclo.etapa_atual() != 'postar':
        return HttpResponseBadRequest('Esse produto não está pronto pra postar agora.')
    if ja_postou_hoje(produto):
        return HttpResponseBadRequest('Este produto já teve vídeo postado hoje — só é permitida 1 postagem por dia.')
    ciclo.marcar_aguardando_aprovacao()
    return None


def _acao_marcar_aprovado_ou_recusado(ciclo: CicloVideo, agora: datetime, novo_status: str) -> HttpResponseBadRequest | None:
    if ciclo.status != StatusPostagem.AGUARDANDO_APROVACAO:
        return HttpResponseBadRequest('Estado inválido — não há postagem aguardando aprovação.')
    ciclo.status = novo_status
    ciclo.aprovado_ou_recusado_em = agora
    ciclo.save(update_fields=['status', 'aprovado_ou_recusado_em'])
    return None


def _acao_aprovar(produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    return _acao_marcar_aprovado_ou_recusado(ciclo, agora, StatusPostagem.APROVADO)


def _acao_recusar(produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    return _acao_marcar_aprovado_ou_recusado(ciclo, agora, StatusPostagem.RECUSADO)


# Função Objetivo: Recusado precisa refazer o Completo antes de postar de
# novo (regra confirmada na Frente 1) — reabre pra edição; o usuário marca
# "Completo" de novo antes de poder postar.
def _acao_nova_tentativa(produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    if ciclo.status != StatusPostagem.RECUSADO:
        return HttpResponseBadRequest('Estado inválido — a postagem atual não foi recusada.')
    ciclo.status = None
    ciclo.completo_concluido_em = None
    ciclo.save(update_fields=['status', 'completo_concluido_em'])
    return None


# Função Objetivo: "Seguir sem repor" — só existe pra Recusada com cota já
# cumprida (periodo encolheu no meio do caminho, edge case raro). Nunca
# resolve a recusada — ela fica no histórico exatamente como ficou, sem
# resolução, e o produto avança pra próxima fase mesmo assim.
def _acao_seguir_sem_repor(produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    if ciclo.status != StatusPostagem.RECUSADO:
        return HttpResponseBadRequest('Estado inválido — a postagem atual não foi recusada.')

    config_atual = ConfiguracaoFase.objects.get(fase=ciclo.fase)
    if config_atual.dentro_do_periodo(ciclo.numero_ocorrencia + 1):
        return HttpResponseBadRequest('A cota desta fase ainda não foi cumprida — não é possível seguir sem repor.')

    proxima_fase = config_atual.proxima_fase
    if proxima_fase is None:
        return HttpResponseBadRequest('Não há próxima fase configurada.')

    CicloVideo.objects.create(
        produto=produto, fase=proxima_fase.fase, numero_ocorrencia=1, data_devida=agora.date(),
    )
    return None


def _acao_replicar(produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    if ciclo.status != StatusPostagem.APROVADO:
        return HttpResponseBadRequest('Estado inválido — a postagem atual não foi aprovada.')
    # * [EXPLICAÇÃO] → Clique manual (não é o agente) — não sabe quais MLBs
    #                  foram replicados de verdade, então vai vazio. Só a
    #                  automação real (api/replicacao_automatica) preenche
    #                  isso de fato.
    ciclo.marcar_replicado(mlbs_replicados=[], mlbs_nao_encontrados=[])
    return None


ACOES_CICLICAS = {
    'postar': _acao_postar,
    'aprovado': _acao_aprovar,
    'recusado': _acao_recusar,
    'nova_tentativa': _acao_nova_tentativa,
    'seguir': _acao_seguir_sem_repor,
    'replicar': _acao_replicar,
}


def view_executar_acao_ciclica(request: HttpRequest, produto_id: int, acao: str) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)
    ciclo = _buscar_ciclo_atual(produto)

    if ciclo is None:
        return HttpResponseBadRequest('Este produto ainda não entrou na Agenda.')

    funcao_acao = ACOES_CICLICAS.get(acao)
    if funcao_acao is None:
        return HttpResponseBadRequest(f'Ação desconhecida: {acao}')

    agora = timezone.now()
    resposta_erro = funcao_acao(produto, ciclo, agora)
    if resposta_erro is not None:
        return resposta_erro

    return _recarregar_e_renderizar_card(request, produto.id)


# Função Objetivo: Liga/desliga "Urgente" — qualquer produto, sem confirmação
# (reversível, baixo risco).
def view_alternar_urgente(request: HttpRequest, produto_id: int) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)

    participacao, _ = ParticipacaoAgenda.objects.get_or_create(produto=produto)
    participacao.urgente = not participacao.urgente
    participacao.save(update_fields=['urgente'])

    return _recarregar_e_renderizar_card(request, produto.id)


# Função Objetivo: Verifica os arquivos deste produto no Google Drive e
# avança quantos pontos os arquivos permitirem — 1 clique em vez de N.
# * [PENDENTE] → Ainda desativado (ver drive/verificador.py) — a chamada
# abaixo não faz nada de verdade até a estrutura de pastas ser redesenhada
# pro modelo novo.
def view_verificar_produto_drive(request: HttpRequest, produto_id: int) -> HttpResponse:
    get_object_or_404(Produto, id=produto_id)
    try:
        verificar_produto_no_drive(produto_id)
    except Exception:
        return _recarregar_e_renderizar_card(
            request, produto_id,
            contexto_extra={
                'erro_verificacao_drive': 'Não foi possível conectar ao Google Drive agora — tente novamente em instantes.',
            },
        )
    return _recarregar_e_renderizar_card(request, produto_id)


# Função Objetivo: Verifica TODO o catálogo de uma vez.
# * [PENDENTE] → Mesmo motivo acima — desativado até o redesenho do Drive.
def view_verificar_todos_drive(request: HttpRequest) -> HttpResponse:
    try:
        resumo_por_produto, sem_produto_no_banco = verificar_todos_no_drive()
    except Exception:
        messages.error(request, 'Não foi possível conectar ao Google Drive agora — tente novamente em instantes.')
        return redirect(reverse('agenda_videos_principal'))

    total_pontos = sum(len(pontos) for _, pontos in resumo_por_produto)
    if resumo_por_produto:
        messages.success(
            request,
            f'Verificação concluída — {len(resumo_por_produto)} produto(s) avançaram, '
            f'{total_pontos} ponto(s) marcado(s) no total.',
        )
    else:
        messages.info(request, 'Verificação concluída — nenhum produto teve ponto novo pra avançar.')

    if sem_produto_no_banco:
        messages.warning(
            request,
            f'{len(sem_produto_no_banco)} pasta(s) no Drive não correspondem a nenhum produto do banco.',
        )

    return redirect(reverse('agenda_videos_principal'))


# ===================================================================
# Configurações
# ===================================================================

def _validar_inteiro_positivo(valor: str | None) -> int | None:
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero >= 1 else None


# Função Objetivo: Tela de Configuração das fases (Simples/Vídeo Mensal/Vídeo
# Trimestral) — substitui o Admin como forma de editar ConfiguracaoFase.
# * [PENDENTE] → proxima_fase (a sequência entre fases) não é editável por
# aqui ainda — é fixa/rara de mudar, configurada direto no banco/admin por
# enquanto. Formulário real (HTML) também pendente — Frente 4.
def view_configuracoes_agenda_videos(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        algum_salvo = False

        for fase_valor, fase_label in Fase.choices:
            periodo_continuo = request.POST.get(f'{fase_valor}_periodo_continuo') == 'on'
            periodo = None if periodo_continuo else _validar_inteiro_positivo(request.POST.get(f'{fase_valor}_periodo'))
            distancia = _validar_inteiro_positivo(request.POST.get(f'{fase_valor}_distancia_dias_corridos'))
            distancia_entrada = _validar_inteiro_positivo(
                request.POST.get(f'{fase_valor}_distancia_dias_ao_entrar_na_fase')
            ) or 0
            config_existente = ConfiguracaoFase.objects.filter(fase=fase_valor).first()

            if distancia is None or (not periodo_continuo and periodo is None):
                if config_existente is None:
                    messages.warning(request, f'{fase_label}: valor inválido — não foi possível criar a configuração.')
                else:
                    messages.warning(request, f'{fase_label}: valor inválido — mantido o valor anterior.')
                continue

            ConfiguracaoFase.objects.update_or_create(
                fase=fase_valor,
                defaults={
                    'periodo_continuo': periodo_continuo, 'periodo': periodo,
                    'distancia_dias_corridos': distancia,
                    'distancia_dias_ao_entrar_na_fase': distancia_entrada,
                },
            )
            algum_salvo = True

        if algum_salvo:
            messages.success(request, 'Configurações de fase salvas com sucesso.')
        return redirect(reverse('agenda_videos_configuracoes'))

    fases = []
    for fase_valor, fase_label in Fase.choices:
        config = ConfiguracaoFase.objects.filter(fase=fase_valor).first()
        fases.append({
            'valor': fase_valor,
            'label': fase_label,
            'periodo_continuo': config.periodo_continuo if config else False,
            'periodo': config.periodo if config else '',
            'distancia_dias_corridos': config.distancia_dias_corridos if config else '',
            'distancia_dias_ao_entrar_na_fase': config.distancia_dias_ao_entrar_na_fase if config else '',
            'configurado': config is not None,
        })

    return render(request, 'agenda_videos/estrutura_configuracoes_agenda_videos.html', {
        'fases': fases,
    })


# ===================================================================
# Histórico
# ===================================================================

# Função Objetivo: Modal de histórico de 1 produto (Formato A).
def view_historico_produto(request: HttpRequest, produto_id: int) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)
    historico = montar_historico_produto(produto)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_historico_produto.html', {
        'historico': historico,
    })


def _validar_data(valor: str) -> date | None:
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


# Função Objetivo: Tela de relatório (Formato B).
def view_historico_agenda_videos(request: HttpRequest) -> HttpResponse:
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


# ===================================================================
# Postagem Automática — corpo intacto, só sem imports locais redundantes
# ===================================================================

def _obter_execucao_em_andamento():
    status_em_andamento = [StatusExecucao.AGUARDANDO_INICIO, StatusExecucao.RODANDO, StatusExecucao.PAUSADO]

    execucao_postagem = ExecucaoPostagemAutomatica.objects.filter(status__in=status_em_andamento).first()
    if execucao_postagem:
        execucao_postagem.tipo_execucao = 'postagem'
        return execucao_postagem

    execucao_replicacao = ExecucaoReplicacaoAutomatica.objects.filter(status__in=status_em_andamento).first()
    if execucao_replicacao:
        execucao_replicacao.tipo_execucao = 'replicacao'
        return execucao_replicacao

    return None


def view_confirmar_postagem_automatica(request):
    execucao_em_andamento = _obter_execucao_em_andamento()
    if execucao_em_andamento:
        return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_execucao_ja_em_andamento.html', {
            'execucao': execucao_em_andamento,
            'url_nome_progresso': (
                'agenda_videos_progresso_postagem_automatica' if execucao_em_andamento.tipo_execucao == 'postagem'
                else 'agenda_videos_progresso_replicacao_automatica'
            ),
        })

    produtos_elegiveis = listar_produtos_elegiveis()
    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_postagem_automatica.html', {
        'produtos_elegiveis': produtos_elegiveis,
        'quantidade_elegiveis': len(produtos_elegiveis),
    })


def view_iniciar_postagem_automatica(request):
    execucao_em_andamento = _obter_execucao_em_andamento()
    if execucao_em_andamento:
        url_nome = (
            'agenda_videos_progresso_postagem_automatica' if execucao_em_andamento.tipo_execucao == 'postagem'
            else 'agenda_videos_progresso_replicacao_automatica'
        )
        return redirect(reverse(url_nome, args=[execucao_em_andamento.id]))

    produtos_elegiveis = listar_produtos_elegiveis()

    execucao = ExecucaoPostagemAutomatica.objects.create()
    for ordem, produto in enumerate(produtos_elegiveis, start=1):
        ItemExecucaoPostagem.objects.create(execucao=execucao, produto=produto, ordem=ordem)

    return redirect(reverse('agenda_videos_progresso_postagem_automatica', args=[execucao.id]))


def _montar_contexto_progresso(execucao):
    itens = list(execucao.itens.select_related('produto').all())
    return {
        'execucao': execucao,
        'itens': itens,
        'total': len(itens),
        'concluidos': sum(1 for i in itens if i.status == StatusItemExecucao.CONCLUIDO),
        'falharam': sum(1 for i in itens if i.status == StatusItemExecucao.FALHOU),
        'cancelados': sum(1 for i in itens if i.status == StatusItemExecucao.CANCELADO),
        'travada': execucao.travada,
    }


def view_progresso_postagem_automatica(request, execucao_id):
    execucao = get_object_or_404(ExecucaoPostagemAutomatica, id=execucao_id)
    return render(
        request, 'agenda_videos/estrutura_progresso_postagem_automatica.html',
        _montar_contexto_progresso(execucao),
    )


def view_progresso_postagem_automatica_parcial(request, execucao_id):
    execucao = get_object_or_404(ExecucaoPostagemAutomatica, id=execucao_id)
    return render(
        request, 'agenda_videos/parciais/estrutura_parcial_lista_progresso_postagem.html',
        _montar_contexto_progresso(execucao),
    )


@require_POST
def view_cancelar_execucao_travada(request, execucao_id):
    execucao = get_object_or_404(ExecucaoPostagemAutomatica, id=execucao_id)
    execucao.itens.filter(
        status__in=[StatusItemExecucao.AGUARDANDO],
    ).update(status=StatusItemExecucao.CANCELADO)
    execucao.status = StatusExecucao.CANCELADO
    execucao.finalizado_em = timezone.now()
    execucao.save(update_fields=['status', 'finalizado_em'])
    return redirect(reverse('agenda_videos_progresso_postagem_automatica', args=[execucao_id]))


# ===================================================================
# Replicação Automática — corpo intacto, só sem imports locais redundantes
# ===================================================================

def view_confirmar_replicacao_automatica(request):
    execucao_em_andamento = _obter_execucao_em_andamento()
    if execucao_em_andamento:
        return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_execucao_ja_em_andamento.html', {
            'execucao': execucao_em_andamento,
            'url_nome_progresso': (
                'agenda_videos_progresso_postagem_automatica' if execucao_em_andamento.tipo_execucao == 'postagem'
                else 'agenda_videos_progresso_replicacao_automatica'
            ),
        })

    produtos_elegiveis = listar_a_fazer_hoje(filtros={'pendente_agora': ['replicar']})
    return render(request, 'agenda_videos/parciais/estrutura_parcial_modal_confirmar_replicacao_automatica.html', {
        'produtos_elegiveis': produtos_elegiveis,
        'quantidade_elegiveis': len(produtos_elegiveis),
    })


def view_iniciar_replicacao_automatica(request):
    execucao_em_andamento = _obter_execucao_em_andamento()
    if execucao_em_andamento:
        url_nome = (
            'agenda_videos_progresso_postagem_automatica' if execucao_em_andamento.tipo_execucao == 'postagem'
            else 'agenda_videos_progresso_replicacao_automatica'
        )
        return redirect(reverse(url_nome, args=[execucao_em_andamento.id]))

    produtos_elegiveis = listar_a_fazer_hoje(filtros={'pendente_agora': ['replicar']})

    execucao = ExecucaoReplicacaoAutomatica.objects.create()
    for ordem, produto in enumerate(produtos_elegiveis, start=1):
        ItemExecucaoReplicacao.objects.create(execucao=execucao, produto=produto, ordem=ordem)

    return redirect(reverse('agenda_videos_progresso_replicacao_automatica', args=[execucao.id]))


def _montar_contexto_progresso_replicacao(execucao):
    itens = list(execucao.itens.select_related('produto').all())
    return {
        'execucao': execucao,
        'itens': itens,
        'total': len(itens),
        'concluidos': sum(1 for i in itens if i.status == StatusItemExecucaoReplicacao.CONCLUIDO),
        'falharam': sum(1 for i in itens if i.status == StatusItemExecucaoReplicacao.FALHOU),
        'cancelados': sum(1 for i in itens if i.status == StatusItemExecucaoReplicacao.CANCELADO),
        'travada': execucao.travada,
    }


def view_progresso_replicacao_automatica(request, execucao_id):
    execucao = get_object_or_404(ExecucaoReplicacaoAutomatica, id=execucao_id)
    return render(
        request, 'agenda_videos/estrutura_progresso_replicacao_automatica.html',
        _montar_contexto_progresso_replicacao(execucao),
    )


def view_progresso_replicacao_automatica_parcial(request, execucao_id):
    execucao = get_object_or_404(ExecucaoReplicacaoAutomatica, id=execucao_id)
    return render(
        request, 'agenda_videos/parciais/estrutura_parcial_lista_progresso_replicacao.html',
        _montar_contexto_progresso_replicacao(execucao),
    )


@require_POST
def view_cancelar_execucao_replicacao_travada(request, execucao_id):
    execucao = get_object_or_404(ExecucaoReplicacaoAutomatica, id=execucao_id)
    execucao.itens.filter(
        status__in=[StatusItemExecucaoReplicacao.AGUARDANDO],
    ).update(status=StatusItemExecucaoReplicacao.CANCELADO)
    execucao.status = StatusExecucao.CANCELADO
    execucao.finalizado_em = timezone.now()
    execucao.save(update_fields=['status', 'finalizado_em'])
    return redirect(reverse('agenda_videos_progresso_replicacao_automatica', args=[execucao_id]))