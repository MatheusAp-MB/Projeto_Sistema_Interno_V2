# * [RESUMO] → Monta os dados de qualidade de 1 folha (MLB) para a
#              tela de detalhe, organizados em 4 zonas fixas:
#              A Fazer, Feitos, Não Aplicável, Novos Critérios.
#              Novos Critérios é independente do status (catalogado=False,
#              qualquer status) — critério que a API trouxe e ainda não
#              foi traduzido/formalizado no nosso seed.

from mercado_livre.models import VariacaoAnuncioMercadoLivre
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


def agrupar_por_grupo(lista):
    grupos = {}
    for item in lista:
        grupos.setdefault(item['grupo'], {'cor': item['cor_grupo'], 'criterios': []})
        grupos[item['grupo']]['criterios'].append(item)
    return [
        {
            'nome_grupo': nome,
            'cor': dados['cor'],
            'criterios': dados['criterios'],
            'col_span': min(len(dados['criterios']), 4),
        }
        for nome, dados in grupos.items()
    ]


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
            'permalink': anuncio.permalink
        
        }

    avaliacoes = qualidade.criterios.select_related('criterio').all()

    a_fazer = []
    feitos = []
    nao_aplicavel = []
    novos_criterios = []

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

        if not av.criterio.catalogado:
            novos_criterios.append(item)
        elif av.status == 'aprovado':
            feitos.append(item)
        elif av.status == 'nao_aplicavel':
            nao_aplicavel.append(item)
        else:
            a_fazer.append(item)

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

        'total_a_fazer': len(a_fazer),
        'total_feitos': len(feitos),
        'total_nao_aplicavel': len(nao_aplicavel),
        'total_novos_criterios': len(novos_criterios),
        'total_criterios': len(a_fazer) + len(feitos) + len(nao_aplicavel) + len(novos_criterios),

        'zona_a_fazer': agrupar_por_grupo(a_fazer),
        'zona_feitos': agrupar_por_grupo(feitos),
        'zona_nao_aplicavel': agrupar_por_grupo(nao_aplicavel),
        'zona_novos_criterios': agrupar_por_grupo(novos_criterios),

        'arco_vermelho': arcos['vermelho'],
        'arco_amarelo': arcos['amarelo'],
        'arco_verde': arcos['verde'],
        'ponteiro_x': ponteiro_x,
        'ponteiro_y': ponteiro_y,

        'resumo_a_fazer': a_fazer,
        'resumo_feitos': feitos,
        'resumo_nao_aplicavel': nao_aplicavel,
        'resumo_novos_criterios': novos_criterios,
        
    }