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
from datetime import date, datetime

from googleapiclient.http import MediaIoBaseDownload
import requests

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, StreamingHttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

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
from agenda_videos.funcoes_auxiliares.drive.utilitarios_pasta import buscar_arquivo, buscar_subpasta
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
# * [ATENÇÃO] → A leitura/escrita no Drive de cada produto AINDA aponta
#               100% pra pasta de teste fixa (MARCA_SANDBOX_TESTES/
#               EAN_SANDBOX_TESTES) — decisão do usuário (20/08/2026): a
#               lista/busca/paginação já é real (produtos de verdade do
#               banco), mas o Drive só passa a ler/escrever por produto de
#               verdade depois que essa tela nova for validada sem risco
#               de mexer em pasta real de produção. `modo_teste_sandbox`
#               no contexto do card avisa isso na própria tela — nunca
#               esconder do usuário que o conteúdo mostrado é da pasta de
#               teste, mesmo quando o cabeçalho mostra a identidade de um
#               produto real (ver Checkpoint do Portal do Drive no vault).

MARCA_SANDBOX_TESTES = 'PRODUTO_RASCUNHO'
EAN_SANDBOX_TESTES = '0000000000099'

ROTULO_FASE = {'simples': 'Simples', 'video_mensal': 'Mensal', 'video_trimestral': 'Trimestral'}


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
        duracao_ms = metadados.get('videoMediaMetadata', {}).get('durationMillis')
        return {
            'link_visualizacao': metadados.get('webViewLink', ''),
            'tamanho_bytes': int(metadados.get('size', 0) or 0),
            'duracao_segundos': int(duracao_ms) / 1000 if duracao_ms else 0,
        }
    except Exception:
        return {'link_visualizacao': '', 'tamanho_bytes': 0, 'duracao_segundos': 0}


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


# Função Objetivo: Monta 1 linha (fase/ocorrência) — procura cada um dos 3
# arquivos primeiro em Videos/ (ativo) e, se não achar lá, em Videos/
# usados/ (já usado na postagem automática — vira só leitura, nunca pode
# ser excluído pela tela).
def _montar_linha(servico, pasta_videos_id, pasta_usados_id, fase, numero):
    arquivos = {}
    qtd_presente = 0
    for tipo in ('base', 'roteiro', 'completo'):
        nome_esperado = montar_nome_arquivo(fase, numero, tipo)
        drive_file_id = buscar_arquivo(servico, pasta_videos_id, nome_esperado) if pasta_videos_id else None
        usado = False
        if not drive_file_id and pasta_usados_id:
            drive_file_id = buscar_arquivo(servico, pasta_usados_id, nome_esperado)
            usado = bool(drive_file_id)

        presente = bool(drive_file_id)
        qtd_presente += int(presente)
        detalhes = _obter_detalhes_arquivo(servico, drive_file_id) if presente else {}

        arquivos[tipo] = {
            'tipo': tipo, 'nome_esperado': nome_esperado, 'presente': presente,
            'usado': usado, 'drive_file_id': drive_file_id or '',
            'link_visualizacao': detalhes.get('link_visualizacao', ''),
            'tamanho_formatado': _formatar_tamanho_arquivo(detalhes.get('tamanho_bytes')) if presente else '',
            'duracao_formatada': (
                _formatar_duracao(detalhes.get('duracao_segundos'))
                if presente and detalhes.get('duracao_segundos') else ''
            ),
            'pasta_completa': (
                f'{MARCA_SANDBOX_TESTES}/{EAN_SANDBOX_TESTES}/{NOME_PASTA_VIDEOS}/{NOME_PASTA_USADOS}/'
                if usado else
                f'{MARCA_SANDBOX_TESTES}/{EAN_SANDBOX_TESTES}/{NOME_PASTA_VIDEOS}/'
            ),
        }
    return {
        'fase': fase, 'numero': numero, 'chave': f'{fase}-{numero or 0}',
        'rotulo': _rotulo_linha(fase, numero), 'arquivos': arquivos,
        'qtd_presente': qtd_presente, 'completa': qtd_presente == 3,
    }


# Função Objetivo: Monta o contexto completo do card de 1 produto — usado na
# 1ª carga do painel lazy, depois de um envio em lote e depois de uma
# exclusão, sempre recarregando do Drive de verdade (nunca um estado
# "otimista" assumido no servidor).
#
# * [ATENÇÃO] → A leitura/escrita no Drive AINDA aponta 100% pra pasta de
#               teste (MARCA_SANDBOX_TESTES/EAN_SANDBOX_TESTES), não pra
#               pasta real do `produto` recebido — decisão do usuário
#               (20/08/2026): a tela já lista/busca/pagina TODOS os
#               produtos reais do banco, mas o Drive de cada um só passa a
#               ler/escrever de verdade depois que a tela nova for validada
#               sem risco de mexer em pasta real de produção.
#               `modo_teste_sandbox` no contexto avisa isso na tela (nunca
#               esconder do usuário que o conteúdo mostrado é da pasta de
#               teste).
def _montar_contexto_card(produto, resultado_envio=None, erro_envio=None, mensagem_exclusao=None):
    servico = obter_servico_drive()
    pasta_raiz_id = obter_pasta_raiz_id_ativa()
    pasta_marca_id = buscar_subpasta(servico, pasta_raiz_id, MARCA_SANDBOX_TESTES)
    pasta_ean_id = buscar_subpasta(servico, pasta_marca_id, EAN_SANDBOX_TESTES) if pasta_marca_id else None
    pasta_videos_id = buscar_subpasta(servico, pasta_ean_id, NOME_PASTA_VIDEOS) if pasta_ean_id else None
    pasta_usados_id = buscar_subpasta(servico, pasta_videos_id, NOME_PASTA_USADOS) if pasta_videos_id else None

    fases_e_numeros = (
        [('simples', None)]
        + [('video_mensal', n) for n in range(1, 5)]
        + [('video_trimestral', 1), ('video_trimestral', 2)]
    )
    linhas = []
    for fase, numero in fases_e_numeros:
        linha = _montar_linha(servico, pasta_videos_id, pasta_usados_id, fase, numero)
        linha['extra_trimestral'] = (fase == 'video_trimestral' and numero == 2)
        linhas.append(linha)

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
        'modo_teste_sandbox': True,
    }


# Função Objetivo: Tela de lista — TODOS os produtos reais que já
# participam da Agenda de Vídeos (mesmo recorte de
# listar_produtos_com_historico, sem os filtros extras daquela tela), com
# busca e paginação (mesmo padrão da tela de Histórico). Cada linha
# colapsada só mostra dado de banco (foto/marca/título/EAN/SKU) — nenhuma
# chamada ao Drive acontece aqui; o detalhe (fases/arquivos) de 1 produto
# só é buscado no Drive quando a linha dele é aberta (ver
# view_portal_drive_detalhe), pra não fazer dezenas de chamadas ao Drive
# por produto listado de uma vez só.
def view_portal_drive(request):
    busca = request.GET.get('busca', '').strip()
    produtos = listar_produtos_agenda_filtrados(tela=Tela.GERAL, busca=busca or None)

    try:
        por_pagina = int(request.GET.get('por_pagina', '25'))
    except ValueError:
        por_pagina = 25

    paginator = Paginator(produtos, por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'agenda_videos/estrutura_portal_drive.html', {
        'pagina': pagina,
        'busca': busca,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
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
                    pasta_raiz_id, MARCA_SANDBOX_TESTES, EAN_SANDBOX_TESTES, fase, numero, tipo, caminho_temporario,
                )
                resultados.append({'rotulo': rotulo, 'tipo': tipo, 'status': 'enviado', 'mensagem': 'enviado com sucesso.'})
            except FileExistsError:
                resultados.append({'rotulo': rotulo, 'tipo': tipo, 'status': 'conflito', 'mensagem': 'já existe no Drive — não foi enviado.'})
        finally:
            if caminho_temporario and os.path.exists(caminho_temporario):
                os.remove(caminho_temporario)

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

    contexto = _montar_contexto_card(produto, mensagem_exclusao='Arquivo movido para a lixeira do Drive.')
    return render(request, 'agenda_videos/parciais/estrutura_parcial_portal_drive_card.html', contexto)


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