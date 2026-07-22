# * [RESUMO] → Filtro, ordenação e paginação da tela de Resumo de
#              Critérios. Mesma arquitetura de listar_skus_filtrados
#              (Hub), sem cascata Base↔Catálogo.

from django.db.models import Q
from django.db.models.functions import Trim
from mercado_livre.models import (
    VariacaoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, QualidadeAnuncioCriterio,
)


# Função Objetivo: Lê busca/filtros/ordenação do GET — usada pela tela e pela
# exportação, pra nunca duplicar essa leitura em 2 lugares.
def ler_filtros_resumo_criterios(request, criterios):
    busca = request.GET.get('busca', '').strip()

    ordenar = request.GET.get('ordenar', 'sku')
    if ordenar.lstrip('-') not in CAMPOS_ORDENACAO:
        ordenar = 'sku'

    criterios_grid_filtro = {}
    for c in criterios:
        valores = request.GET.getlist(f'crit_{c.rule_key}')
        if valores:
            criterios_grid_filtro[c.rule_key] = valores

    filtros = {
        'marcas': request.GET.getlist('marca'),
        'status': request.GET.getlist('status'),
        'tipos_anuncio': request.GET.getlist('tipo_anuncio'),
        'tipos_logisticos': request.GET.getlist('logistica'),
        'catalogos': request.GET.getlist('catalogo'),
        'flex': request.GET.getlist('flex'),
        'criterios_grid': criterios_grid_filtro,
    }

    return busca, filtros, ordenar

# * [EXPLICAÇÃO] → Única fonte de verdade dos campos ordenáveis — usada
#                  tanto pra montar os links de cabeçalho quanto pra
#                  validar o parâmetro "ordenar" (nunca confiar em input
#                  cru do usuário direto num order_by).
CAMPOS_ORDENACAO = {
    'sku': 'produto__sku',
    'mlb': 'anuncio__mlb',
    'marca': 'produto__marca',
    'titulo': 'anuncio__titulo_anuncio',
    'status': 'anuncio__tipo_de_anuncio__status',
    'tipo_anuncio': 'anuncio__tipo_de_anuncio__tipo_anuncio',
    'tipo_logistico': 'anuncio__tipo_de_anuncio__tipo_logistico',
    'flex': 'anuncio__tipo_de_anuncio__flex',
    'catalogo': 'anuncio__tipo_de_anuncio__classificacao_catalogo',
    'score': 'qualidade__score',
    'nivel': 'qualidade__nivel',
}


def listar_variacoes_resumo_filtradas(busca=None, filtros=None, ordenar='sku'):
    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo
    filtros = filtros or {}

    qs = VariacaoAnuncioMercadoLivre.objects.filter(
        anuncio__tipo_de_anuncio__classificacao_catalogo__in=[Classificacao.SIMPLES, Classificacao.BASE]
    ).exclude(produto__isnull=True)

    if busca:
        termos = busca.split()
        for termo in termos:
            qs = qs.filter(
                Q(produto__sku__icontains=termo) |
                Q(produto__marca__icontains=termo) |
                Q(anuncio__mlb__icontains=termo) |
                Q(anuncio__titulo_anuncio__icontains=termo)
            )

    if filtros.get('marcas'):
        qs = qs.filter(produto__marca__in=filtros['marcas'])

    if filtros.get('status'):
        qs = qs.filter(anuncio__tipo_de_anuncio__status__in=filtros['status'])

    if filtros.get('tipos_anuncio'):
        qs = qs.filter(anuncio__tipo_de_anuncio__tipo_anuncio__in=filtros['tipos_anuncio'])

    if filtros.get('tipos_logisticos'):
        qs = qs.filter(anuncio__tipo_de_anuncio__tipo_logistico__in=filtros['tipos_logisticos'])

    if filtros.get('catalogos'):
        qs = qs.filter(anuncio__tipo_de_anuncio__classificacao_catalogo__in=filtros['catalogos'])

    valores_flex = filtros.get('flex') or []
    if len(valores_flex) == 1:
        qs = qs.filter(anuncio__tipo_de_anuncio__flex=(valores_flex[0] == 'sim'))

    # * [EXPLICAÇÃO] → Filtro em GRADE: 1 ou mais critérios ao mesmo tempo,
    #                  cada um com 1+ resultados marcados. Cada rule_key
    #                  vira um .filter() SEPARADO (não um só Q composto) —
    #                  isso é proposital: cada .filter() gera um JOIN
    #                  independente, então "Frete Grátis=NÃO E
    #                  Estoque=Não calculado" exige 2 avaliações
    #                  diferentes batendo, não a mesma linha satisfazendo
    #                  as duas condições ao mesmo tempo (o que seria
    #                  logicamente impossível, já que são critérios
    #                  diferentes).
    criterios_grid = filtros.get('criterios_grid') or {}
    for rule_key, resultados_selecionados in criterios_grid.items():
        if not resultados_selecionados:
            continue

        condicao = Q()
        resultados_reais = [r for r in resultados_selecionados if r != 'nao_calculado']

        if resultados_reais:
            condicao |= Q(
                qualidade__criterios__criterio__rule_key=rule_key,
                qualidade__criterios__status__in=resultados_reais,
            )

        if 'nao_calculado' in resultados_selecionados:
            ids_com_avaliacao = QualidadeAnuncioCriterio.objects.filter(
                criterio__rule_key=rule_key
            ).values_list('qualidade__variacao_id', flat=True)
            condicao |= ~Q(id__in=ids_com_avaliacao)

        qs = qs.filter(condicao)

    # * [EXPLICAÇÃO] → Todo campo de TEXTO pode ter sujeira vinda bruta da
    #                  API (espaços nas pontas/meio) — dado nunca é
    #                  "corrigido" no banco (ver princípio do projeto).
    #                  O Trim() aqui existe só pra ordenação fazer sentido
    #                  pro usuário; o valor exibido e armazenado continua
    #                  intacto. score e flex ficam de fora por não serem
    #                  texto (Trim quebraria a query nesses campos).
    CAMPOS_TEXTO = {'sku', 'mlb', 'marca', 'titulo', 'status', 'tipo_anuncio', 'tipo_logistico', 'catalogo', 'nivel'}

    chave = ordenar.lstrip('-')
    descendente = ordenar.startswith('-')
    campo_orm = CAMPOS_ORDENACAO.get(chave, 'produto__sku')

    if chave in CAMPOS_TEXTO:
        expressao = Trim(campo_orm)
        ordenacao = expressao.desc() if descendente else expressao.asc()
    else:
        ordenacao = f'-{campo_orm}' if descendente else campo_orm

    return qs.select_related(
        'produto', 'anuncio', 'anuncio__tipo_de_anuncio', 'qualidade'
    ).distinct().order_by(ordenacao)