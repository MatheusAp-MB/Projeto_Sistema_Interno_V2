# mercado_livre/funcoes_auxiliares/filtros_do_hub.py
#
# Função Objetivo: O DONO ÚNICO dos filtros do Hub de Anúncios (o painel "Filtros"): quais são, como se chamam no endereço, como se leem da query string, como voltam para o endereço e o que o painel
# precisa para ser desenhado (as opções de cada filtro e os chips dos filtros ativos). O Hub de Anúncios e a Previsão de Ruptura de estoque usam estas funções e o MESMO painel
# (templates/mercado_livre/parciais/estrutura_parcial_filtros_painel.html): nenhuma tela lê "?marca=..." nem monta as opções por conta própria. Quem decide QUEM PASSA em cada filtro continua sendo só o Hub
# (classificacao_catalogo.py: listar_skus_filtrados no Hub, mlbs_visiveis_com_filtros na Previsão).
#
# * [EXPLICAÇÃO] → Cada filtro tem uma CHAVE de dentro (a que classificacao_catalogo.py lê: "tipos_logisticos") e um PARÂMETRO do endereço (o que a pessoa vê: "logistica"). PARAMETROS_DO_FILTRO é a única
#                  tabela das duas; um filtro novo nasce aqui, no painel (estrutura_parcial_filtros_painel.html) e em classificacao_catalogo.py, e nunca repetido por tela.
# * [EXPLICAÇÃO] → `ignorar` (em ler_filtros) e `escondidos` (no painel) existem para uma tela que NÃO usa um filtro (ele volta vazio e o cartão some do painel), em vez de a tela copiar o painel. Hoje: a Previsão
#                  de Ruptura ignora "estoque" (o parâmetro `estoque` dela já é o estoque digitado no detalhe, e "estoque" tem outro sentido lá) e, no mundo Envios Full, "tipos_logisticos" (todo anúncio de lá é FULL).

from mercado_livre.funcoes_auxiliares.logistica_do_anuncio import logistica_e_de_fora_do_full

# (chave de dentro, parâmetro no endereço), na ordem em que aparecem no endereço e nos chips
PARAMETROS_DO_FILTRO = (
    ('marcas', 'marca'),
    ('status', 'status'),
    ('tipos_anuncio', 'tipo_anuncio'),
    ('tipos_logisticos', 'logistica'),
    ('catalogos', 'catalogo'),
    ('flex', 'flex'),
    ('estoque', 'estoque'),
    ('desconto', 'desconto'),
    ('conexao_erp', 'conexao_erp'),
    ('faixas_score', 'score'),
    ('situacoes_competicao', 'competicao'),
)
CHAVES_DO_FILTRO = tuple(chave for chave, _ in PARAMETROS_DO_FILTRO)


def _valores(parametros, nome):
    if hasattr(parametros, 'getlist'):   # QueryDict (request.GET)
        return list(parametros.getlist(nome))
    valor = parametros.get(nome)
    if valor in (None, ''):
        return []
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


# Função Objetivo: Lê os filtros do Hub da query string (request.GET): {chave: [valores]}. Todas as chaves voltam (vazias quando não vieram no endereço); as de `ignorar` voltam sempre vazias.
def ler_filtros(parametros, ignorar=()):
    return {chave: ([] if chave in ignorar else _valores(parametros, parametro)) for chave, parametro in PARAMETROS_DO_FILTRO}


# Função Objetivo: Os filtros no formato do endereço: {parâmetro: [valores]}, só os que têm valor. (Quem monta o endereço precisa aceitar listas: url_da_tela usa doseq.)
def para_url(filtros):
    return {parametro: list(filtros[chave]) for chave, parametro in PARAMETROS_DO_FILTRO if filtros.get(chave)}


# Função Objetivo: Há algum filtro do Hub ativo?
def tem_filtro_ativo(filtros):
    return any((filtros or {}).get(chave) for chave in CHAVES_DO_FILTRO)


# Função Objetivo: O que o painel de filtros precisa para ser desenhado (o painel é o parcial estrutura_parcial_filtros_painel.html, os chips são estrutura_parcial_filtros_chips.html): os filtros marcados,
# as opções de cada filtro (com os selos do registro único badges.py), os chips dos filtros ativos, os filtros que a tela esconde e o endereço do "Limpar filtros".
# * [EXPLICAÇÃO] → `so_logisticas_de_fora_do_full`: oferece só as logísticas de fora do Full (as do Hub menos o FULL, pelo dono da regra: logistica_do_anuncio.py). Usado no mundo Fora do Full da Previsão.
def contexto_do_painel(filtros, url_limpar, escondidos=(), so_logisticas_de_fora_do_full=False):
    from mercado_livre.funcoes_auxiliares.badges import (
        BADGES_STATUS, BADGES_TIPO_ANUNCIO, BADGES_LOGISTICA, BADGES_CATALOGO,
        BADGE_FLEX_ATIVO, BADGE_FLEX_INATIVO,
        badge_de, badge_flex, opcoes_com_badge,
    )
    from mercado_livre.models import CompeticaoCatalogo
    from produtos.models import Produto

    mapa_competicao = dict(CompeticaoCatalogo.StatusCompeticao.choices)
    mapa_estoque = {'com': 'Com estoque', 'sem': 'Sem estoque'}
    mapa_desconto = {'com': 'Com desconto', 'sem': 'Sem desconto'}
    mapa_conexao_erp = {'com': 'Com conexão ERP', 'sem': 'Sem conexão ERP'}
    mapa_score = {'ruim': 'Ruim', 'medio': 'Médio', 'bom': 'Bom', 'sem_dados': 'Sem dados'}

    # * [EXPLICAÇÃO] → Status/Tipo/Logística/Flex/Catálogo usam o mesmo
    #                  registro de badges do Resumo de Critérios agora
    #                  (badges.py). Estoque/Score/Competição ficam de
    #                  fora desse sistema — são conceitos diferentes,
    #                  sem badge própria ainda.
    chips_ativos = (
        [{'label': marca, 'classe': None, 'icone': None} for marca in filtros['marcas']] +
        [badge_de(BADGES_STATUS, v) for v in filtros['status']] +
        [badge_de(BADGES_TIPO_ANUNCIO, v) for v in filtros['tipos_anuncio']] +
        [badge_de(BADGES_LOGISTICA, v) for v in filtros['tipos_logisticos']] +
        [badge_de(BADGES_CATALOGO, v) for v in filtros['catalogos']] +
        [badge_flex(v == 'sim') for v in filtros['flex']] +
        [{'label': mapa_estoque.get(v, v), 'classe': None, 'icone': None} for v in filtros['estoque']] +
        [{'label': mapa_desconto.get(v, v), 'classe': None, 'icone': None} for v in filtros['desconto']] +
        [{'label': mapa_conexao_erp.get(v, v), 'classe': None, 'icone': None} for v in filtros['conexao_erp']] +
        [{'label': mapa_score.get(v, v), 'classe': None, 'icone': None} for v in filtros['faixas_score']] +
        [{'label': mapa_competicao.get(v, v), 'classe': None, 'icone': None} for v in filtros['situacoes_competicao']]
    )

    opcoes_logistica = opcoes_com_badge(BADGES_LOGISTICA)
    if so_logisticas_de_fora_do_full:
        opcoes_logistica = [o for o in opcoes_logistica if logistica_e_de_fora_do_full(o['valor'])]

    return {
        'filtros': filtros,
        'tem_filtro_ativo': tem_filtro_ativo(filtros),
        'escondidos': list(escondidos),
        'url_limpar': url_limpar,
        'chips_ativos': chips_ativos,
        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True)
            .exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'opcoes_status': opcoes_com_badge(BADGES_STATUS),
        'opcoes_tipo_anuncio': opcoes_com_badge(BADGES_TIPO_ANUNCIO),
        'opcoes_logistica': opcoes_logistica,
        'opcoes_catalogo': opcoes_com_badge(BADGES_CATALOGO),
        'opcoes_situacao_competicao': CompeticaoCatalogo.StatusCompeticao.choices,
        'badge_flex_ativo': BADGE_FLEX_ATIVO,
        'badge_flex_inativo': BADGE_FLEX_INATIVO,
    }
