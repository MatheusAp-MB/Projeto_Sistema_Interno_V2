# agenda_videos/views.py

# Função Objetivo: Views das 4 telas do app agenda_videos — Agenda de Vídeos
# (tela principal), Configurações (regras de cada fase), Histórico (relatório
# e modal por produto) e Postagem/Replicação Automática (execução em lote).
# Views de Postagem/Replicação Automática ainda não passaram por revisão de
# regras — só limpeza de import aqui; reescrita fica pra quando auditarmos
# agenda_videos/funcoes_auxiliares/postagem_automatica/orquestrador.py.

import io
import os
import tempfile
import threading
from datetime import date, datetime

from googleapiclient.http import MediaIoBaseDownload
import requests

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import (
    HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, JsonResponse, StreamingHttpResponse,
)
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.empresa import definir_empresa_ativa, obter_empresa_ativa
from produtos.models import Produto
from agenda_videos.funcoes_auxiliares.contexto_tela_agenda_videos import ContextoTelaAgendaVideos
from agenda_videos.funcoes_auxiliares.drive import (
    calcular_diagnostico_preparo_drive, verificar_produto_no_drive, verificar_todos_no_drive,
)
from agenda_videos.funcoes_auxiliares.drive.arquivador import ArquivadorDrive, montar_nome_arquivo
from agenda_videos.funcoes_auxiliares.drive.cliente import (
    obter_servico_drive, obter_servico_drive_escrita, obter_pasta_raiz_id_ativa, obter_credenciais_drive_escrita,
)
from agenda_videos.funcoes_auxiliares.drive.constantes import NOME_PASTA_VIDEOS, NOME_PASTA_USADOS
from agenda_videos.funcoes_auxiliares.drive.parser import EXTENSOES_VALIDAS_POR_TIPO
from agenda_videos.funcoes_auxiliares.postagem_ciclica import ja_postou_hoje
from agenda_videos.funcoes_auxiliares.sincronizar_roadmap_agenda import sincronizar_indicadores_agenda_produto
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import calcular_indicadores_ciclo
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import Tela, listar_produtos_agenda_filtrados
from agenda_videos.funcoes_auxiliares.historico_roadmap import listar_produtos_com_historico, montar_historico_produto
from agenda_videos.funcoes_auxiliares.postagem_automatica import listar_produtos_elegiveis
from agenda_videos.models import (
    StatusPostagem, Fase, ConfiguracaoFase, CicloVideo, StatusManualAgenda, ParticipacaoAgenda,
    HistoricoStatusManualAgenda, status_manual_atual_do_produto,
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
        # * [EXPLICAÇÃO] → Simples não precisa mais de clique pra existir —
        #                  o único ponto alcançável sem nenhum CicloVideo no
        #                  banco é Base. Instância NÃO salva, só pra exibir o
        #                  modal — a criação real acontece em
        #                  view_marcar_ponto_roadmap (visualizar nunca
        #                  escreve no banco).
        if chave != 'base':
            return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')
        ciclo = CicloVideo(produto=produto, fase=Fase.SIMPLES, numero_ocorrencia=1)

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

    if ciclo is None:
        # * [EXPLICAÇÃO] → 1º clique real de qualquer produto — cria o
        #                  Simples sozinho, aqui (nunca na exibição do modal).
        if chave != 'base':
            return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')
        ciclo = CicloVideo.iniciar_agenda(produto)
    elif chave not in ('base', 'roteiro', 'completo') or ciclo.etapa_atual() != chave:
        return HttpResponseBadRequest('Esse ponto não pode ser confirmado agora.')

    agora = timezone.now()
    campo = f'{chave}_concluido_em'
    setattr(ciclo, campo, agora)
    ciclo.save(update_fields=[campo])

    return _recarregar_e_renderizar_card(request, produto.id)


# Função Objetivo: Agenda formalmente o início do ciclo recorrente (Vídeo
# Mensal #1) — só permitido depois do Simples estar replicado. Substituiu
# (02/08) o antigo "criar o Simples" — Simples agora nasce sozinho, no
# primeiro clique de Base (ver view_marcar_ponto_roadmap).
def view_agendar_produto(request: HttpRequest, produto_id: int) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)
    ciclo = _buscar_ciclo_atual(produto)

    if ciclo is None or ciclo.fase != Fase.SIMPLES or ciclo.etapa_atual() != 'concluido':
        return HttpResponseBadRequest('Só é possível agendar depois do Simples replicado.')

    ciclo.agendar_apos_simples()

    # Marca o momento real da transição Simples → Mensal — é isso que
    # agendado_em representa, nunca a criação do produto nem o 1º clique
    # de Base. Idempotente: uma vez agendado, sempre agendado.
    participacao, _ = ParticipacaoAgenda.objects.get_or_create(produto=produto)
    if participacao.agendado_em is None:
        participacao.agendado_em = timezone.now()
        participacao.save(update_fields=['agendado_em'])

    return _recarregar_e_renderizar_card(request, produto.id)


# ===================================================================
# Ações do ciclo (Base/Roteiro/Completo já ficaram em view_marcar_ponto_
# roadmap acima) — Postar/Aprovar/Recusar/Nova tentativa/Seguir sem
# repor/Replicar, cada uma isolada, assinatura idêntica: (produto, ciclo,
# agora) → HttpResponseBadRequest em erro, ou None em sucesso.
# ===================================================================

def _acao_postar(request: HttpRequest, produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    if ciclo.etapa_atual() != 'postar':
        return HttpResponseBadRequest('Esse produto não está pronto pra postar agora.')
    if ja_postou_hoje(produto):
        return HttpResponseBadRequest('Este produto já teve vídeo postado hoje — só é permitida 1 postagem por dia.')
    mlb_postado = (request.POST.get('mlb_postado') or '').strip()
    if not mlb_postado:
        return HttpResponseBadRequest('Informe o MLB que foi postado.')
    ciclo.marcar_aguardando_aprovacao(mlb_postado=mlb_postado)
    return None


def _acao_marcar_aprovado_ou_recusado(ciclo: CicloVideo, agora: datetime, novo_status: str) -> HttpResponseBadRequest | None:
    if ciclo.status != StatusPostagem.AGUARDANDO_APROVACAO:
        return HttpResponseBadRequest('Estado inválido — não há postagem aguardando aprovação.')
    ciclo.status = novo_status
    ciclo.aprovado_ou_recusado_em = agora
    ciclo.save(update_fields=['status', 'aprovado_ou_recusado_em'])
    return None


def _acao_aprovar(request: HttpRequest, produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    return _acao_marcar_aprovado_ou_recusado(ciclo, agora, StatusPostagem.APROVADO)


def _acao_recusar(request: HttpRequest, produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
    return _acao_marcar_aprovado_ou_recusado(ciclo, agora, StatusPostagem.RECUSADO)


# Função Objetivo: Recusado precisa refazer o Completo antes de postar de
# novo (regra confirmada na Frente 1) — reabre pra edição; o usuário marca
# "Completo" de novo antes de poder postar.
def _acao_nova_tentativa(request: HttpRequest, produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
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
def _acao_seguir_sem_repor(request: HttpRequest, produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
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


def _acao_replicar(request: HttpRequest, produto: Produto, ciclo: CicloVideo, agora: datetime) -> HttpResponseBadRequest | None:
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
    resposta_erro = funcao_acao(request, produto, ciclo, agora)
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

            # * [CORREÇÃO] → Simples tem só 1 ocorrência (não existe "distância
            # entre ocorrências" quando não há segunda ocorrência) — o campo já
            # é null=True no banco pra ela. Só Mensal/Trimestral exigem esse valor.
            distancia_obrigatoria = fase_valor != Fase.SIMPLES
            if (distancia_obrigatoria and distancia is None) or (not periodo_continuo and periodo is None):
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


# Função Objetivo: Liga/desliga "Pausado" no status manual da agenda deste
# produto — cria um novo registro de histórico (nunca edita o antigo,
# preserva quando cada mudança aconteceu). Nunca gera Descontinuado — esse
# valor existe no model mas não tem ação manual (decisão: exclusão da
# agenda nunca é manual; se um dia for preciso tirar produtos da agenda, o
# ajuste é no FILTRO de entrada, não no status de 1 produto por vez).
def view_alternar_pausado_agenda(request: HttpRequest, produto_id: int) -> HttpResponse:
    produto = get_object_or_404(Produto, id=produto_id)

    status_atual = status_manual_atual_do_produto(produto)
    novo_status = StatusManualAgenda.ATIVO if status_atual == StatusManualAgenda.PAUSADO else StatusManualAgenda.PAUSADO
    HistoricoStatusManualAgenda.objects.create(produto=produto, status=novo_status)

    sincronizar_indicadores_agenda_produto(produto)
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

    produtos_elegiveis = listar_produtos_agenda_filtrados(tela=Tela.AGUARDANDO_POSTAR_REPLICAR, filtros={'aba': 'replicar'})
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

    produtos_elegiveis = listar_produtos_agenda_filtrados(tela=Tela.AGUARDANDO_POSTAR_REPLICAR, filtros={'aba': 'replicar'})

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

# Portal do Drive — Agenda de Vídeos
# ===================================================================
# Função Objetivo: Tela real de upload manual do Portal do Drive — lista
# TODOS os produtos reais que já participam da Agenda de Vídeos (mesmo
# recorte de listar_produtos_com_historico), com busca e paginação (mesmo
# padrão da tela de Histórico). Cada linha colapsada só mostra dado de
# banco (foto/marca/título/EAN/SKU) — nenhuma chamada ao Drive acontece na
# carga da lista. Ao abrir 1 produto (accordion — só 1 aberto por vez, ver
# script_portal_drive.js), a tela carrega sob demanda (HTMX, evento
# `toggle` do <details>) as 7 ocorrências (Simples, Mensal 01-04,
# Trimestral 01-02), mostra quais dos 3 arquivos (Base/Roteiro/Completo)
# já existem no Drive — tanto em Videos/ (ativo) quanto em Videos/usados/
# (já usado na postagem automática, vira só leitura) — e permite
# selecionar/arrastar vários arquivos de uma vez e enviar o lote inteiro
# num único envio (upload real, ArquivadorDrive.enviar_arquivo). Arquivos
# ativos também podem ser excluídos (movidos pra lixeira do Drive) via
# confirmação em 2 etapas — nunca um arquivo já usado, que é sempre só
# leitura.
#
# * [ATENÇÃO] → Decisão revertida em 31/08/2026 — voltou a usar a pasta
#               REAL de produção (ver obter_pasta_raiz_id_ativa() em
#               drive/cliente.py). Entre 20/08 e 31/08/2026, toda leitura/
#               escrita no Drive usada por esta tela acontecia dentro da
#               pasta de TESTE dedicada da empresa. Cada
#               produto usa sua PRÓPRIA marca/ean real (não mais uma
#               identidade fixa/falsa) — só que criada, se ainda não
#               existir, dentro dessa raiz de teste isolada. Antiga
#               MARCA_SANDBOX_TESTES/EAN_SANDBOX_TESTES (identidade fixa
#               "PRODUTO_RASCUNHO") removida — não faz mais sentido com a
#               raiz inteira já isolada pra teste. A tela não avisa mais
#               isso na UI (decisão do usuário, 20/08/2026) — o código já
#               é a versão final, a raiz de teste é só config reversível.

ROTULO_FASE = {'simples': 'Simples', 'video_mensal': 'Mensal', 'video_trimestral': 'Trimestral'}

# * [EXPLICAÇÃO] → Extraído pra constante de módulo (20/08/2026) — antes
#                  vivia só dentro de _montar_contexto_card; agora
#                  _contar_arquivos_presentes também precisa da mesma
#                  lista, e duplicar as 7 fases/ocorrências em 2 lugares
#                  era um risco real de um dia os dois divergirem.
FASES_E_NUMEROS = (
    [('simples', None)]
    + [('video_mensal', n) for n in range(1, 5)]
    + [('video_trimestral', 1), ('video_trimestral', 2)]
)
# * [EXPLICAÇÃO] → A ocorrência extra do Trimestral (a 2ª) nunca conta no
#                  total "X de Y arquivos" — mesmo recorte que o card
#                  aberto já usa (linhas_principais, abaixo). Precisa ser
#                  o MESMO número nos 2 lugares (linha colapsada da lista
#                  e cabeçalho do card aberto), senão a tela mostra 2
#                  contagens diferentes pro mesmo produto.
FASES_E_NUMEROS_PRINCIPAIS = [
    (fase, numero) for fase, numero in FASES_E_NUMEROS
    if not (fase == 'video_trimestral' and numero == 2)
]
TOTAL_ARQUIVOS_ESPERADOS = len(FASES_E_NUMEROS_PRINCIPAIS) * 3  # 6 linhas principais × 3 tipos = 18


def _rotulo_linha(fase, numero):
    return ROTULO_FASE[fase] if numero is None else f'{ROTULO_FASE[fase]} {numero:02d}'


# Função Objetivo: Busca detalhes (link de visualização + tamanho + duração)
# de 1 arquivo já confirmado presente — 1 única chamada combinada ao Drive,
# só feita quando o arquivo existe de verdade (nunca pra checar existência).
def _obter_detalhes_arquivo(servico, drive_file_id):
    try:
        metadados = servico.files().get(
            fileId=drive_file_id, fields='webViewLink, size, videoMediaMetadata(durationMillis)',
            supportsAllDrives=True,
        ).execute()
    except Exception:
        # * [EXPLICAÇÃO] → Falha não vira cache — devolve None (em vez de
        #                  um dict zerado) pra _obter_detalhes_com_cache
        #                  saber que isso foi um erro passageiro, não um
        #                  resultado real, e tentar de novo no próximo open.
        return None
    duracao_ms = metadados.get('videoMediaMetadata', {}).get('durationMillis')
    return {
        'link_visualizacao': metadados.get('webViewLink', ''),
        'tamanho_bytes': int(metadados.get('size', 0) or 0),
        'duracao_segundos': int(duracao_ms) / 1000 if duracao_ms else 0,
    }


# * [EXPLICAÇÃO] → Cache de detalhes (link/tamanho/duração) DENTRO do
#                  próprio item do snapshot já salvo (20/08/2026) — a 1ª
#                  vez que um arquivo é aberto, os 3 campos são buscados ao
#                  vivo e gravados de volta no item; da 2ª vez em diante
#                  (reabrir o mesmo produto), a leitura é 100% do banco,
#                  sem chamada nenhuma ao Drive. Invalida sozinho: qualquer
#                  sincronização sobrescreve arquivos_videos/arquivos_usados
#                  do zero, sem esses campos — o próximo open recalcula.
CAMPOS_CACHE_DETALHES = ('link_visualizacao', 'tamanho_bytes', 'duracao_segundos')


def _obter_detalhes_com_cache(servico, item):
    if all(campo in item for campo in CAMPOS_CACHE_DETALHES):
        return {campo: item[campo] for campo in CAMPOS_CACHE_DETALHES}, False

    detalhes = _obter_detalhes_arquivo(servico, item['id'])
    if detalhes is None:
        return {'link_visualizacao': '', 'tamanho_bytes': 0, 'duracao_segundos': 0}, False

    item.update(detalhes)
    return detalhes, True


def _formatar_tamanho_arquivo(tamanho_bytes):
    if not tamanho_bytes:
        return '0 KB'
    if tamanho_bytes >= 1024 * 1024:
        return f'{tamanho_bytes / (1024 * 1024):.1f} MB'
    return f'{max(tamanho_bytes // 1024, 1)} KB'


def _formatar_duracao(duracao_segundos):
    minutos = int(duracao_segundos) // 60
    segundos_restantes = int(duracao_segundos) % 60
    return f'{minutos}:{segundos_restantes:02d}'


def _indice_arquivos_por_nome(lista_arquivos):
    # * [EXPLICAÇÃO] → Indexa o ITEM inteiro (não só o id) — precisa do
    #                  dict completo pra _obter_detalhes_com_cache poder
    #                  ler/gravar os campos extras de cache nele.
    return {item['name']: item for item in lista_arquivos}


# Função Objetivo: Monta 1 linha (fase/ocorrência) — lê presença de arquivo
# do SNAPSHOT já salvo (nunca ao vivo). Só bate no Drive (via
# _obter_detalhes_arquivo) pros arquivos que o snapshot já confirma
# existir, nunca pra descobrir se existem.
def _montar_linha(servico, snapshot, fase, numero, marca, ean):
    indice_videos = _indice_arquivos_por_nome(snapshot.arquivos_videos) if snapshot else {}
    indice_usados = _indice_arquivos_por_nome(snapshot.arquivos_usados) if snapshot else {}

    arquivos = {}
    qtd_presente = 0
    houve_cache_novo = False
    for tipo in ('base', 'roteiro', 'completo'):
        nome_esperado = montar_nome_arquivo(fase, numero, tipo)
        item = indice_videos.get(nome_esperado)
        usado = False
        if not item:
            item = indice_usados.get(nome_esperado)
            usado = bool(item)

        presente = bool(item)
        qtd_presente += int(presente)
        if presente:
            detalhes, novo = _obter_detalhes_com_cache(servico, item)
            houve_cache_novo = houve_cache_novo or novo
        else:
            detalhes = {}

        drive_file_id = item['id'] if item else ''
        pasta_do_arquivo_id = (snapshot.pasta_usados_id if usado else snapshot.pasta_videos_id) if snapshot else ''
        link_pasta = f'https://drive.google.com/drive/folders/{pasta_do_arquivo_id}' if presente and pasta_do_arquivo_id else ''

        arquivos[tipo] = {
            'tipo': tipo, 'nome_esperado': nome_esperado, 'presente': presente,
            'usado': usado, 'drive_file_id': drive_file_id,
            'link_visualizacao': link_pasta,
            'tamanho_formatado': _formatar_tamanho_arquivo(detalhes.get('tamanho_bytes')) if presente else '',
            'duracao_formatada': (
                _formatar_duracao(detalhes.get('duracao_segundos'))
                if presente and detalhes.get('duracao_segundos') else ''
            ),
            'pasta_completa': (
                f'{marca}/{ean}/{NOME_PASTA_VIDEOS}/{NOME_PASTA_USADOS}/'
                if usado else
                f'{marca}/{ean}/{NOME_PASTA_VIDEOS}/'
            ),
        }
    return {
        'fase': fase, 'numero': numero, 'chave': f'{fase}-{numero or 0}',
        'rotulo': _rotulo_linha(fase, numero), 'arquivos': arquivos,
        'qtd_presente': qtd_presente, 'completa': qtd_presente == 3,
    }, houve_cache_novo


# Função Objetivo: Conta quantos dos arquivos esperados (linhas principais,
# mesmo recorte de _montar_contexto_card) já existem no Drive — 100% a
# partir do snapshot já salvo, nenhuma chamada de rede. Usado tanto pro
# filtro de Progresso quanto pro contador "X de Y" da linha colapsada.
def _contar_arquivos_presentes(produto):
    snapshot = getattr(produto, 'snapshot_drive', None)
    if snapshot is None:
        return 0
    nomes_presentes = {item['name'] for item in snapshot.arquivos_videos} | {item['name'] for item in snapshot.arquivos_usados}
    return sum(
        1
        for fase, numero in FASES_E_NUMEROS_PRINCIPAIS
        for tipo in ('base', 'roteiro', 'completo')
        if montar_nome_arquivo(fase, numero, tipo) in nomes_presentes
    )


def _montar_contexto_card(produto, resultado_envio=None, erro_envio=None, mensagem_exclusao=None):
    servico = obter_servico_drive()
    snapshot = getattr(produto, 'snapshot_drive', None)
    ciclo_atual = _buscar_ciclo_atual(produto)
    # * [EXPLICAÇÃO] → Produto sem NENHUM CicloVideo ainda (nunca postou
    #                  nada) não tem "etapa atual" gravada no banco — mas o
    #                  ponto de partida óbvio de qualquer produto novo é
    #                  sempre Simples, então a ausência de ciclo é tratada
    #                  como se já estivesse lá, só pra fins de destaque.
    fase_atual, numero_atual = (ciclo_atual.fase, ciclo_atual.numero_ocorrencia) if ciclo_atual else ('simples', 1)

    linhas = []
    houve_cache_novo = False
    for fase, numero in FASES_E_NUMEROS:
        linha, novo = _montar_linha(servico, snapshot, fase, numero, produto.marca, produto.ean)
        linha['extra_trimestral'] = (fase == 'video_trimestral' and numero == 2)
        linha['atual'] = (fase_atual == fase and numero_atual == (numero or 1))
        linhas.append(linha)
        houve_cache_novo = houve_cache_novo or novo

    if houve_cache_novo and snapshot is not None:
        # * [EXPLICAÇÃO] → 1 único save no final, não 1 por arquivo — os
        #                  itens dentro de arquivos_videos/arquivos_usados
        #                  já foram mutados in-place por
        #                  _obter_detalhes_com_cache, isso só persiste tudo
        #                  de uma vez.
        snapshot.save(update_fields=['arquivos_videos', 'arquivos_usados'])

    linhas_principais = [l for l in linhas if not l['extra_trimestral']]
    total = sum(1 for l in linhas_principais for a in l['arquivos'].values())
    presentes = sum(1 for l in linhas_principais for a in l['arquivos'].values() if a['presente'])

    return {
        'produto': produto,
        'linhas': linhas,
        'total_arquivos': total,
        'presentes_arquivos': presentes,
        'resultado_envio': resultado_envio or [],
        'erro_envio': erro_envio,
        'mensagem_exclusao': mensagem_exclusao,
        'nunca_sincronizado': snapshot is None,
        'pasta_nao_encontrada': snapshot is not None and not snapshot.pasta_encontrada,
        'motivo_nao_encontrado': snapshot.motivo_nao_encontrado if snapshot else None,
        'snapshot_atualizado_em': snapshot.atualizado_em if snapshot else None,
    }


# Função Objetivo: Tela de lista — TODOS os produtos reais que já
# participam da Agenda de Vídeos (tela=Tela.GERAL), com busca, paginação e
# filtros (Marca, Progresso de envio, Fase atual, Urgente, Nunca
# sincronizado). Cada linha colapsada mostra dado de banco mais o
# progresso de arquivos (calculado do snapshot já salvo, sem chamada ao
# Drive); o detalhe (fases/arquivos) de 1 produto só é buscado/exibido
# quando a linha dele é aberta (ver view_portal_drive_detalhe).
#
# * [ATENÇÃO] → O filtro de Progresso não dá pra fazer só com SQL (os
#               nomes de arquivo presentes ficam dentro de um JSON no
#               snapshot) — por isso, só QUANDO esse filtro é usado, a
#               lista inteira (já filtrada por busca/marca/fase/urgente/
#               nunca-sincronizado) é avaliada em Python antes de
#               paginar. Tranquilo pro tamanho real do catálogo da
#               Agenda de Vídeos; não escalaria bem se isso um dia virasse
#               dezenas de milhares de produtos.
def view_portal_drive(request):
    from django.core.cache import cache

    # * [EXPLICAÇÃO] → A sincronização real roda numa thread em background
    #                  (ver view_portal_drive_sincronizar/
    #                  _rodar_sincronizacao_portal_drive_em_thread abaixo) —
    #                  sem request/response nenhum durante a execução, então
    #                  não dá pra usar messages.success() na hora. O resultado
    #                  fica guardado no cache e só é "descarregado" como
    #                  mensagem de verdade no próximo GET desta tela (aqui).
    estado_sincronizacao = cache.get(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    if estado_sincronizacao and estado_sincronizacao.get('status') in ('concluido', 'erro'):
        if estado_sincronizacao['status'] == 'erro':
            messages.error(request, 'Não foi possível conectar ao Google Drive agora — tente novamente em instantes.')
        else:
            getattr(messages, estado_sincronizacao['tipo_mensagem'])(request, estado_sincronizacao['mensagem'])
            if estado_sincronizacao.get('aviso_sem_produto'):
                messages.warning(request, estado_sincronizacao['aviso_sem_produto'])
        cache.delete(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)

    busca = request.GET.get('busca', '').strip()
    marcas_selecionadas = request.GET.getlist('marca')
    fases_selecionadas = request.GET.getlist('fase')
    progresso = request.GET.get('progresso', 'todos')
    somente_urgentes = request.GET.get('urgente') == '1'
    sincronizado = request.GET.get('sincronizado', 'todos')

    produtos = listar_produtos_agenda_filtrados(tela=Tela.GERAL, busca=busca or None)
    produtos = produtos.select_related('snapshot_drive', 'indicadores_agenda', 'participacao_agenda')

    if marcas_selecionadas:
        produtos = produtos.filter(marca__in=marcas_selecionadas)
    if fases_selecionadas:
        produtos = produtos.filter(indicadores_agenda__fase_atual__in=fases_selecionadas)
    if somente_urgentes:
        produtos = produtos.filter(participacao_agenda__urgente=True)
    if sincronizado == 'sim':
        produtos = produtos.filter(snapshot_drive__isnull=False)
    elif sincronizado == 'nao':
        produtos = produtos.filter(snapshot_drive__isnull=True)

    if progresso in ('pendente', 'completo'):
        produtos_avaliados = list(produtos)
        for produto in produtos_avaliados:
            produto.arquivos_presentes = _contar_arquivos_presentes(produto)
        if progresso == 'pendente':
            produtos_para_paginar = [p for p in produtos_avaliados if p.arquivos_presentes < TOTAL_ARQUIVOS_ESPERADOS]
        else:
            produtos_para_paginar = [p for p in produtos_avaliados if p.arquivos_presentes >= TOTAL_ARQUIVOS_ESPERADOS]
    else:
        produtos_para_paginar = produtos

    try:
        por_pagina = int(request.GET.get('por_pagina', '25'))
    except ValueError:
        por_pagina = 25

    paginator = Paginator(produtos_para_paginar, por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    for produto in pagina:
        if not hasattr(produto, 'arquivos_presentes'):
            produto.arquivos_presentes = _contar_arquivos_presentes(produto)
        produto.arquivos_total = TOTAL_ARQUIVOS_ESPERADOS
        produto.arquivos_percentual = round(produto.arquivos_presentes / TOTAL_ARQUIVOS_ESPERADOS * 100)

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    marcas_disponiveis = (
        Produto.objects.exclude(marca__isnull=True).exclude(marca='')
        .values_list('marca', flat=True).distinct().order_by('marca')
    )

    return render(request, 'agenda_videos/estrutura_portal_drive.html', {
        'pagina': pagina,
        'busca': busca,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'marcas_disponiveis': marcas_disponiveis,
        'marcas_selecionadas': marcas_selecionadas,
        'opcoes_fase': ROTULO_FASE.items(),
        'fases_selecionadas': fases_selecionadas,
        'progresso': progresso,
        'somente_urgentes': somente_urgentes,
        'sincronizado': sincronizado,
    })

# Função Objetivo: Carrega, sob demanda, o painel completo (fases/arquivos)
# de 1 produto — disparado pelo HTMX só quando a linha dele é aberta na
# lista (nunca na carga inicial da página).
def view_portal_drive_detalhe(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    return render(
        request, 'agenda_videos/parciais/estrutura_parcial_portal_drive_card.html',
        _montar_contexto_card(produto),
    )


@require_POST
def view_portal_drive_enviar(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    resultados = []
    pasta_raiz_id = obter_pasta_raiz_id_ativa()
    arquivador = None

    for campo, arquivo_enviado in request.FILES.items():
        if not campo.startswith('arquivo__'):
            continue
        _, fase, numero_str, tipo = campo.split('__')
        numero = None if numero_str == '0' else int(numero_str)
        rotulo = _rotulo_linha(fase, numero) if fase in ROTULO_FASE else fase

        if fase not in ROTULO_FASE or tipo not in EXTENSOES_VALIDAS_POR_TIPO:
            resultados.append({'rotulo': rotulo, 'tipo': tipo, 'status': 'erro', 'mensagem': 'campo de envio inválido.'})
            continue

        extensao_esperada = EXTENSOES_VALIDAS_POR_TIPO[tipo]
        extensao_recebida = arquivo_enviado.name.rsplit('.', 1)[-1].lower() if '.' in arquivo_enviado.name else ''
        if extensao_recebida != extensao_esperada:
            resultados.append({
                'rotulo': rotulo, 'tipo': tipo, 'status': 'erro',
                'mensagem': f'esperado .{extensao_esperada}, você enviou .{extensao_recebida or "?"}.',
            })
            continue

        caminho_temporario = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{extensao_recebida}') as arquivo_temp:
                for pedaco in arquivo_enviado.chunks():
                    arquivo_temp.write(pedaco)
                caminho_temporario = arquivo_temp.name

            if arquivador is None:
                arquivador = ArquivadorDrive()

            try:
                arquivador.enviar_arquivo(
                    pasta_raiz_id, produto.marca, produto.ean, fase, numero, tipo, caminho_temporario,
                )
                resultados.append({'rotulo': rotulo, 'tipo': tipo, 'status': 'enviado', 'mensagem': 'enviado com sucesso.'})
            except FileExistsError:
                resultados.append({'rotulo': rotulo, 'tipo': tipo, 'status': 'conflito', 'mensagem': 'já existe no Drive — não foi enviado.'})
        finally:
            if caminho_temporario and os.path.exists(caminho_temporario):
                os.remove(caminho_temporario)

    if any(resultado['status'] == 'enviado' for resultado in resultados):
        try:
            # * [EXPLICAÇÃO] → O upload já aconteceu de verdade — se esta
            #                  reverificação falhar (rede instável), não
            #                  vira erro 500: o snapshot só fica um pouco
            #                  desatualizado até o próximo "Sincronizar com
            #                  o Drive", nunca perde o arquivo já enviado.
            verificar_produto_no_drive(produto.id)
        except Exception:
            pass

    erro_envio = None if resultados else 'Nenhum arquivo selecionado para envio.'
    contexto = _montar_contexto_card(produto, resultado_envio=resultados, erro_envio=erro_envio)
    return render(request, 'agenda_videos/parciais/estrutura_parcial_portal_drive_card.html', contexto)


# Função Objetivo: Abre o modal de confirmação de exclusão (1º clique) — só
# monta o texto de exibição (rótulo/tipo/nome vêm da própria tela via
# querystring, sem precisar de outra ida ao Drive só pra isso). Nada é
# excluído aqui — a exclusão de verdade só acontece em
# view_portal_drive_excluir, no 2º clique, dentro do modal.
def view_portal_drive_confirmar_exclusao(request, produto_id, file_id):
    contexto = {
        'produto_id': produto_id,
        'file_id': file_id,
        'rotulo': request.GET.get('rotulo', ''),
        'tipo': request.GET.get('tipo', ''),
        'nome': request.GET.get('nome', ''),
    }
    return render(request, 'agenda_videos/parciais/estrutura_parcial_portal_drive_modal_excluir.html', contexto)


# Função Objetivo: Exclui de verdade (2º clique, dentro do modal) — move
# pra lixeira do Drive (ArquivadorDrive.excluir_arquivo), nunca apaga em
# definitivo. Um arquivo 'usado' nunca mostra o botão que chama essa view
# (ver _montar_linha/template) — não precisa checar isso de novo aqui.
@require_POST
def view_portal_drive_excluir(request, produto_id, file_id):
    produto = get_object_or_404(Produto, id=produto_id)
    arquivador = ArquivadorDrive()
    arquivador.excluir_arquivo(file_id)
    try:
        verificar_produto_no_drive(produto.id)
    except Exception:
        pass

    contexto = _montar_contexto_card(produto, mensagem_exclusao='Arquivo movido para a lixeira do Drive.')
    return render(request, 'agenda_videos/parciais/estrutura_parcial_portal_drive_card.html', contexto)


# Função Objetivo: Chave única de cache pro status da sincronização do
# Portal do Drive — mesmo mecanismo já usado em
# precificacao/views/exportacao_precos.py (django.core.cache), sem
# introduzir nenhuma peça nova de infraestrutura. Só 1 sincronização por
# vez faz sentido pra este botão (não é por usuário), por isso é 1 chave
# fixa, não uma por token/sessão.
CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE = 'portal_drive_sincronizacao_status'


# Função Objetivo: Roda a sincronização de verdade numa thread separada,
# publicando o progresso em cache — quem lê esse progresso é sempre a view
# de status (view_portal_drive_sincronizar_status), consultada por polling
# do navegador, nunca a request original (que já respondeu antes desta
# função rodar). try/except cobre a função inteira de propósito: sem isso,
# uma falha de rede no meio da varredura mataria a thread em silêncio, sem
# nenhum jeito do usuário saber que a sincronização quebrou.
def _rodar_sincronizacao_portal_drive_em_thread(empresa):
    from django.core.cache import cache

    # * [EXPLICAÇÃO] → obter_pasta_raiz_id_ativa() (e qualquer outra função
    #                  do domínio Drive) depende da empresa ativa, guardada
    #                  num threading.local() (core/empresa.py) que o
    #                  EmpresaMiddleware só popula na thread que atende a
    #                  requisição HTTP original. Esta é uma thread NOVA,
    #                  sem relação com aquela — sem esta linha, toda chamada
    #                  aqui dentro quebra com "nenhuma empresa ativa
    #                  encontrada" (bug real, achado em 21/08/2026).
    definir_empresa_ativa(empresa)

    def callback_progresso(etapa, processados, total):
        cache.set(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, {
            'status': 'rodando', 'etapa': etapa, 'processados': processados, 'total': total,
        }, timeout=600)

    try:
        resumo_por_produto, sem_produto_no_banco = verificar_todos_no_drive(callback_progresso)
    except Exception:
        # * [EXPLICAÇÃO] → Mantido de propósito (não é só diagnóstico
        #                  pontual): uma thread em background que falha em
        #                  silêncio é praticamente impossível de investigar
        #                  depois — sem isso, qualquer erro futuro aqui
        #                  (mesmo um real de conexão com o Drive) não deixa
        #                  nenhum rastro no terminal, só a mensagem genérica
        #                  pro usuário.
        import traceback
        traceback.print_exc()
        cache.set(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, {'status': 'erro'}, timeout=600)
        return

    if resumo_por_produto:
        total_pontos = sum(len(pontos) for _, pontos in resumo_por_produto)
        mensagem = (
            f'Sincronização concluída — {len(resumo_por_produto)} produto(s) avançaram, '
            f'{total_pontos} ponto(s) marcado(s) no total.'
        )
        tipo_mensagem = 'success'
    else:
        mensagem = 'Sincronização concluída — nenhum produto teve ponto novo pra avançar.'
        tipo_mensagem = 'info'

    aviso_sem_produto = None
    if sem_produto_no_banco:
        aviso_sem_produto = f'{len(sem_produto_no_banco)} pasta(s) no Drive não correspondem a nenhum produto do banco.'

    cache.set(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, {
        'status': 'concluido', 'mensagem': mensagem, 'tipo_mensagem': tipo_mensagem,
        'aviso_sem_produto': aviso_sem_produto,
    }, timeout=600)


# Função Objetivo: Botão único "Sincronizar com o Drive" do Portal do
# Drive — chama a MESMA função já usada pelo "Verificar Todos no Drive" da
# Agenda de Vídeos principal (verificar_todos_no_drive, que por baixo roda
# a varredura completa e eficiente do Drive inteiro numa passada só) — 1
# chamada resolve os 2 lados (snapshot pro Portal, avanço de roadmap pra
# Agenda), sem duplicar leitura do Drive. Nunca disparado automaticamente
# em nenhum outro momento desta tela — só aqui, sob clique explícito.
#
# Reescrita (21/08/2026) pra rodar em thread + polling em vez de síncrono:
# antes a view ficava parada até a sincronização inteira terminar (vários
# segundos, sem nenhum feedback visual — a tela "congelava"). Agora só
# dispara a thread e responde na hora; o progresso real é consultado por
# view_portal_drive_sincronizar_status, e o resultado final é mostrado no
# próximo GET de view_portal_drive (ver comentário lá).
@require_POST
def view_portal_drive_sincronizar(request):
    from django.core.cache import cache

    estado_atual = cache.get(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    if estado_atual and estado_atual.get('status') == 'rodando':
        return JsonResponse(estado_atual)

    estado_inicial = {'status': 'rodando', 'etapa': 'iniciando', 'processados': 0, 'total': None}
    cache.set(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE, estado_inicial, timeout=600)

    # * [EXPLICAÇÃO] → Captura a empresa ativa AQUI, na thread da requisição
    #                  (onde o EmpresaMiddleware já resolveu ela de verdade),
    #                  e repassa pra dentro da thread nova — ver comentário
    #                  em _rodar_sincronizacao_portal_drive_em_thread.
    threading.Thread(
        target=_rodar_sincronizacao_portal_drive_em_thread,
        args=(obter_empresa_ativa(),),
        daemon=True,
    ).start()

    return JsonResponse(estado_inicial)


# Função Objetivo: Endpoint de polling — o navegador consulta a cada 1s
# enquanto a sincronização está rodando (ver script_portal_drive.js). GET
# simples, sem side-effect nenhum, só lê o cache.
@require_GET
def view_portal_drive_sincronizar_status(request):
    from django.core.cache import cache

    estado = cache.get(CHAVE_CACHE_SINCRONIZACAO_PORTAL_DRIVE)
    return JsonResponse(estado or {'status': 'ocioso'})


def view_portal_drive_video(request, file_id):
    credenciais = obter_credenciais_drive_escrita()
    cabecalhos = {'Authorization': f'Bearer {credenciais.token}'}
    if request.META.get('HTTP_RANGE'):
        cabecalhos['Range'] = request.META['HTTP_RANGE']

    resposta_drive = requests.get(
        f'https://www.googleapis.com/drive/v3/files/{file_id}',
        params={'alt': 'media', 'supportsAllDrives': 'true'},
        headers=cabecalhos,
        stream=True,
    )
    if resposta_drive.status_code not in (200, 206):
        return HttpResponseNotFound('Arquivo não encontrado ou sem permissão no Drive.')

    resposta = StreamingHttpResponse(
        resposta_drive.iter_content(chunk_size=256 * 1024),
        status=resposta_drive.status_code,
        content_type=resposta_drive.headers.get('Content-Type', 'video/mp4'),
    )
    resposta['Accept-Ranges'] = 'bytes'
    for cabecalho in ('Content-Length', 'Content-Range'):
        if cabecalho in resposta_drive.headers:
            resposta[cabecalho] = resposta_drive.headers[cabecalho]
    return resposta


def view_portal_drive_thumbnail(request, file_id):
    servico = obter_servico_drive()
    try:
        metadados = servico.files().get(fileId=file_id, fields='thumbnailLink', supportsAllDrives=True).execute()
    except Exception:
        return HttpResponseNotFound('Arquivo não encontrado no Drive.')

    thumbnail_link = metadados.get('thumbnailLink')
    if not thumbnail_link:
        return HttpResponseNotFound('Este arquivo ainda não tem miniatura no Drive.')

    resposta_imagem = requests.get(thumbnail_link, stream=True)
    if resposta_imagem.status_code != 200:
        return HttpResponseNotFound('Não foi possível carregar a miniatura.')

    return HttpResponse(resposta_imagem.content, content_type=resposta_imagem.headers.get('Content-Type', 'image/jpeg'))