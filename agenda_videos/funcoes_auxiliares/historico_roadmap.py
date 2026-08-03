# agenda_videos/funcoes_auxiliares/historico_roadmap.py

# Função Objetivo: Monta os dados de histórico de 1 produto — usado tanto pelo
# modal individual (Formato A) quanto pela tela de relatório geral agrupada
# por produto (Formato B). 1 função só constrói o histórico, os 2 formatos
# reaproveitam ela — nunca duplicada.
# Reestruturação completa (30/07) — antes precisava juntar 3 tabelas
# (progresso/preparação por fase/postagem) pra montar a linha do tempo; agora
# cada CicloVideo já carrega, numa linha só, todos os timestamps do ciclo
# inteiro dele. O conceito de "gap" (marco concluído sem data) deixa de
# existir — não tem mais "fase pulada automaticamente" no agendamento, então
# toda etapa concluída sempre tem timestamp real, por construção.

from dataclasses import dataclass
from datetime import datetime

from django.db import models
from django.db.models import Q, QuerySet

from produtos.models import Produto
from agenda_videos.models import CicloVideo, StatusManualAgenda, StatusPostagem
from agenda_videos.funcoes_auxiliares.roadmap_produto import montar_rotulo_rodada
from agenda_videos.funcoes_auxiliares.badges_agenda import (
    Badge, BADGES_STATUS_MANUAL, BADGES_STATUS_POSTAGEM, BADGES_ETAPA, buscar_badge_de,
)


# * [EXPLICAÇÃO] → Categoria de evento na linha do tempo (cor/ícone no
#                  template) — valor fixo repetido, nunca string solta.
class TipoEventoHistorico(models.TextChoices):
    MARCO = 'marco', 'Marco'
    AGUARDANDO_APROVACAO = 'aguardando_aprovacao', 'Aguardando Aprovação'
    RECUSADO = 'recusado', 'Recusado'
    APROVADO = 'aprovado', 'Aprovado'
    REPLICADO = 'replicado', 'Replicado'


# Objeto de domínio/processo — 1 linha da linha do tempo.
@dataclass(frozen=True)
class EventoHistorico:
    timestamp: datetime
    label: str
    tipo: TipoEventoHistorico
    icone: str
    mlbs_replicados: list[str] | None = None
    mlbs_nao_encontrados: list[str] | None = None


# Objeto de domínio/processo — retorno único de montar_linha_do_tempo_produto.
@dataclass(frozen=True)
class LinhaDoTempoProduto:
    eventos: list[EventoHistorico]
    aviso_gap: str | None = None


# Objeto de domínio/processo — 1 linha do resumo por etapa (pills do modal).
@dataclass(frozen=True)
class ResumoEtapa:
    valor: str
    label: str
    classe: str
    quantidade: int


# Objeto de domínio/processo — retorno único de montar_historico_produto.
@dataclass(frozen=True)
class HistoricoProduto:
    produto: Produto
    ciclos: list[CicloVideo]
    total: int
    resumo: list[ResumoEtapa]
    eventos: list[EventoHistorico]
    status_manual_atual: Badge
    aviso_gap: str | None = None


# Função Objetivo: Monta a linha do tempo COMPLETA e ÚNICA de 1 produto —
# desde "Entrou na Agenda" até o evento mais recente, tudo misturado em
# ordem cronológica. Cada CicloVideo contribui com até 6 eventos (Base/
# Roteiro/Completo concluídos, Postado, Aprovado-ou-Recusado, Replicado).
def montar_linha_do_tempo_produto(produto: Produto) -> LinhaDoTempoProduto:
    eventos: list[EventoHistorico] = []

    participacao = getattr(produto, 'participacao_agenda', None)
    if participacao and participacao.agendado_em:
        eventos.append(EventoHistorico(
            timestamp=participacao.agendado_em, label='Agendado — Vídeo Mensal Iniciado',
            tipo=TipoEventoHistorico.MARCO, icone='fa-calendar-check',
        ))

    # Ordem determinística mesmo com timestamps empatados — Python's
    # sort() é estável (documentado na linguagem), então visitar os
    # ciclos sempre na mesma ordem garante que eventos empatados no
    # timestamp saiam sempre na mesma posição relativa, nunca embaralhado.
    for ciclo in produto.ciclos_video.order_by('criado_em', 'id'):
        rotulo_base = montar_rotulo_rodada(ciclo.fase, ciclo.numero_ocorrencia)

        if ciclo.base_concluido_em:
            eventos.append(EventoHistorico(
                timestamp=ciclo.base_concluido_em, label=f'Base concluída ({rotulo_base})',
                tipo=TipoEventoHistorico.MARCO, icone='fa-video',
            ))
        if ciclo.roteiro_concluido_em:
            eventos.append(EventoHistorico(
                timestamp=ciclo.roteiro_concluido_em, label=f'Roteiro concluído ({rotulo_base})',
                tipo=TipoEventoHistorico.MARCO, icone='fa-pen',
            ))
        if ciclo.completo_concluido_em:
            eventos.append(EventoHistorico(
                timestamp=ciclo.completo_concluido_em, label=f'Completo concluído ({rotulo_base})',
                tipo=TipoEventoHistorico.MARCO, icone='fa-film',
            ))
        if ciclo.aguardando_aprovacao_em:
            eventos.append(EventoHistorico(
                timestamp=ciclo.aguardando_aprovacao_em, label=f'{rotulo_base} — Postado',
                tipo=TipoEventoHistorico.AGUARDANDO_APROVACAO, icone='fa-upload',
            ))
        if ciclo.aprovado_ou_recusado_em:
            if ciclo.status == StatusPostagem.RECUSADO:
                tipo, acao = TipoEventoHistorico.RECUSADO, 'Recusado'
            else:
                tipo, acao = TipoEventoHistorico.APROVADO, 'Aprovado'
            eventos.append(EventoHistorico(
                timestamp=ciclo.aprovado_ou_recusado_em, label=f'{rotulo_base} — {acao}',
                tipo=tipo, icone='fa-gavel',
            ))
        if ciclo.replicado_em:
            eventos.append(EventoHistorico(
                timestamp=ciclo.replicado_em, label=f'{rotulo_base} — Replicado',
                tipo=TipoEventoHistorico.REPLICADO, icone='fa-copy',
                mlbs_replicados=ciclo.mlbs_replicados, mlbs_nao_encontrados=ciclo.mlbs_nao_encontrados,
            ))

    eventos.sort(key=lambda evento: evento.timestamp)
    return LinhaDoTempoProduto(eventos=eventos)


# Função Objetivo: Monta o histórico completo (todas as fases/ocorrências) de
# 1 produto — SEMPRE completo, nunca filtrado, mesmo quando chamado a partir
# da tela com filtro ativo (o filtro estreita QUAIS produtos aparecem no
# relatório, nunca esconde ciclo de dentro de um produto já mostrado).
def montar_historico_produto(produto: Produto) -> HistoricoProduto:
    # Desempate por '-id' — 2 CicloVideo criados muito próximos podem
    # empatar no timestamp de criado_em (comum no Windows); id sempre
    # cresce na ordem de criação, nunca empata.
    ciclos = list(CicloVideo.objects.filter(produto=produto).order_by('-criado_em', '-id'))

    contagem_por_etapa: dict[str, int] = {}
    for ciclo in ciclos:
        etapa = ciclo.etapa_atual()
        # * [EXPLICAÇÃO] → Badge de status (Aguardando/Aprovado/Recusado/
        #                  Replicado) quando já tem status; senão, badge da
        #                  etapa de produção (Base/Roteiro/Completo).
        ciclo.badge = buscar_badge_de(BADGES_STATUS_POSTAGEM, ciclo.status) if ciclo.status else buscar_badge_de(BADGES_ETAPA, etapa)
        contagem_por_etapa[etapa] = contagem_por_etapa.get(etapa, 0) + 1

    resumo = [
        ResumoEtapa(
            valor=etapa_valor,
            label=buscar_badge_de(BADGES_ETAPA, etapa_valor).label,
            classe=buscar_badge_de(BADGES_ETAPA, etapa_valor).classe,
            quantidade=quantidade,
        )
        for etapa_valor, quantidade in contagem_por_etapa.items()
    ]

    linha_do_tempo = montar_linha_do_tempo_produto(produto)

    # Mesmo padrão de calcular_indicadores() (a_fazer_hoje): produto sem
    # ParticipacaoAgenda ainda nunca foi tocado por nenhuma ação manual —
    # conta como Ativo, o próprio default do campo, nunca fica sem status.
    participacao = getattr(produto, 'participacao_agenda', None)
    status_manual = participacao.status_manual_atual() if participacao else StatusManualAgenda.ATIVO

    return HistoricoProduto(
        produto=produto,
        ciclos=ciclos,
        total=len(ciclos),
        resumo=resumo,
        eventos=linha_do_tempo.eventos,
        status_manual_atual=buscar_badge_de(BADGES_STATUS_MANUAL, status_manual),
        aviso_gap=linha_do_tempo.aviso_gap,
    )


# Função Objetivo: Busca PRODUTOS que têm pelo menos 1 CicloVideo batendo com
# os filtros (fase/status/intervalo de data) + busca por nome/EAN/SKU. Devolve
# só os PRODUTOS — o conteúdo de cada um vem de montar_historico_produto,
# sempre completo.
def listar_produtos_com_historico(busca: str | None = None, filtros: dict | None = None) -> QuerySet:
    filtros = filtros or {}

    ciclos = CicloVideo.objects.all()
    if filtros.get('fase'):
        ciclos = ciclos.filter(fase__in=filtros['fase'])
    if filtros.get('status'):
        ciclos = ciclos.filter(status__in=filtros['status'])
    if filtros.get('data_de'):
        ciclos = ciclos.filter(criado_em__date__gte=filtros['data_de'])
    if filtros.get('data_ate'):
        ciclos = ciclos.filter(criado_em__date__lte=filtros['data_ate'])

    ids_produtos = ciclos.values_list('produto_id', flat=True).distinct()
    produtos = Produto.objects.filter(id__in=ids_produtos)

    if filtros.get('urgente'):
        # Produto sem ParticipacaoAgenda nunca teve o botão "Urgente"
        # clicado — conta como "não urgente" (mesmo default do campo),
        # nunca deve ficar de fora do filtro "não urgente" só por não ter
        # o registro relacionado criado ainda.
        valores_urgente = {v == 'sim' for v in filtros['urgente']}
        condicao = Q()
        if True in valores_urgente:
            condicao |= Q(participacao_agenda__urgente=True)
        if False in valores_urgente:
            condicao |= Q(participacao_agenda__urgente=False) | Q(participacao_agenda__isnull=True)
        produtos = produtos.filter(condicao)
    if filtros.get('marcas'):
        produtos = produtos.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        produtos = produtos.filter(indicadores_agenda__status_manual__in=filtros['status_manual'])

    if busca:
        for termo in busca.split():
            produtos = produtos.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    return produtos.order_by('titulo')