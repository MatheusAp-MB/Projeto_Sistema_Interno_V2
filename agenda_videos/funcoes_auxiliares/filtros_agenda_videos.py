# agenda_videos/funcoes_auxiliares/filtros_agenda_videos.py

# * [RESUMO] → Busca, filtros e ordenação das 6 telas da Agenda de Vídeos.
# Reestruturação completa (12/08) — o antigo "Tela" único misturava 3
# perguntas diferentes (onde no tempo / o que falta fazer / ação minha vs.
# automática) numa lista plana de 6 opções mutuamente exclusivas. Agora
# cada tela responde 1 pergunta só: Geral (navegação livre, Período x
# Etapa), A Fazer Hoje (só produção real — base/roteiro/completo/recusado),
# Aguardando Postar/Replicar (ação mecânica, sem prazo — 2 abas), Aguardando
# Aprovação (espera de terceiro, sem ação minha), Prontos pra Agendar Mensal
# (Simples já replicado, renomeada de "Não Agendado" — o nome antigo dizia
# o oposto do que significava) e Pausados na Agenda (única tela onde
# produto pausado/descontinuado aparece — todas as outras excluem sempre).
#
# Prioridade de ordenação — aplicada em toda tela, exceto Geral (ordenação
# escolhida pelo usuário) e Aguardando Aprovação (só tempo de espera). Regra
# completa vive em prioridade_agenda_videos.py.

from datetime import date

from django.db import models
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone as django_timezone

from produtos.models import Produto
from agenda_videos.models import CicloVideo, Fase, StatusManualAgenda, StatusPostagem, VALIDADE_SNAPSHOT_DRIVE
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje, adicionar_dias_uteis
from agenda_videos.funcoes_auxiliares.postagem_ciclica import construir_condicao_postou_hoje
from agenda_videos.funcoes_auxiliares.prioridade_agenda_videos import (
    construir_annotation_prioridade, construir_annotation_ordenacao_fase,
)
from core.funcoes_auxiliares.filtros_genericos import aplicar_filtro_faixa


class Tela(models.TextChoices):
    GERAL = 'geral', 'Geral'
    A_FAZER_HOJE = 'a_fazer_hoje', 'A Fazer Hoje'
    AGUARDANDO_POSTAR_REPLICAR = 'aguardando_postar_replicar', 'Aguardando Postar/Replicar'
    AGUARDANDO_APROVACAO = 'aguardando_aprovacao', 'Aguardando Aprovação'
    PRONTOS_AGENDAR = 'prontos_agendar', 'Prontos pra Agendar Mensal'
    PAUSADOS = 'pausados', 'Pausados na Agenda'

OPCOES_TELA = Tela.choices


# * [EXPLICAÇÃO] → Só usado por Geral e A Fazer Hoje — as 2 telas que
#                  navegam livremente pelo tempo. Reaproveita os mesmos
#                  valores de Fase, nunca duplicados à mão.
class Periodo(models.TextChoices):
    TODOS = 'todos', 'Todos'
    SIMPLES = 'simples', 'Simples'
    VIDEO_MENSAL = 'video_mensal', 'Vídeo Mensal'
    VIDEO_TRIMESTRAL = 'video_trimestral', 'Vídeo Trimestral'

OPCOES_PERIODO = Periodo.choices

CAMPOS_ORDENACAO = {
    'titulo': 'titulo', 'marca': 'marca', 'estoque': 'estoque',
    'numero_ocorrencia': 'numero_ocorrencia_ciclo_atual',
    'data_devida': 'data_devida_ciclo_atual',
}

CAMPOS_FAIXA = [
    'numero_ocorrencia_ciclo_atual',
    'data_devida_ciclo_atual',
]

DIAS_RISCO = 1  # "hoje e o próximo dia útil" — janela de risco de 1 dia útil à frente

# * [EXPLICAÇÃO] → Segue existindo pro filtro avançado "risco" (checkbox,
#                  independente da tela) e pra a_fazer_hoje.py (card de 1
#                  produto só) — nenhum dos 2 usos foi afetado por esta
#                  reestruturação.
ETAPAS_EM_PRODUCAO = ['base', 'roteiro', 'completo']

# * [EXPLICAÇÃO] → 7 estados reais de 1 ciclo — fonte única, tanto dos
#                  chips de Etapa (Geral/A Fazer Hoje) quanto do escopo
#                  fixo das outras 4 telas.
OPCOES_ETAPA = [
    ('base', 'Aguardando base'),
    ('roteiro', 'Aguardando roteiro'),
    ('completo', 'Aguardando completo'),
    ('postar', 'Aguardando postar'),
    ('aguardando_aprovacao', 'Aguardando aprovação'),
    ('recusado', 'Recusado: aguardando análise manual'),
    ('replicar', 'Aguardando replicar'),
    ('concluido', 'Prontos pra agendar mensal'),
]

OPCOES_ABA = [('postar', 'Postar'), ('replicar', 'Replicar')]

# * [EXPLICAÇÃO] → Só as 4 que demandam esforço real de produção — Postar/
#                  Replicar não produzem nada, só executam (e vão ser
#                  automatizados); Aguardando Aprovação não demanda esforço
#                  nenhum (espera de terceiro). As 3 têm tela própria e
#                  saem do filtro de Etapa de A Fazer Hoje.
ETAPAS_FABRICA = ['base', 'roteiro', 'completo', 'recusado']


def condicao_etapa(chave: str) -> Q:
    # Função Objetivo: 1 condição por etapa — fonte única, usada pelos
    # chips de Geral/A Fazer Hoje E pelo escopo fixo das outras 4 telas.
    match chave:
        case 'base':
            # * [EXPLICAÇÃO] → Soma quem nunca teve nenhum CicloVideo (etapa
            #                  sintética 'nao_agendado') com quem já tem
            #                  ciclo em Base — as 2 pedem a mesma ação.
            return Q(indicadores_agenda__etapa_atual__in=['base', 'nao_agendado'])
        case 'recusado':
            return Q(status_ciclo_atual=StatusPostagem.RECUSADO)
        case 'completo':
            # * [CORREÇÃO] → status_ciclo_atual é NULL no caso mais comum
            #                  (nunca chegou a ser postado) — precisa tratar
            #                  NULL como "não recusado" explicitamente, senão
            #                  ~Q sozinho exclui todos os "nunca feito".
            return Q(indicadores_agenda__etapa_atual='completo') & (
                Q(status_ciclo_atual__isnull=True) | ~Q(status_ciclo_atual=StatusPostagem.RECUSADO)
            )
        case _:
            return Q(indicadores_agenda__etapa_atual=chave)


def _construir_condicao_risco(hoje: date) -> Q:
    # Função Objetivo: ciclo em produção com o prazo perto, mas ainda não
    # atrasado — usado só pelo filtro avançado "risco", independente da
    # navegação por tela.
    limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
    return (
        Q(indicadores_agenda__etapa_atual__in=ETAPAS_EM_PRODUCAO) &
        Q(data_devida_ciclo_atual__lte=limite_risco) &
        ~Q(indicadores_agenda__ciclo_atual_atrasado=True)
    )


def _condicao_a_fazer_hoje() -> Q:
    # Função Objetivo: escopo fixo — produção real. Mensal/Trimestral entram
    # em qualquer etapa de produção (têm prazo real, mesmo parado em Base).
    # Simples nunca tem prazo — só entra se Base já estiver feito (Roteiro/
    # Completo/Recusado), sinal de processo em andamento que falta terminar;
    # Simples em Base (ou nunca tocado) é só backlog, não é urgente hoje.
    condicao_mensal_trimestral = (
        Q(indicadores_agenda__fase_atual__in=[Fase.VIDEO_MENSAL, Fase.VIDEO_TRIMESTRAL]) &
        (condicao_etapa('base') | condicao_etapa('roteiro') | condicao_etapa('completo') | condicao_etapa('recusado'))
    )
    condicao_simples = (
        Q(indicadores_agenda__fase_atual=Fase.SIMPLES) &
        (condicao_etapa('roteiro') | condicao_etapa('completo') | condicao_etapa('recusado'))
    )
    return condicao_mensal_trimestral | condicao_simples


def _condicao_aguardando_postar_replicar() -> Q:
    return condicao_etapa('postar') | condicao_etapa('replicar')


def _condicao_prontos_agendar() -> Q:
    # Função Objetivo: Simples já replicado (etapa_atual='concluido') — só
    # falta o clique de "Agendar" pra virar Vídeo Mensal #1.
    return Q(indicadores_agenda__fase_atual=Fase.SIMPLES, indicadores_agenda__etapa_atual='concluido')


def _condicao_pausados() -> Q:
    return Q(indicadores_agenda__status_manual__in=[StatusManualAgenda.PAUSADO, StatusManualAgenda.DESCONTINUADO])


def condicao_tela(tela: str) -> Q:
    # Função Objetivo: escopo fixo de cada tela, ANTES de Período/Etapa/aba.
    # Geral não tem escopo nenhum — Q() (tudo que estiver ativo).
    match tela:
        case Tela.GERAL:
            return Q()
        case Tela.A_FAZER_HOJE:
            return _condicao_a_fazer_hoje()
        case Tela.AGUARDANDO_POSTAR_REPLICAR:
            return _condicao_aguardando_postar_replicar()
        case Tela.AGUARDANDO_APROVACAO:
            return condicao_etapa('aguardando_aprovacao')
        case Tela.PRONTOS_AGENDAR:
            return _condicao_prontos_agendar()
        case Tela.PAUSADOS:
            return _condicao_pausados()
        case _:
            raise ValueError(f'Tela desconhecida: {tela!r}')


def contar_por_condicoes(qs: QuerySet, condicoes: dict[str, Q]) -> dict[str, int]:
    aggregates = {chave: Count('pk', filter=condicao) for chave, condicao in condicoes.items()}
    return qs.aggregate(**aggregates)


def _campos_ordenacao(tela: str, ordenar: str) -> tuple[str, ...]:
    # Função Objetivo: Geral é a única com ordenação escolhida pelo usuário.
    # Aguardando Aprovação ordena só por tempo de espera (mais recente
    # primeiro). As outras 4 usam a mesma ordenação fixa de sempre:
    # prioridade (urgente/atrasado/reprovado) → fase → prazo.
    if tela == Tela.AGUARDANDO_APROVACAO:
        return ('-aguardando_aprovacao_em_ciclo_atual',)
    if tela != Tela.GERAL:
        return ('prioridade_ordenacao', 'ordenacao_fase', 'data_devida_ciclo_atual')
    campo_ordenacao = CAMPOS_ORDENACAO.get(ordenar.lstrip('-'), 'titulo')
    if ordenar.startswith('-'):
        campo_ordenacao = f'-{campo_ordenacao}'
    return ('prioridade_ordenacao', 'ordenacao_fase', campo_ordenacao)


def construir_queryset_tela(
    tela: str, busca: str | None = None, filtros: dict | None = None, data_referencia: date | None = None,
) -> tuple[QuerySet, date]:
    # Função Objetivo: monta o queryset da tela com todos os filtros EXCETO
    # Etapa (que segue funcionando como chip contado) — base compartilhada
    # entre a listagem final e a contagem dos chips.
    filtros = filtros or {}
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())

    ciclo_mais_recente = CicloVideo.objects.filter(produto=OuterRef('pk')).order_by('-criado_em')

    qs = Produto.objects.select_related(
        'participacao_agenda', 'indicadores_agenda', 'snapshot_drive',
    ).annotate(
        status_ciclo_atual=Subquery(ciclo_mais_recente.values('status')[:1]),
        data_devida_ciclo_atual=Subquery(ciclo_mais_recente.values('data_devida')[:1]),
        numero_ocorrencia_ciclo_atual=Subquery(ciclo_mais_recente.values('numero_ocorrencia')[:1]),
        aguardando_aprovacao_em_ciclo_atual=Subquery(ciclo_mais_recente.values('aguardando_aprovacao_em')[:1]),
        postou_hoje=construir_condicao_postou_hoje(data_referencia=hoje),
        prioridade_ordenacao=construir_annotation_prioridade(),
        ordenacao_fase=construir_annotation_ordenacao_fase(),
    ).filter(condicao_tela(tela))

    # * [EXPLICAÇÃO] → Pausado/Descontinuado nunca aparece em nenhuma tela,
    #                  EXCETO a própria — inverte a regra antiga (só "A
    #                  Fazer Hoje" excluía). Decisão de 12/08: pausado só
    #                  existe num lugar, em lugar nenhum mais.
    if tela != Tela.PAUSADOS:
        qs = qs.exclude(
            indicadores_agenda__status_manual__in=[StatusManualAgenda.PAUSADO, StatusManualAgenda.DESCONTINUADO],
        )
    elif filtros.get('status_manual'):
        # * [EXPLICAÇÃO] → Dentro da própria tela Pausados, esse mesmo
        #                  filtro serve pra separar só Pausado de só
        #                  Descontinuado, se quiser — sem escopo novo.
        qs = qs.filter(indicadores_agenda__status_manual__in=filtros['status_manual'])

    if tela in (Tela.GERAL, Tela.A_FAZER_HOJE) and filtros.get('periodo') and filtros['periodo'] != Periodo.TODOS:
        if filtros['periodo'] == Periodo.SIMPLES:
            # * [CORREÇÃO] → Produto nunca tocado tem fase_atual='' (nunca
            #                'simples'), mas já É Simples na prática — é o
            #                ponto de entrada. Sem isso, ficava em limbo: só
            #                aparecia em "Todos", nunca em nenhum período.
            qs = qs.filter(indicadores_agenda__fase_atual__in=[Fase.SIMPLES, ''])
        else:
            qs = qs.filter(indicadores_agenda__fase_atual=filtros['periodo']) 

    if busca:
        for termo in busca.split():
            qs = qs.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    if filtros.get('marcas'):
        qs = qs.filter(marca__in=filtros['marcas'])
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
        condicao_risco = _construir_condicao_risco(hoje)
        valores = filtros['risco']
        if 'sim' in valores and 'nao' not in valores:
            qs = qs.filter(condicao_risco)
        elif 'nao' in valores and 'sim' not in valores:
            qs = qs.exclude(condicao_risco)

    for campo in CAMPOS_FAIXA:
        qs = aplicar_filtro_faixa(qs, filtros, campo)

    return qs, hoje


def listar_produtos_agenda_filtrados(
    tela: str, busca: str | None = None, filtros: dict | None = None,
    ordenar: str = 'titulo', data_referencia: date | None = None,
) -> QuerySet:
    filtros = filtros or {}
    qs, hoje = construir_queryset_tela(tela, busca, filtros, data_referencia)

    if tela in (Tela.GERAL, Tela.A_FAZER_HOJE) and filtros.get('etapa'):
        chaves_validas = set(ETAPAS_FABRICA) if tela == Tela.A_FAZER_HOJE else {c for c, _ in OPCOES_ETAPA}
        condicao_combinada = Q()
        for chave in filtros['etapa']:
            if chave in chaves_validas:
                condicao_combinada |= condicao_etapa(chave)
        qs = qs.filter(condicao_combinada)
    elif tela == Tela.AGUARDANDO_POSTAR_REPLICAR:
        qs = qs.filter(condicao_etapa(filtros.get('aba') or 'postar'))

    return qs.order_by(*_campos_ordenacao(tela, ordenar))