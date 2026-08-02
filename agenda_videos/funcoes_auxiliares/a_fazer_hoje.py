# agenda_videos/funcoes_auxiliares/a_fazer_hoje.py

# Função Objetivo: Lista produtos "A Fazer Hoje" — mesma queryset anotada da
# listagem paginada, com exclusões a mais (concluído, "postar" ainda não
# devido, já postou hoje).
# Reestruturação completa (30/07): virou queryset (era loop Python) porque
# IndicadoresAgendaProduto já guarda etapa_atual em cache.
# * [CORREÇÃO] → filtro de faixa usava chaves erradas ("vencimento_min/max")
# — nunca funcionava. Corrigido reaproveitando aplicar_filtro_faixa.

from datetime import date

from django.db.models import OuterRef, Q, QuerySet, Subquery

from produtos.models import Produto
from agenda_videos.models import CicloVideo, StatusManualAgenda
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje, adicionar_dias_uteis
from agenda_videos.funcoes_auxiliares.prioridade_agenda_videos import (
    construir_annotation_prioridade, construir_annotation_ordenacao_fase,
)
from agenda_videos.funcoes_auxiliares.filtros_agenda_videos import DIAS_RISCO, CAMPOS_FAIXA, condicao_pendencia_agora
from agenda_videos.funcoes_auxiliares.postagem_ciclica import construir_condicao_postou_hoje
from core.funcoes_auxiliares.filtros_genericos import aplicar_filtro_faixa

ETAPAS_EM_PRODUCAO = ['base', 'roteiro', 'completo']


def calcular_indicadores_ciclo(produto: Produto, ciclo: CicloVideo, data_referencia: date | None = None) -> str:
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())
    limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
    etapa = ciclo.etapa_atual()

    produto.a_fazer_hoje_atrasado = ciclo.esta_atrasado()
    produto.a_fazer_hoje_risco = (
        not produto.a_fazer_hoje_atrasado
        and etapa in ETAPAS_EM_PRODUCAO
        and ciclo.data_devida is not None
        and ciclo.data_devida <= limite_risco
    )
    produto.a_fazer_hoje_vencimento = ciclo.data_devida
    produto.a_fazer_hoje_fase = ciclo.fase
    return etapa


def listar_a_fazer_hoje(busca: str | None = None, filtros: dict | None = None, data_referencia: date | None = None) -> QuerySet:
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())
    limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
    filtros = filtros or {}

    ciclo_mais_recente = CicloVideo.objects.filter(produto=OuterRef('pk')).order_by('-criado_em')

    qs = Produto.objects.filter(
        ciclos_video__isnull=False,
    ).exclude(
        indicadores_agenda__status_manual__in=[StatusManualAgenda.PAUSADO, StatusManualAgenda.DESCONTINUADO],
    ).exclude(
        indicadores_agenda__etapa_atual='concluido',
    ).select_related(
        'participacao_agenda', 'indicadores_agenda', 'snapshot_drive',
    ).distinct().annotate(
        status_ciclo_atual=Subquery(ciclo_mais_recente.values('status')[:1]),
        data_devida_ciclo_atual=Subquery(ciclo_mais_recente.values('data_devida')[:1]),
        postou_hoje=construir_condicao_postou_hoje(data_referencia=hoje),
        prioridade_ordenacao=construir_annotation_prioridade(),
        ordenacao_fase=construir_annotation_ordenacao_fase(),
    )

    qs = qs.exclude(Q(indicadores_agenda__etapa_atual='postar') & Q(data_devida_ciclo_atual__gt=hoje))
    qs = qs.exclude(Q(indicadores_agenda__etapa_atual='postar') & Q(postou_hoje=True))

    if busca:
        for termo in busca.split():
            qs = qs.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    if filtros.get('marcas'):
        qs = qs.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        qs = qs.filter(indicadores_agenda__status_manual__in=filtros['status_manual'])
    if filtros.get('urgente'):
        qs = qs.filter(participacao_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])
    if filtros.get('sem_video'):
        qs = qs.filter(indicadores_agenda__tem_video_reprovado__in=[v == 'sim' for v in filtros['sem_video']])

    condicao_atrasado = Q(indicadores_agenda__ciclo_atual_atrasado=True)
    if filtros.get('atrasado'):
        valores = filtros['atrasado']
        if 'sim' in valores and 'nao' not in valores:
            qs = qs.filter(condicao_atrasado)
        elif 'nao' in valores and 'sim' not in valores:
            qs = qs.exclude(condicao_atrasado)

    if filtros.get('risco'):
        condicao_risco = (
            Q(indicadores_agenda__etapa_atual__in=ETAPAS_EM_PRODUCAO) &
            Q(data_devida_ciclo_atual__lte=limite_risco) &
            ~condicao_atrasado
        )
        valores = filtros['risco']
        if 'sim' in valores and 'nao' not in valores:
            qs = qs.filter(condicao_risco)
        elif 'nao' in valores and 'sim' not in valores:
            qs = qs.exclude(condicao_risco)

    if filtros.get('pendente_agora'):
        condicao_combinada = Q()
        for chave in filtros['pendente_agora']:
            condicao_combinada |= condicao_pendencia_agora(chave)
        qs = qs.filter(condicao_combinada)

    for campo in CAMPOS_FAIXA:
        qs = aplicar_filtro_faixa(qs, filtros, campo)

    return qs.order_by('prioridade_ordenacao', 'ordenacao_fase', 'data_devida_ciclo_atual')