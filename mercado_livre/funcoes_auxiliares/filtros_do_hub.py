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
# * [EXPLICAÇÃO] → DOIS desenhos do painel convivem por enquanto (decisão do Matheus, 12/10/2026: "só nessa tela por enquanto"): o painel ANTIGO (cartões com listas, estrutura_parcial_filtros_painel.html), que o Hub de Anúncios
#                  ainda usa, e o painel em MENUS (estrutura_parcial_filtros_menus.html), só da Previsão de Ruptura. Os DOIS leem e escrevem o mesmo endereço (PARAMETROS_DO_FILTRO) e as opções saem do mesmo lugar (contexto_do_painel):
#                  o que muda é só o desenho. Quando o Hub de Anúncios (e o Hub de Fotos, que ainda tem uma cópia própria) passarem para os menus, o painel e o CSS antigos saem.

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

# Função Objetivo: A organização do painel em MENUS: os 3 grupos (chave, título, legenda) e, em cada grupo, os campos na ordem em que aparecem. É a única tabela dessa organização (o desenho mora no parcial dos menus).
# (chave de dentro, grupo, rótulo, texto do menu vazio, tem busca, gênero de "selecionado(s)": 'm' | 'f')
GRUPOS_DO_PAINEL = (
    ('identificacao', 'Identificação e anúncio', 'Defina os principais critérios do anúncio.'),
    ('comercial', 'Comercial e catálogo', 'Logística, estrutura comercial e catálogo.'),
    ('desempenho', 'Desempenho e integração', 'Estoque, desempenho e integração com outros sistemas.'),
)
CAMPOS_DO_PAINEL = (
    ('marcas', 'identificacao', 'Marca', 'Selecionar marca...', True, 'f'),
    ('status', 'identificacao', 'Situação do anúncio', 'Selecionar situação...', True, 'm'),
    ('tipos_anuncio', 'identificacao', 'Tipo de anúncio', 'Selecionar tipo de anúncio...', False, 'm'),
    ('tipos_logisticos', 'comercial', 'Logística', 'Selecionar logística...', True, 'f'),
    ('flex', 'comercial', 'Flex', 'Selecionar tipo de Flex...', False, 'm'),
    ('catalogos', 'comercial', 'Situação do catálogo', 'Selecionar situação do catálogo...', True, 'f'),
    ('desconto', 'comercial', 'Desconto', 'Selecionar desconto...', False, 'm'),
    ('estoque', 'desempenho', 'Estoque', 'Selecionar estoque...', False, 'm'),
    ('faixas_score', 'desempenho', 'Faixa de score', 'Selecionar faixa de score...', False, 'f'),
    ('situacoes_competicao', 'desempenho', 'Situação de competição', 'Selecionar situação...', True, 'f'),
    ('conexao_erp', 'desempenho', 'Conexão com ERP', 'Selecionar conexão com ERP...', False, 'f'),
)


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


# Função Objetivo: Os grupos do painel em MENUS prontos para o parcial: cada campo (menos os `escondidos`) com o rótulo, o texto do menu vazio, as opções (valor, texto, selo do registro único badges.py quando o filtro tem selo,
# e se está marcada) e quantas estão marcadas. `opcoes_por_chave` = {chave de dentro: [(valor, texto, selo ou None)]}, montado em contexto_do_painel (as MESMAS opções do painel antigo: uma fonte só). Grupo sem nenhum campo some.
def _montar_grupos(filtros, escondidos, opcoes_por_chave):
    parametros = dict(PARAMETROS_DO_FILTRO)
    grupos = []
    for chave_do_grupo, titulo, legenda in GRUPOS_DO_PAINEL:
        campos = []
        for chave, grupo, rotulo, vazio, com_busca, genero in CAMPOS_DO_PAINEL:
            if grupo != chave_do_grupo or chave in escondidos:
                continue
            marcados = set(filtros.get(chave) or [])
            opcoes = [{'valor': valor, 'texto': texto, 'selo': selo, 'marcada': valor in marcados} for valor, texto, selo in opcoes_por_chave[chave]]
            campos.append({'chave': chave, 'parametro': parametros[chave], 'rotulo': rotulo, 'vazio': vazio, 'com_busca': com_busca, 'genero': genero,
                           'opcoes': opcoes, 'n_marcadas': sum(1 for o in opcoes if o['marcada'])})
        if campos:
            grupos.append({'chave': chave_do_grupo, 'titulo': titulo, 'legenda': legenda, 'campos': campos})
    return grupos


# Função Objetivo: O que o painel de filtros precisa para ser desenhado (o painel antigo é o parcial estrutura_parcial_filtros_painel.html e os chips dele são estrutura_parcial_filtros_chips.html; o painel em MENUS é
# estrutura_parcial_filtros_menus.html e usa `grupos`): os filtros marcados,
# as opções de cada filtro (com os selos do registro único badges.py), os chips dos filtros ativos, os filtros que a tela esconde e o endereço do "Limpar filtros".
# * [EXPLICAÇÃO] → `so_logisticas_de_fora_do_full`: oferece só as logísticas de fora do Full (as do Hub menos o FULL, pelo dono da regra: logistica_do_anuncio.py). Usado no mundo Fora do Full da Previsão.
# * [EXPLICAÇÃO] → `em_menus`: monta também `grupos` (o painel em menus). Fica desligado para o Hub de Anúncios, que ainda usa o painel antigo (assim ele não paga a conta de montar o que não desenha).
def contexto_do_painel(filtros, url_limpar, escondidos=(), so_logisticas_de_fora_do_full=False, em_menus=False):
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

    marcas_disponiveis = Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca')
    opcoes_status = opcoes_com_badge(BADGES_STATUS)
    opcoes_tipo_anuncio = opcoes_com_badge(BADGES_TIPO_ANUNCIO)
    opcoes_catalogo = opcoes_com_badge(BADGES_CATALOGO)
    opcoes_situacao_competicao = CompeticaoCatalogo.StatusCompeticao.choices

    grupos = []
    if em_menus:
        # * [EXPLICAÇÃO] → Quem tem SELO (Situação, Tipo, Logística, Flex e Catálogo) mostra o selo do registro único (badges.py) nas opções e nas etiquetas; os outros filtros são texto simples (não têm selo próprio ainda).
        opcoes_por_chave = {
            'marcas': [(marca, marca, None) for marca in marcas_disponiveis],
            'status': [(o['valor'], o['label'], o) for o in opcoes_status],
            'tipos_anuncio': [(o['valor'], o['label'], o) for o in opcoes_tipo_anuncio],
            'tipos_logisticos': [(o['valor'], o['label'], o) for o in opcoes_logistica],
            'flex': [('sim', BADGE_FLEX_ATIVO['label'], BADGE_FLEX_ATIVO), ('nao', BADGE_FLEX_INATIVO['label'], BADGE_FLEX_INATIVO)],
            'catalogos': [(o['valor'], o['label'], o) for o in opcoes_catalogo],
            'desconto': [('com', 'Com desconto ativo', None), ('sem', 'Sem desconto', None)],
            'estoque': [('com', 'Com estoque', None), ('sem', 'Sem estoque', None)],
            'faixas_score': [('bom', 'Bom', None), ('medio', 'Médio', None), ('ruim', 'Ruim', None), ('sem_dados', 'Sem dados', None)],
            'situacoes_competicao': [(valor, texto, None) for valor, texto in opcoes_situacao_competicao],
            'conexao_erp': [('com', 'Com conexão ERP', None), ('sem', 'Sem conexão ERP', None)],
        }
        grupos = _montar_grupos(filtros, escondidos, opcoes_por_chave)

    return {
        'filtros': filtros,
        'tem_filtro_ativo': tem_filtro_ativo(filtros),
        'escondidos': list(escondidos),
        'url_limpar': url_limpar,
        'chips_ativos': chips_ativos,
        'grupos': grupos,
        'marcas_disponiveis': marcas_disponiveis,
        'opcoes_status': opcoes_status,
        'opcoes_tipo_anuncio': opcoes_tipo_anuncio,
        'opcoes_logistica': opcoes_logistica,
        'opcoes_catalogo': opcoes_catalogo,
        'opcoes_situacao_competicao': opcoes_situacao_competicao,
        'badge_flex_ativo': BADGE_FLEX_ATIVO,
        'badge_flex_inativo': BADGE_FLEX_INATIVO,
    }
