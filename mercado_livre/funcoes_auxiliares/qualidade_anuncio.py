# * [RESUMO] → Monta os dados de qualidade de 1 folha (Variação) para
#              a tela de detalhe. Organiza os 16 critérios em 3 grupos
#              (OK / Não se aplica / Falta fazer), na ordem certa para
#              cada contexto: resumo mostra OK→N/A→Falta (do mais
#              tranquilo pro mais urgente); detalhado mostra
#              Falta→N/A→OK (ordem de ação).

from mercado_livre.models import VariacaoAnuncioMercadoLivre, CriterioQualidade
from mercado_livre.funcoes_auxiliares.classificacao_catalogo import montar_arcos_termometro, calcular_ponteiro_termometro

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
            grupos.setdefault(item['grupo'], []).append(item)
        return [{'nome_grupo': nome, 'criterios': criterios} for nome, criterios in grupos.items()]


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