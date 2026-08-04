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

# * [EXPLICAÇÃO] → Vocabulário das 5 telas da Agenda de Vídeos (decisão de
#                  03/08) — substitui o antigo "estágio", que confundia
#                  "produto sem nenhum ciclo" com "produto ainda em
#                  Simples" (2 coisas que deveriam ser a mesma tela).
class Tela(models.TextChoices):
    TODOS = 'todos', 'Todos'
    NAO_AGENDADO = 'nao_agendado', 'Não Agendado'
    SIMPLES = 'simples', 'Simples'
    VIDEO_MENSAL = 'video_mensal', 'Vídeo Mensal'
    VIDEO_TRIMESTRAL = 'video_trimestral', 'Vídeo Trimestral'
    A_FAZER_HOJE = 'a_fazer_hoje', 'A Fazer Hoje'

OPCOES_TELA = Tela.choices

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

# * [EXPLICAÇÃO] → Só Base/Roteiro/Completo entram no cálculo de risco —
#                  são as 3 etapas sem trava de data (podem ser adiantadas),
#                  então "risco" é a única forma de saber que o prazo do
#                  ciclo está próximo antes de chegar em Postar.
ETAPAS_EM_PRODUCAO = ['base', 'roteiro', 'completo']

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


def condicao_pendencia_agora(chave: str) -> Q:
    # Função Objetivo: 1 condição por etapa exibida como chip-contador nas
    # telas Simples/Vídeo Mensal/Vídeo Trimestral.
    match chave:
        case 'base':
            # * [EXPLICAÇÃO] → Soma quem nunca teve nenhum CicloVideo (etapa
            #                  sintética 'nao_agendado', sem ciclo pra
            #                  perguntar) com quem já tem ciclo em Base —
            #                  decisão de 03/08: as 2 situações pedem a
            #                  mesma ação (gravar/terminar o Base), a
            #                  distinção é só técnica, não deve virar 2
            #                  chips.
            return Q(indicadores_agenda__etapa_atual__in=['base', 'nao_agendado'])
        case 'recusado':
            # * [EXPLICAÇÃO] → etapa_atual() devolve 'completo' pros 2 casos
            #                  (nunca feito OU recusado, precisa refazer) —
            #                  só o status do ciclo distingue os 2.
            return Q(status_ciclo_atual=StatusPostagem.RECUSADO)
        case 'completo':
            # * [CORREÇÃO] → status_ciclo_atual é NULL no caso mais comum
            #                  (nunca chegou a ser postado) — "NOT (NULL =
            #                  valor)" em SQL dá NULL, não True, então ~Q
            #                  sozinho excluía TODOS os "nunca feito".
            #                  Precisa tratar NULL como "não recusado"
            #                  explicitamente.
            return Q(indicadores_agenda__etapa_atual='completo') & (
                Q(status_ciclo_atual__isnull=True) | ~Q(status_ciclo_atual=StatusPostagem.RECUSADO)
            )
        case _:
            return Q(indicadores_agenda__etapa_atual=chave)


def _construir_condicao_risco(hoje: date) -> Q:
    # Função Objetivo: ciclo em produção (sem trava de data) com o prazo
    # perto, mas ainda não atrasado — extraída aqui pra ser fonte única
    # (antes duplicada, quase igual, em listar_produtos_agenda_filtrados()
    # e em a_fazer_hoje.py — a cópia de lá some na Fase 2).
    limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
    return (
        Q(indicadores_agenda__etapa_atual__in=ETAPAS_EM_PRODUCAO) &
        Q(data_devida_ciclo_atual__lte=limite_risco) &
        ~Q(indicadores_agenda__ciclo_atual_atrasado=True)
    )


def _condicao_nao_agendado() -> Q:
    # Função Objetivo: Simples já replicado (etapa_atual='concluido') — só
    # falta o clique de "Agendar" pra virar Vídeo Mensal #1. É o único
    # caso em que 'concluido' persiste de verdade: Mensal e Trimestral
    # sempre criam o próximo ciclo sozinhos assim que replicam, então
    # nunca ficam parados em 'concluido'.
    return Q(indicadores_agenda__fase_atual=Fase.SIMPLES, indicadores_agenda__etapa_atual='concluido')


def _condicao_simples_em_andamento() -> Q:
    # Função Objetivo: Simples ainda rodando os 5 passos — inclui quem
    # nunca teve nenhum CicloVideo (mesmo motivo do case 'base' de
    # condicao_pendencia_agora).
    nunca_tocado = Q(indicadores_agenda__fase_atual='', indicadores_agenda__etapa_atual='nao_agendado')
    em_producao = Q(indicadores_agenda__fase_atual=Fase.SIMPLES) & ~Q(indicadores_agenda__etapa_atual='concluido')
    return nunca_tocado | em_producao


def _condicao_fase(fase: str) -> Q:
    # Função Objetivo: Mensal/Trimestral inteiros, sem exigir urgência —
    # nunca precisa excluir 'concluido' (ver _condicao_nao_agendado).
    return Q(indicadores_agenda__fase_atual=fase)


# * [EXPLICAÇÃO] → Os 6 motivos que tornam 1 produto urgente hoje — cada
#                  um vira chip-contador clicável na tela A Fazer Hoje,
#                  igual aos 7 de OPCOES_PENDENTE_AGORA nas telas de fase.
OPCOES_MOTIVO_A_FAZER_HOJE = [
    ('atrasado', 'Atrasado'),
    ('risco', 'Risco'),
    ('postar_hoje', 'Postar hoje'),
    ('aguardando_aprovacao', 'Aguardando aprovação'),
    ('replicar', 'Replicar'),
    ('recusado', 'Recusado'),
]


def condicao_motivo_a_fazer_hoje(chave: str, hoje: date) -> Q:
    # Função Objetivo: 1 condição por motivo de urgência. Pressupõe as
    # mesmas annotations de condicao_tela(), mais 'postou_hoje' (só usada
    # aqui, em 'postar_hoje').
    match chave:
        case 'atrasado':
            return Q(indicadores_agenda__ciclo_atual_atrasado=True)
        case 'risco':
            return _construir_condicao_risco(hoje)
        case 'postar_hoje':
            # * [CORREÇÃO] → 'postou_hoje=False' protege contra o cache de
            #                etapa_atual ficar desatualizado (ex: já clicou
            #                Postar, mas a sincronização ainda não rodou) —
            #                sem isso, o produto reaparece pedindo pra
            #                postar de novo no mesmo dia. Conferido contra
            #                o teste já existente,
            #                test_listar_etapa_postar_ja_postou_hoje_nao_aparece.
            return Q(indicadores_agenda__etapa_atual='postar', data_devida_ciclo_atual=hoje, postou_hoje=False)
        case 'aguardando_aprovacao' | 'replicar':
            return Q(indicadores_agenda__etapa_atual=chave)
        case 'recusado':
            return Q(status_ciclo_atual=StatusPostagem.RECUSADO)
        case _:
            raise ValueError(f'Motivo desconhecido: {chave!r}')


def _condicao_a_fazer_hoje(hoje: date) -> Q:
    # Função Objetivo: cruza Mensal+Trimestral com pelo menos 1 dos 6
    # motivos de urgência — construída a partir de
    # condicao_motivo_a_fazer_hoje(), nunca duplicada: os chips-contador
    # da tela usam a mesma fonte.
    escopo_fase = Q(indicadores_agenda__fase_atual__in=[Fase.VIDEO_MENSAL, Fase.VIDEO_TRIMESTRAL])
    condicao_urgencia = Q()
    for chave, _ in OPCOES_MOTIVO_A_FAZER_HOJE:
        condicao_urgencia |= condicao_motivo_a_fazer_hoje(chave, hoje)
    return escopo_fase & condicao_urgencia


def contar_por_condicoes(qs: QuerySet, condicoes: dict[str, Q]) -> dict[str, int]:
    # Função Objetivo: n contagens simultâneas numa única query agregada
    # (nunca 1 query por chip) — serve tanto os chips de etapa quanto os
    # de motivo de urgência, sempre em cima do queryset já filtrado pela
    # tela (sem os filtros de etapa/motivo aplicados ainda).
    aggregates = {chave: Count('pk', filter=condicao) for chave, condicao in condicoes.items()}
    return qs.aggregate(**aggregates)


def _condicao_todos() -> Q:
    # Função Objetivo: nenhuma restrição de fase/etapa — mostra literalmente
    # todo produto, cache sincronizado ou não (útil pra enxergar quem ainda
    # não sincronizou, em vez de escondê-lo em silêncio). Reintroduz a
    # capacidade "ver tudo" que o sistema antigo tinha quando nenhuma
    # caixinha de estágio era marcada, perdida no redesenho das 5 telas.
    return Q()


def condicao_tela(tela: str, hoje: date) -> Q:
    # Função Objetivo: 1 condição por tela — fonte única de "quem aparece
    # onde", reaproveitada tanto pela listagem quanto pela contagem de
    # cada tela. Pressupõe que o queryset já foi anotado com
    # data_devida_ciclo_atual, ciclo_atual_atrasado e postou_hoje (ver
    # listar_produtos_agenda_filtrados()).
    match tela:
        case Tela.TODOS:
            return _condicao_todos()
        case Tela.NAO_AGENDADO:
            return _condicao_nao_agendado()
        case Tela.SIMPLES:
            return _condicao_simples_em_andamento()
        case Tela.VIDEO_MENSAL | Tela.VIDEO_TRIMESTRAL:
            return _condicao_fase(tela)
        case Tela.A_FAZER_HOJE:
            return _condicao_a_fazer_hoje(hoje)
        case _:
            raise ValueError(f'Tela desconhecida: {tela!r}')


def _campos_ordenacao(tela: str, ordenar: str) -> tuple[str, ...]:
    # Função Objetivo: A Fazer Hoje tem ordenação fixa (prioridade → fase →
    # prazo, não escolhida pelo usuário) — as outras 4 telas usam a coluna
    # dos cabeçalhos ordenáveis, como já era antes desta reescrita.
    if tela == Tela.A_FAZER_HOJE:
        return ('prioridade_ordenacao', 'ordenacao_fase', 'data_devida_ciclo_atual')
    campo_ordenacao = CAMPOS_ORDENACAO.get(ordenar.lstrip('-'), 'titulo')
    if ordenar.startswith('-'):
        campo_ordenacao = f'-{campo_ordenacao}'
    return ('prioridade_ordenacao', 'ordenacao_fase', campo_ordenacao)


def construir_queryset_tela(
    tela: str, busca: str | None = None, filtros: dict | None = None, data_referencia: date | None = None,
) -> tuple[QuerySet, date]:
    # Função Objetivo: monta o queryset da tela com todos os filtros
    # EXCETO etapa/motivo (pendente_agora/motivo_a_fazer_hoje) — base
    # compartilhada entre a listagem final (que ainda filtra etapa/motivo
    # e ordena) e a contagem dos chips (que precisa do queryset SEM esse
    # filtro, senão o chip clicado zeraria a própria contagem). Retorna
    # também 'hoje' já calculado, pra quem for contar não precisar
    # recalcular.
    filtros = filtros or {}
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())

    ciclo_mais_recente = CicloVideo.objects.filter(produto=OuterRef('pk')).order_by('-criado_em')

    qs = Produto.objects.select_related(
        'participacao_agenda', 'indicadores_agenda', 'snapshot_drive',
    ).annotate(
        status_ciclo_atual=Subquery(ciclo_mais_recente.values('status')[:1]),
        data_devida_ciclo_atual=Subquery(ciclo_mais_recente.values('data_devida')[:1]),
        numero_ocorrencia_ciclo_atual=Subquery(ciclo_mais_recente.values('numero_ocorrencia')[:1]),
        postou_hoje=construir_condicao_postou_hoje(data_referencia=hoje),
        prioridade_ordenacao=construir_annotation_prioridade(),
        ordenacao_fase=construir_annotation_ordenacao_fase(),
    ).filter(condicao_tela(tela, hoje))

    if tela == Tela.A_FAZER_HOJE:
        # * [EXPLICAÇÃO] → Só aqui a exclusão é incondicional — A Fazer
        #                  Hoje é lista de ação (pausado nunca é "pra
        #                  fazer"); as outras 4 telas são listagem geral e
        #                  mostram pausado, a menos que o usuário filtre
        #                  status_manual explicitamente (decisão de 03/08).
        qs = qs.exclude(
            indicadores_agenda__status_manual__in=[StatusManualAgenda.PAUSADO, StatusManualAgenda.DESCONTINUADO],
        )

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
    # Função Objetivo: listagem final de 1 tela — pega a base de
    # construir_queryset_tela(), aplica o filtro de etapa/motivo (o único
    # que também é chip-contador) e ordena. Substitui a antiga dupla
    # listar_produtos_agenda_filtrados()/listar_a_fazer_hoje().
    filtros = filtros or {}
    qs, hoje = construir_queryset_tela(tela, busca, filtros, data_referencia)

    if tela == Tela.A_FAZER_HOJE:
        if filtros.get('motivo_a_fazer_hoje'):
            condicao_combinada = Q()
            for chave in filtros['motivo_a_fazer_hoje']:
                condicao_combinada |= condicao_motivo_a_fazer_hoje(chave, hoje)
            qs = qs.filter(condicao_combinada)
    elif filtros.get('pendente_agora'):
        condicao_combinada = Q()
        for chave in filtros['pendente_agora']:
            condicao_combinada |= condicao_pendencia_agora(chave)
        qs = qs.filter(condicao_combinada)

    return qs.order_by(*_campos_ordenacao(tela, ordenar))