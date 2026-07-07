# * [RESUMO] → Monta os dados de qualidade de 1 folha (Variação) para
#              a tela de detalhe. Organiza os 16 critérios em 3 grupos
#              (OK / Não se aplica / Falta fazer), na ordem certa para
#              cada contexto: resumo mostra OK→N/A→Falta (do mais
#              tranquilo pro mais urgente); detalhado mostra
#              Falta→N/A→OK (ordem de ação).

from mercado_livre.models import VariacaoAnuncioMercadoLivre, CriterioQualidade
from mercado_livre.funcoes_auxiliares.classificacao_catalogo import montar_arcos_termometro, calcular_ponteiro_termometro


GRUPO_CORES = {
    'UP_SHORTS': '7030A0',
    'UP_PICTURES': '17375E',
    'UP_TITLE': '375623',
    'UP_GTIN': 'C00000',
    'UP_TECHNICAL_SPECIFICATIONS_MAIN': 'E26B0A',
    'UP_STOCK_DEPOSITO': '7B3F00',
    'UP_STOCK_AVAILABILITY_TIME': '4F5B66',
    'UP_FREE_SHIPPING': '1F4E79',
    'UP_FINANCING': '7B2C2C',
    'UP_PROMOTIONS': '1D6B5A',
    'UP_PRICE': '7F6000',
    'UP_ME_FLEX_ITEM_OPTIN': '2E4057',
    'UP_SIZE_CHART': '833C00',
    'UP_CATALOG': '1F3864',
    'DESCONHECIDO': '595959',
}


def pastel(hex_color, fator=0.85):
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r = int(r + (255 - r) * fator)
    g = int(g + (255 - g) * fator)
    b = int(b + (255 - b) * fator)
    return f'{r:02x}{g:02x}{b:02x}'



def montar_qualidade_da_folha(mlb):
    variacao = VariacaoAnuncioMercadoLivre.objects.filter(
        anuncio__mlb=mlb
    ).select_related('anuncio', 'produto', 'qualidade').first()

    if not variacao:
        return {'encontrado': False}

    anuncio = variacao.anuncio
    qualidade = getattr(variacao, 'qualidade', None)

    if not qualidade:
        return {
            'encontrado': True,
            'mlb': anuncio.mlb,
            'titulo': anuncio.titulo_anuncio,
            'sku': variacao.sku_ml,
            'imagem_url': variacao.imagem_principal_url or variacao.thumbnail_url,
            'score': None,
            'nivel': None,
            'sem_dado_qualidade': True,
            'resumo_ok': [], 'resumo_na': [], 'resumo_falta': [],
            'detalhado_falta': [], 'detalhado_na': [], 'detalhado_ok': [],
        }

    Status = CriterioQualidade  # apenas para leitura mais clara abaixo
    avaliacoes = qualidade.criterios.select_related('criterio').all()

    ok = []
    na = []
    falta = []

    for av in avaliacoes:
        cor_grupo = GRUPO_CORES.get(av.criterio.grupo, '595959')

        item = {
            'rule_key': av.criterio.rule_key,
            'grupo': av.criterio.get_grupo_display(),
            'nome': av.criterio.nome,
            'pergunta': av.criterio.pergunta,
            'como_aprovar': av.criterio.como_aprovar,
            'link': av.link_correcao,
            'catalogado': av.criterio.catalogado,
            'score': av.score,
            'calculado_em': av.calculado_em,
            'cor_grupo': cor_grupo,
            'cor_grupo_pastel': pastel(cor_grupo),
        }

        if av.status == 'aprovado':
            ok.append(item)
        elif av.status == 'nao_aplicavel':
            na.append(item)
        else:
            falta.append(item)

    def agrupar_por_grupo(lista):
        grupos = {}
        for item in lista:
            grupos.setdefault(item['grupo'], {'cor': item['cor_grupo'], 'criterios': []})
            grupos[item['grupo']]['criterios'].append(item)
        return [
            {'nome_grupo': nome, 'cor': dados['cor'], 'criterios': dados['criterios']}
            for nome, dados in grupos.items()
        ]


    arcos = montar_arcos_termometro()
    ponteiro_x, ponteiro_y = calcular_ponteiro_termometro(qualidade.score or 0)

    return {
        'encontrado': True,
        'mlb': anuncio.mlb,
        'titulo': anuncio.titulo_anuncio,
        'sku': variacao.sku_ml,
        'imagem_url': variacao.imagem_principal_url or variacao.thumbnail_url,
        'permalink': anuncio.permalink,
        'score': qualidade.score,
        'nivel': qualidade.nivel,
        'sem_dado_qualidade': False,
        'arco_vermelho': arcos['vermelho'],
        'arco_amarelo': arcos['amarelo'],
        'arco_verde': arcos['verde'],
        'ponteiro_x': ponteiro_x,
        'ponteiro_y': ponteiro_y,

        'total_ok': len(ok),
        'total_na': len(na),
        'total_falta': len(falta),
        'total_criterios': len(ok) + len(na) + len(falta),

        'resumo_ok': ok,
        'resumo_na': na,
        'resumo_falta': falta,

        'detalhado_falta': agrupar_por_grupo(falta),
        'detalhado_na': agrupar_por_grupo(na),
        'detalhado_ok': agrupar_por_grupo(ok),
    }