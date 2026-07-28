# agenda_videos/funcoes_auxiliares/filtros_agenda_videos.py

# * [RESUMO] → Busca, filtros e ordenação da tela única "Agenda de Vídeos".
# Prioridade de ordenação (25/07) — SEMPRE aplicada, em qualquer listagem/
# estágio, ANTES de paginar. Regra completa e a versão Python equivalente
# (usada em A Fazer Hoje) vivem em prioridade_agenda_videos.py (26/07,
# pente fino) — mudou a regra? Mexe nos 2 lugares, documentados cruzados.
# "Ordenar por" (Nome/Marca/etc.) continua funcionando, mas só como DESEMPATE
# dentro de cada grupo de prioridade, nunca embaralhando os grupos entre si.
#
# Filtros de checkbox/faixa que já existiam (status manual, urgente, vídeo, etc.)
# continuam aqui intocados por enquanto — serão repensados numa rodada própria
# (roteiros_gerados/completos_produzidos/roteiros_insuficientes/quantidade_roteiros
# SEGUEM QUEBRADOS de propósito — decisão do usuário, não mexer até repensar os
# filtros com calma).
#
# Filtros novos (26/07): Atrasado/Risco/Sem vídeo viram filtro de verdade (antes
# só existiam como badge visual); Vencimento (faixa de data sobre
# fim_ocorrencia_atual, adicionado em CAMPOS_FAIXA); "Pendente agora" (9
# categorias de fila de trabalho, via Exists()/Subquery — nunca em Python/loop,
# mesmo motivo de escala já documentado pro resto da tela). A MESMA regra de
# "Pendente agora" existe em Python, pra A Fazer Hoje (a_fazer_hoje.py,
# PENDENCIAS_AGORA_PYTHON) — documentada cruzada, mesmo padrão da prioridade.

from datetime import date
from django.db.models import Q, OuterRef, Subquery, Exists
from produtos.models import Produto
from agenda_videos.models import Postagem, PreparacaoVideoFase, Fase, StatusVideo, StatusPostagem
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje, adicionar_dias_uteis
from agenda_videos.funcoes_auxiliares.prioridade_agenda_videos import (
    construir_annotation_prioridade, construir_annotation_ordenacao_fase,
)
# * [EXPLICAÇÃO] → DIAS_RISCO importado de a_fazer_hoje.py, não duplicado —
#                  mesma janela de risco (1 dia útil) usada nos 2 lugares
#                  (26/07, "fonte única de verdade"). Import seguro (a_fazer_hoje.py
#                  não importa nada daqui, sem risco de import circular).
from agenda_videos.funcoes_auxiliares.a_fazer_hoje import DIAS_RISCO
from core.funcoes_auxiliares.filtros_genericos import aplicar_filtro_faixa

CAMPOS_ORDENACAO = {
    'titulo': 'titulo', 'marca': 'marca', 'estoque': 'estoque',
    'ocorrencia_atual': 'andamento_agenda__ocorrencia_atual',
    'inicio_fase': 'andamento_agenda__inicio_fase',
    'fim_fase': 'andamento_agenda__fim_fase',
    'quantidade_roteiros': 'progresso_producao_video__quantidade_roteiros',
}

CAMPOS_FAIXA = [
    'andamento_agenda__ocorrencia_atual',
    'andamento_agenda__inicio_fase',
    'andamento_agenda__fim_fase',
    'andamento_agenda__fim_ocorrencia_atual',
    'progresso_producao_video__quantidade_roteiros',
]

# * [EXPLICAÇÃO] → As 9 categorias de "Pendente agora" — fila de trabalho por
#                  tipo de tarefa, independente da fase. MESMA lista existe em
#                  Python, pra A Fazer Hoje (a_fazer_hoje.py,
#                  PENDENCIAS_AGORA_PYTHON) — documentada cruzada, adicionou
#                  categoria nova? Bota nas 2.
OPCOES_PENDENTE_AGORA = [
    ('roteiros_diaria', 'Roteiros — Diária'),
    ('completos_diaria', 'Completos — Diária'),
    ('roteiros_semanal', 'Roteiros — Semanal'),
    ('completos_semanal', 'Completos — Semanal'),
    ('roteiros_mensal', 'Roteiros — Mensal'),
    ('completos_mensal', 'Completos — Mensal'),
    ('aguardando_postar', 'Aguardando Postar'),
    ('aguardando_aprovacao', 'Aguardando aprovação do ML'),
    ('recusado', 'Recusado, aguardando decisão'),
]


def _condicao_roteiros_pendente_diaria():
    return Q(
        progresso_producao_video__video_simples_status=StatusVideo.GERADO,
        progresso_producao_video__video_base_status=StatusVideo.GERADO,
    ) & ~Exists(PreparacaoVideoFase.objects.filter(
        produto=OuterRef('pk'), fase=Fase.DIARIA, roteiros_gerados=True,
    ))


def _condicao_completos_pendente_diaria():
    return Exists(PreparacaoVideoFase.objects.filter(
        produto=OuterRef('pk'), fase=Fase.DIARIA, roteiros_gerados=True, completos_produzidos=False,
    ))


def _condicao_roteiros_pendente_fase(fase):
    return Q(andamento_agenda__fase_atual__fase=fase) & ~Exists(PreparacaoVideoFase.objects.filter(
        produto=OuterRef('pk'), fase=fase, roteiros_gerados=True,
    ))


def _condicao_completos_pendente_fase(fase):
    return Q(andamento_agenda__fase_atual__fase=fase) & Exists(PreparacaoVideoFase.objects.filter(
        produto=OuterRef('pk'), fase=fase, roteiros_gerados=True, completos_produzidos=False,
    ))


# * [EXPLICAÇÃO] → Pool pronto = roteiros E completos da fase ATUAL do
#                  produto já feitos — base de "Aguardando Postar".
def _condicao_pool_pronto_fase_atual():
    return Exists(PreparacaoVideoFase.objects.filter(
        produto=OuterRef('pk'), fase=OuterRef('andamento_agenda__fase_atual__fase'),
        roteiros_gerados=True, completos_produzidos=True,
    ))


# Função Objetivo: Traduz 1 categoria de "Pendente agora" na condição Q
# correspondente. "status_postagem_ocorrencia_atual" precisa já estar
# anotado no queryset por quem chama (ver listar_produtos_agenda_filtrados).
def _condicao_pendencia(chave):
    andamento_ativo = Q(andamento_agenda__isnull=False, andamento_agenda__concluido=False)

    if chave == 'roteiros_diaria':
        return _condicao_roteiros_pendente_diaria()
    if chave == 'completos_diaria':
        return _condicao_completos_pendente_diaria()
    if chave == 'roteiros_semanal':
        return _condicao_roteiros_pendente_fase(Fase.SEMANAL)
    if chave == 'completos_semanal':
        return _condicao_completos_pendente_fase(Fase.SEMANAL)
    if chave == 'roteiros_mensal':
        return _condicao_roteiros_pendente_fase(Fase.MENSAL)
    if chave == 'completos_mensal':
        return _condicao_completos_pendente_fase(Fase.MENSAL)
    if chave == 'aguardando_postar':
        return andamento_ativo & _condicao_pool_pronto_fase_atual() & Q(status_postagem_ocorrencia_atual__isnull=True)
    if chave == 'aguardando_aprovacao':
        return andamento_ativo & Q(status_postagem_ocorrencia_atual=StatusPostagem.AGUARDANDO_APROVACAO)
    if chave == 'recusado':
        return andamento_ativo & Q(status_postagem_ocorrencia_atual=StatusPostagem.RECUSADO)
    raise ValueError(f'Categoria de pendência desconhecida: {chave}')


def listar_produtos_agenda_filtrados(busca=None, filtros=None, ordenar='titulo', data_referencia=None):
    filtros = filtros or {}
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())

    # * [EXPLICAÇÃO] → Escopada na ocorrência ATUAL (fase + número certos) —
    #                  corrigido (26/07): existia uma versão anterior
    #                  (status_postagem_recente) que pegava a Postagem mais
    #                  recente do produto INTEIRO, qualquer fase/ocorrência.
    #                  Bug real encontrado em teste: um produto que passou
    #                  por "Seguir sem repor" (Recusada deixada de propósito
    #                  no histórico, sem nunca ser resolvida) continuava
    #                  aparecendo no filtro "Recusado" muito depois de já ter
    #                  avançado de fase — a Postagem antiga, abandonada, ainda
    #                  era "a mais recente do produto", mesmo sem relevância
    #                  nenhuma pro presente. Removida — nada mais usa ela.
    postagem_ocorrencia_atual = Postagem.objects.filter(
        produto=OuterRef('pk'),
        fase=OuterRef('andamento_agenda__fase_atual__fase'),
        numero_ocorrencia=OuterRef('andamento_agenda__ocorrencia_atual'),
    ).order_by('-criado_em')

    # * [EXPLICAÇÃO] → Base NÃO exige mais AndamentoAgenda (diferente da antiga
    #                  tela "Diários") — "Não Agendado"/"Pronto para Agendar"
    #                  ainda não têm esse registro, e precisam aparecer também.
    qs = Produto.objects.select_related(
        'andamento_agenda', 'andamento_agenda__fase_atual',
        'progresso_producao_video', 'roadmap_agenda', 'snapshot_drive',
    ).annotate(
        status_postagem_ocorrencia_atual=Subquery(postagem_ocorrencia_atual.values('status')[:1]),
        prioridade_ordenacao=construir_annotation_prioridade(hoje),
        ordenacao_fase=construir_annotation_ordenacao_fase(),
    )

    if busca:
        for termo in busca.split():
            qs = qs.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    if filtros.get('estagio'):
        qs = qs.filter(roadmap_agenda__estagio_atual__in=filtros['estagio'])

    if filtros.get('marcas'):
        qs = qs.filter(marca__in=filtros['marcas'])
    if filtros.get('status_manual'):
        qs = qs.filter(andamento_agenda__status_manual__in=filtros['status_manual'])
    if filtros.get('urgente'):
        qs = qs.filter(roadmap_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])
    if filtros.get('sem_video'):
        qs = qs.filter(roadmap_agenda__tem_video_reprovado__in=[v == 'sim' for v in filtros['sem_video']])
    if filtros.get('reestruturacao_manual'):
        qs = qs.filter(roadmap_agenda__reestruturacao_manual__in=[v == 'sim' for v in filtros['reestruturacao_manual']])
    if filtros.get('video_simples_status'):
        qs = qs.filter(progresso_producao_video__video_simples_status__in=filtros['video_simples_status'])
    if filtros.get('video_base_status'):
        qs = qs.filter(progresso_producao_video__video_base_status__in=filtros['video_base_status'])
    if filtros.get('roteiros_gerados'):
        qs = qs.filter(progresso_producao_video__roteiros_gerados__in=[v == 'sim' for v in filtros['roteiros_gerados']])
    if filtros.get('completos_produzidos'):
        qs = qs.filter(progresso_producao_video__completos_produzidos__in=[v == 'sim' for v in filtros['completos_produzidos']])
    if filtros.get('roteiros_insuficientes'):
        qs = qs.filter(progresso_producao_video__roteiros_insuficientes__in=[v == 'sim' for v in filtros['roteiros_insuficientes']])
    if filtros.get('status_postagem'):
        qs = qs.filter(status_postagem_ocorrencia_atual__in=filtros['status_postagem'])

    # * [EXPLICAÇÃO] → Atrasado/Risco eram só badge visual até 26/07 — mesma
    #                  regra que já existe em calcular_indicadores_atraso
    #                  (a_fazer_hoje.py), expressa aqui como Q pra funcionar em
    #                  SQL. "Sim" filtra, "Não" exclui; os 2 marcados juntos
    #                  (ou nenhum) não filtra nada.
    condicao_atrasado = Q(
        andamento_agenda__isnull=False, andamento_agenda__concluido=False,
        andamento_agenda__fim_ocorrencia_atual__lt=hoje,
    )
    if filtros.get('atrasado'):
        valores = filtros['atrasado']
        if 'sim' in valores and 'nao' not in valores:
            qs = qs.filter(condicao_atrasado)
        elif 'nao' in valores and 'sim' not in valores:
            qs = qs.exclude(condicao_atrasado)

    if filtros.get('risco'):
        limite_risco = adicionar_dias_uteis(hoje, DIAS_RISCO)
        condicao_risco = (
            Q(andamento_agenda__isnull=False, andamento_agenda__concluido=False) &
            ~Q(andamento_agenda__fase_atual__fase=Fase.DIARIA) &
            Q(andamento_agenda__fim_ocorrencia_atual__gte=hoje, andamento_agenda__fim_ocorrencia_atual__lte=limite_risco) &
            ~condicao_atrasado
        )
        valores = filtros['risco']
        if 'sim' in valores and 'nao' not in valores:
            qs = qs.filter(condicao_risco)
        elif 'nao' in valores and 'sim' not in valores:
            qs = qs.exclude(condicao_risco)

    # * [EXPLICAÇÃO] → "Pendente agora" — cada categoria marcada vira 1 OR (o
    #                  produto aparece se estiver em QUALQUER uma das
    #                  marcadas), nunca AND.
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

    # * [EXPLICAÇÃO] → Prioridade primeiro, depois o grupo de fase
    #                  (Diária/Semanal/Mensal), e só então "Ordenar por" desempata
    #                  dentro de cada combinação — nunca embaralha os grupos entre si.
    return qs.order_by('prioridade_ordenacao', 'ordenacao_fase', campo_ordenacao)