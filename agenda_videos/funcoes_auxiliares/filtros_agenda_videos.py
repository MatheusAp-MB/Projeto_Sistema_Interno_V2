# agenda_videos/funcoes_auxiliares/filtros_agenda_videos.py

# * [RESUMO] → Busca, filtros e ordenação da tela única "Agenda de Vídeos".
# Prioridade de ordenação adicionada (25/07) — SEMPRE aplicada, em qualquer
# listagem/estágio, ANTES de paginar (mesmo princípio de "filtra tudo, depois
# pagina" já usado em todo o resto do projeto — não é ordenação só da página
# atual, é da query inteira):
#   1. Urgente (RoadmapAgenda.urgente=True)
#   2. Atrasado (AndamentoAgenda.fim_ocorrencia_atual < hoje, não concluído)
#   3. Sem vídeo (qualquer variação do produto reprovada no critério UP_HAS_SHORTS,
#      da API do Mercado Livre — NÃO é o nosso video_simples_status interno)
#   4. Resto
# "Ordenar por" (Nome/Marca/etc.) continua funcionando, mas só como DESEMPATE
# dentro de cada grupo de prioridade, nunca embaralhando os grupos entre si.
#
# Filtros de checkbox/faixa que já existiam (status manual, urgente, vídeo, etc.)
# continuam aqui intocados por enquanto — serão repensados numa rodada própria
# (roteiros_gerados/completos_produzidos/roteiros_insuficientes SEGUEM QUEBRADOS
# de propósito — decisão do usuário, não mexer até repensar os filtros com calma).

from datetime import date
from django.db.models import Q, OuterRef, Subquery, Case, When, Value, IntegerField
from produtos.models import Produto
from agenda_videos.models import Postagem, Fase
from agenda_videos.funcoes_auxiliares.calculo_datas_fase import ultimo_dia_util_ou_hoje
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
    'progresso_producao_video__quantidade_roteiros',
]


def listar_produtos_agenda_filtrados(busca=None, filtros=None, ordenar='titulo', data_referencia=None):
    filtros = filtros or {}
    hoje = ultimo_dia_util_ou_hoje(data_referencia or date.today())

    postagem_mais_recente = Postagem.objects.filter(produto=OuterRef('pk')).order_by('-criado_em')

    # * [EXPLICAÇÃO] → Base NÃO exige mais AndamentoAgenda (diferente da antiga
    #                  tela "Diários") — "Não Agendado"/"Pronto para Agendar"
    #                  ainda não têm esse registro, e precisam aparecer também.
    qs = Produto.objects.select_related(
        'andamento_agenda', 'andamento_agenda__fase_atual',
        'progresso_producao_video', 'roadmap_agenda',
    ).annotate(
        status_postagem_recente=Subquery(postagem_mais_recente.values('status')[:1]),
        # * [EXPLICAÇÃO] → 6 níveis (25/07, correção) — "Sem vídeo" não é só o
        #                  4º critério isolado, ele CRUZA com Urgente e Atrasado
        #                  (um Urgente que também não tem vídeo é mais crítico que
        #                  um Urgente comum). Case/When avalia em ordem e para no
        #                  1º que bater — por isso "Urgente + Sem vídeo" precisa
        #                  vir ANTES de "Urgente" sozinho, senão nunca seria
        #                  alcançado (Urgente sozinho já bateria primeiro).
        prioridade_ordenacao=Case(
            When(roadmap_agenda__urgente=True, roadmap_agenda__tem_video_reprovado=True, then=Value(1)),
            When(roadmap_agenda__urgente=True, then=Value(2)),
            When(
                andamento_agenda__isnull=False,
                andamento_agenda__concluido=False,
                andamento_agenda__fim_ocorrencia_atual__lt=hoje,
                roadmap_agenda__tem_video_reprovado=True,
                then=Value(3),
            ),
            When(
                andamento_agenda__isnull=False,
                andamento_agenda__concluido=False,
                andamento_agenda__fim_ocorrencia_atual__lt=hoje,
                then=Value(4),
            ),
            When(roadmap_agenda__tem_video_reprovado=True, then=Value(5)),
            default=Value(6),
            output_field=IntegerField(),
        ),
        # * [EXPLICAÇÃO] → Grupo intermediário (25/07), não critério — vem DEPOIS
        #                  da prioridade (Urgente/Atrasado/etc. continua vencendo
        #                  tudo) e ANTES do "Ordenar por". Diária → Semanal →
        #                  Mensal → (sem fase real: Não Agendado/Pronto p/
        #                  Agendar). "Otimizado" cai no grupo da última fase real
        #                  que ele passou (fase_atual preserva isso, por design).
        ordenacao_fase=Case(
            When(andamento_agenda__fase_atual__fase=Fase.DIARIA, then=Value(1)),
            When(andamento_agenda__fase_atual__fase=Fase.SEMANAL, then=Value(2)),
            When(andamento_agenda__fase_atual__fase=Fase.MENSAL, then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        ),
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
        qs = qs.filter(status_postagem_recente__in=filtros['status_postagem'])

    for campo in CAMPOS_FAIXA:
        qs = aplicar_filtro_faixa(qs, filtros, campo)

    campo_ordenacao = CAMPOS_ORDENACAO.get(ordenar.lstrip('-'), 'titulo')
    if ordenar.startswith('-'):
        campo_ordenacao = f'-{campo_ordenacao}'

    # * [EXPLICAÇÃO] → Prioridade primeiro, depois o grupo de fase
    #                  (Diária/Semanal/Mensal), e só então "Ordenar por" desempata
    #                  dentro de cada combinação — nunca embaralha os grupos entre si.
    return qs.order_by('prioridade_ordenacao', 'ordenacao_fase', campo_ordenacao)