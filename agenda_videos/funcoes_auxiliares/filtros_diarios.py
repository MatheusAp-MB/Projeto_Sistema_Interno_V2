# agenda_videos/funcoes_auxiliares/filtros_diarios.py

# * [RESUMO] → Busca, filtros e ordenação da tela "Diários". Mesma arquitetura já validada
#              em Produtos/Hub de Anúncios: tudo resolvido no servidor, sem client-side.

from django.db.models import Q, OuterRef, Subquery
from produtos.models import Produto
from agenda_videos.models import Fase, Postagem
from core.funcoes_auxiliares.filtros_genericos import aplicar_filtro_faixa

# * [EXPLICAÇÃO] → Única fonte de verdade dos campos ordenáveis — nunca usar o valor
#                  de "ordenar" direto num order_by() sem passar por esse whitelist.
CAMPOS_ORDENACAO = {
    'titulo': 'titulo', 'marca': 'marca', 'estoque': 'estoque',
    'ocorrencia_atual': 'andamento_agenda__ocorrencia_atual',
    'inicio_fase': 'andamento_agenda__inicio_fase',
    'fim_fase': 'andamento_agenda__fim_fase',
    'quantidade_roteiros': 'progresso_producao_video__quantidade_roteiros',
}

# * [EXPLICAÇÃO] → Campos numéricos/data com filtro de faixa (mín/máx).
CAMPOS_FAIXA = [
    'andamento_agenda__ocorrencia_atual',
    'andamento_agenda__inicio_fase',
    'andamento_agenda__fim_fase',
    'progresso_producao_video__quantidade_roteiros',
]


def listar_produtos_diarios_filtrados(busca=None, filtros=None, ordenar='titulo'):
    filtros = filtros or {}

    # * [EXPLICAÇÃO] → Status da Postagem mais recente — via Subquery/OuterRef, numa
    #                  única query (nunca 1 query por produto em loop). Postagem é
    #                  histórico (N por produto); pega sempre a última por criado_em.
    postagem_mais_recente = Postagem.objects.filter(
        produto=OuterRef('pk')
    ).order_by('-criado_em')

    qs = Produto.objects.filter(
        andamento_agenda__fase_atual__fase=Fase.DIARIA,
        andamento_agenda__concluido=False,
    ).select_related(
        'andamento_agenda', 'andamento_agenda__fase_atual', 'progresso_producao_video',
    ).annotate(
        status_postagem_recente=Subquery(postagem_mais_recente.values('status')[:1]),
    )

    if busca:
        termos = busca.split()
        for termo in termos:
            qs = qs.filter(
                Q(titulo__icontains=termo) | Q(ean__icontains=termo) |
                Q(sku__icontains=termo) | Q(cod_fabricante__icontains=termo)
            )

    if filtros.get('marcas'):
        qs = qs.filter(marca__in=filtros['marcas'])

    if filtros.get('status_manual'):
        qs = qs.filter(andamento_agenda__status_manual__in=filtros['status_manual'])

    if filtros.get('urgente'):
        qs = qs.filter(andamento_agenda__urgente__in=[v == 'sim' for v in filtros['urgente']])

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

    return qs.order_by(campo_ordenacao)