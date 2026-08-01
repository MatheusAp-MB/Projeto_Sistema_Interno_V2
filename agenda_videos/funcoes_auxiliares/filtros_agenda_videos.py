# agenda_videos/funcoes_auxiliares/filtros_agenda_videos.py

# * [RESUMO] → Busca, filtros e ordenação da tela única "Agenda de Vídeos".
# Reestruturação completa (30/07) — antes eram 3 tabelas (progresso/preparação
# por fase/andamento) cruzadas em 9 categorias de "Pendente agora"; agora é só
# o CicloVideo mais recente de cada produto (via Subquery), e a maior parte já
# vem pronta em IndicadoresAgendaProduto (cache).
#
# Prioridade de ordenação — SEMPRE aplicada, em qualquer listagem, ANTES de
# paginar. Regra completa e a versão Python equivalente (A Fazer Hoje) vivem
# em prioridade_agenda_videos.py — mudou a regra? Mexe nos 2 lugares.
#
# * [PENDENTE] → Filtros de vídeo simples/base/roteiros/completos "soltos"
# foram removidos — os conceitos que eles checavam (ProgressoProducaoVideo,
# PreparacaoVideoFase) não existem mais. Repensar com calma quando chegar a
# vez (mesma pendência que já existia antes da reestruturação).

from datetime import date
from django.db.models import Q, OuterRef, Subquery
from produtos.models import Produto
from agenda_videos.models import CicloVideo, Fase, StatusPostagem, VALIDADE_SNAPSHOT_DRIVE
from django.utils import timezone as django_timezone
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje, adicionar_dias_uteis
from agenda_videos.funcoes_auxiliares.prioridade_agenda_videos import (
    construir_annotation_prioridade, construir_annotation_ordenacao_fase,
)
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import DIAS_RISCO
from core.funcoes_auxiliares.filtros_genericos import aplicar_filtro_faixa

CAMPOS_ORDENACAO = {
    'titulo': 'titulo', 'marca': 'marca', 'estoque': 'estoque',
    'numero_ocorrencia': 'numero_ocorrencia_ciclo_atual',
    'data_devida': 'data_devida_ciclo_atual',
}

CAMPOS_FAIXA = [
    'numero_ocorrencia_ciclo_atual',
    'data_devida_ciclo_atual',
]

OPCOES_ESTAGIO = [
    ('', 'Não Agendado'),
    (Fase.SIMPLES, 'Simples'),
    (Fase.VIDEO_MENSAL, 'Vídeo Mensal'),
    (Fase.VIDEO_TRIMESTRAL, 'Vídeo Trimestral'),
]

# * [EXPLICAÇÃO] → 7 categorias agora (eram 10) — não tem mais "por fase"
#                  (ex-Roteiros-Diária vs ex-Roteiros-Semanal), já que toda
#                  fase segue a MESMA sequência de 5 passos agora.
OPCOES_PENDENTE_AGORA = [
    ('base', 'Base'),
    ('roteiro', 'Roteiro'),
    ('completo', 'Completo'),
    ('recusado', 'Recusado, aguardando decisão'),
    ('postar', 'Aguardando Postar'),
    ('aguardando_aprovacao', 'Aguardando aprovação do ML'),
    ('replicar', 'Aprovado, aguardando replicar'),
]


def _condicao_pendencia(chave):
    if chave == 'recusado':
        return Q(status_ciclo_atual=StatusPostagem.RECUSADO)
    if chave == 'completo':
        # * [EXPLICAÇÃO] → etapa_atual() devolve 'completo' pros 2 casos (nunca
        #                  feito OU recusado, precisa refazer) — aqui separa,
        #                  pra "Completo" e "Recusado" serem categorias distintas.
        return Q(indicadores_agenda__etapa_atual='completo') & ~Q(status_ciclo_atual=StatusPostagem.RECUSADO)
    return Q(indicadores_agenda__etapa_atual=chave)


def listar_produtos_agenda_filtrados(busca=None, filtros=None, ordenar='titulo', data_referencia=None):
    filtros = filtros or {}
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())

    ciclo_mais_recente = CicloVideo.objects.filter(produto=OuterRef('pk')).order_by('-criado_em')

    qs = Produto.objects.select_related(
        'participacao_agenda', 'indicadores_agenda', 'snapshot_drive',
    ).annotate(
        status_ciclo_atual=Subquery(ciclo_mais_recente.values('status')[:1]),
        data_devida_ciclo_atual=Subquery(ciclo_mais_recente.values('data_devida')[:1]),
        numero_ocorrencia_ciclo_atual=Subquery(ciclo_mais_recente.values('numero_ocorrencia')[:1]),
        prioridade_ordenacao=construir_annotation_prioridade(),
        ordenacao_fase=construir_annotation_ordenacao_fase(),
    )

    if busca:
        for termo in busca.split():
            qs = qs.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    if filtros.get('estagio'):
        qs = qs.filter(indicadores_agenda__fase_atual__in=filtros['estagio'])
    if filtros.get('marcas'):
        qs = qs.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        qs = qs.filter(indicadores_agenda__status_manual__in=filtros['status_manual'])
    if filtros.get('urgente'):
        qs = qs.filter(participacao_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])
    if filtros.get('sem_video'):
        qs = qs.filter(indicadores_agenda__tem_video_reprovado__in=[v == 'sim' for v in filtros['sem_video']])

    if filtros.get('sincronizado_drive'):
        limite_snapshot = django_timezone.now() - VALIDADE_SNAPSHOT_DRIVE
        condicao_sincronizado = Q(
            snapshot_drive__isnull=False, snapshot_drive__atualizado_em__gte=limite_snapshot,
        )
        valores = filtros['sincronizado_drive']
        if 'sim' in valores and 'nao' not in valores:
            qs = qs.filter(condicao_sincronizado)
        elif 'nao' in valores and 'sim' not in valores:
            qs = qs.exclude(condicao_sincronizado)

    if filtros.get('status_postagem'):
        qs = qs.filter(status_ciclo_atual__in=filtros['status_postagem'])

    condicao_atrasado = Q(indicadores_agenda__ciclo_atual_atrasado=True)
    if filtros.get('atrasado'):
        valores = filtros['atrasado']
        if 'sim' in valores and 'nao' not in valores:
            qs = qs.filter(condicao_atrasado)
        elif 'nao' in valores and 'sim' not in valores:
            qs = qs.exclude(condicao_atrasado)

    if filtros.get('risco'):
        limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
        condicao_risco = (
            Q(indicadores_agenda__etapa_atual__in=['base', 'roteiro', 'completo']) &
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
            condicao_combinada |= _condicao_pendencia(chave)
        qs = qs.filter(condicao_combinada)

    for campo in CAMPOS_FAIXA:
        qs = aplicar_filtro_faixa(qs, filtros, campo)

    campo_ordenacao = CAMPOS_ORDENACAO.get(ordenar.lstrip('-'), 'titulo')
    if ordenar.startswith('-'):
        campo_ordenacao = f'-{campo_ordenacao}'

    return qs.order_by('prioridade_ordenacao', 'ordenacao_fase', campo_ordenacao)