# mercado_livre/funcoes_auxiliares/caracteristicas_ml.py
#
# Regras da tela "Características dos anúncios" (Mercado Livre). TUDO aqui
# lê só do BANCO — nenhuma função deste arquivo chama a API do ML (regra do
# Matheus: a API só é consultada pelos 2 botões da tela, via
# integracao_mercado_livre.servicos.sincronizar_caracteristicas_ml).
#
# O que este arquivo faz:
#   - define QUAIS anúncios entram na tela (a mesma regra do serviço que lê
#     a API, para as duas pontas nunca discordarem);
#   - monta a lista de produtos (1 linha por SKU, sem os cards);
#   - monta a "ficha" de 1 produto: a tabela de anúncios e os cards, juntando
#     o que cada categoria pede (card) com o que cada anúncio tem hoje no ML.
#
# REGRAS DE FUSÃO (o produto tem anúncios em categorias diferentes, mas o
# valor é um só): obrigatório = o nível mais exigente; lista fechada = só
# valem as opções comuns a todas as categorias (por id); texto = o menor
# limite de caracteres; unidades = as comuns. Divergências viram aviso na
# linha "Regra" do card. Portadas de
# scripts_exploracao_ML/gerar_planilha_llm_inventario.py (fundir_metadados).

from collections import Counter, defaultdict

from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

# * [EXPLICAÇÃO] → Status do anúncio (no banco) que entram na tela e na
#                  leitura. Anúncio encerrado (closed) não tem o que preencher.
STATUS_ACEITOS = {'active', 'paused'}

# * [EXPLICAÇÃO] → Campos que NÃO são característica do produto e não devem
#                  aparecer no card: ids técnicos do sistema, tipo "guia de
#                  tamanhos" e as etiquetas read_only (somente leitura),
#                  fixed (valor fixo da categoria) e inferred (o ML deduz).
CAMPOS_DE_SISTEMA = {'APGID'}
TIPOS_DE_SISTEMA = {'grid_row_id'}
TAGS_QUE_EXCLUEM = ('read_only', 'fixed', 'inferred')

# * [EXPLICAÇÃO] → Campo com a etiqueta hidden NUNCA entra (regra do Matheus,
#                  15/10/2026): o ML não o mostra ao vendedor. Nem aparece na
#                  lista de "campos que o ML pede mas não aparecem aqui".
#                  A leitura da categoria já não grava esses campos; este
#                  filtro só cobre linhas gravadas antes dessa regra.
TAG_OCULTO = 'hidden'

# * [EXPLICAÇÃO] → A ficha do ML tem grupos de campos (MAIN = "Características
#                  principais", OTHER = "Outros"...). A tela mostra uma seção
#                  por grupo, o principal primeiro. Linha de categoria
#                  gravada sem grupo (antes de o sistema guardá-lo) só podia
#                  ser do MAIN.
GRUPO_PRINCIPAL = 'MAIN'
ROTULO_GRUPO_PRINCIPAL = 'Características principais'

# * [EXPLICAÇÃO] → A marca vem do cadastro do produto (ERP) e não se edita
#                  aqui (mockup aprovado). O card mostra o valor do ERP e
#                  compara com o que os anúncios têm no ML.
ATRIBUTO_MARCA = 'BRAND'

NIVEL_OBRIGATORIEDADE = {'Não': 0, 'Condicional': 1, 'Sim': 2}

LIMITE_OPCOES_EXIBIDAS = 200

# * [EXPLICAÇÃO] → Nomes que, quando são as DUAS únicas opções de uma lista,
#                  fazem o card mostrar os botões "Sim" / "Não" no lugar de
#                  um select (o envio continua sendo pelo id da opção).
NOMES_SIM_NAO = {'sim', 'não', 'nao'}

# * [EXPLICAÇÃO] → O ML devolve value_id "-1" (e value_name vazio) quando o
#                  campo está marcado como "N/A" (não se aplica).
VALOR_ID_NA = '-1'

ROTULO_STATUS_FALLBACK = {
    'active': 'Ativo', 'paused': 'Pausado', 'closed': 'Encerrado',
    'under_review': 'Em revisão', 'payment_required': 'Débito pendente',
    'not_yet_active': 'Aguardando ativação',
}


# ─── QUAIS ANÚNCIOS ENTRAM ──────────────────────────────────────────────

# Função Objetivo: Queryset dos anúncios que entram na tela e na leitura da
# API: ligados a um Produto do ERP (alguma variação com produto), fora os
# "fósseis" de migração e fora os anúncios de catálogo, só status active/
# paused no banco (anúncio sem tipo também entra). skus=None = todos; lista
# de SKUs = só os anúncios desses produtos. É a ÚNICA definição dessa regra:
# o serviço de leitura da API usa esta mesma função.
def consultar_anuncios_elegiveis(skus=None):
    from mercado_livre.models import AnuncioMercadoLivre, TipoDeAnuncioMercadoLivre

    classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo
    if skus is None:
        consulta = AnuncioMercadoLivre.objects.filter(variacoes__produto__isnull=False)
    else:
        consulta = AnuncioMercadoLivre.objects.filter(variacoes__produto__sku__in=list(skus))

    return (
        consulta
        .exclude(eh_fossil_migracao=True)
        .exclude(tipo_de_anuncio__classificacao_catalogo=classificacao.CATALOGO)
        .filter(Q(tipo_de_anuncio__status__in=STATUS_ACEITOS) | Q(tipo_de_anuncio__isnull=True))
        .distinct()
    )


# ─── LISTA DE PRODUTOS ──────────────────────────────────────────────────

# Função Objetivo: Para cada SKU, junta o que o banco sabe da leitura dos
# anúncios: quais são, quais já foram lidos, em que categorias estão e
# quando foi a leitura mais recente. skus=None = todos os produtos.
def _agregar_leituras(skus=None):
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    filtro_produto = {'produto__isnull': False} if skus is None else {'produto_id__in': list(skus)}
    linhas = (
        VariacaoAnuncioMercadoLivre.objects
        .filter(anuncio__in=consultar_anuncios_elegiveis(skus), **filtro_produto)
        .values_list(
            'produto_id', 'anuncio_id', 'anuncio__mlb', 'anuncio__atributos_ml_lido_em',
            'anuncio__atributos_ml_categoria_id', 'categoria_id',
        )
    )

    por_sku = {}
    for sku, anuncio_id, mlb, lido_em, categoria_lida, categoria_banco in linhas:
        dados = por_sku.setdefault(sku, {
            'anuncios': set(), 'lidos': set(), 'mlbs': set(), 'categorias': set(), 'ultima_leitura': None,
        })
        dados['anuncios'].add(anuncio_id)
        dados['mlbs'].add(mlb)
        if lido_em is not None:
            dados['lidos'].add(anuncio_id)
            if dados['ultima_leitura'] is None or lido_em > dados['ultima_leitura']:
                dados['ultima_leitura'] = lido_em
        categoria = categoria_lida or categoria_banco
        if categoria:
            dados['categorias'].add(categoria)
    return por_sku


# * [EXPLICAÇÃO] → Como cada estado de leitura de um produto aparece na lista
#                  (texto e classe da pílula). Fica aqui, e não no HTML/JS,
#                  para o texto ser definido num lugar só: a página e o
#                  "Atualizar" (que devolve o resumo novo) usam o mesmo.
ESTADOS_LEITURA = {
    'nunca': ('Nunca lido', 'car-pilula--neutra'),
    'parcial': ('Lido em parte', 'car-pilula--alerta'),
    'completa': ('Lido', 'car-pilula--ok'),
}


def _estado_da_leitura(n_anuncios, n_lidos):
    if n_lidos == 0:
        return 'nunca'
    if n_lidos >= n_anuncios:
        return 'completa'
    return 'parcial'


def formatar_data_hora(valor):
    if valor is None:
        return ''
    return timezone.localtime(valor).strftime('%d/%m %H:%M')


# Função Objetivo: Resumo de 1 produto para a linha da lista — também usado
# pelo "Atualizar" para devolver os números novos sem recarregar a página.
def resumir_produto(sku):
    dados = _agregar_leituras([sku]).get(sku)
    if dados is None:
        return {
            'n_anuncios': 0, 'n_lidos': 0, 'n_categorias': 0, 'estado': 'nunca',
            'estado_rotulo': ESTADOS_LEITURA['nunca'][0], 'estado_classe': ESTADOS_LEITURA['nunca'][1],
            'ultima_leitura': '',
        }
    n_anuncios, n_lidos = len(dados['anuncios']), len(dados['lidos'])
    estado = _estado_da_leitura(n_anuncios, n_lidos)
    return {
        'n_anuncios': n_anuncios,
        'n_lidos': n_lidos,
        'n_categorias': len(dados['categorias']),
        'estado': estado,
        'estado_rotulo': ESTADOS_LEITURA[estado][0],
        'estado_classe': ESTADOS_LEITURA[estado][1],
        'ultima_leitura': formatar_data_hora(dados['ultima_leitura']),
    }


# Função Objetivo: Lista de produtos da tela (1 linha por SKU, sem os
# cards). Filtros: busca (SKU, EAN, título, marca ou MLB), marca e estado da
# leitura (nunca / parcial / completa). Devolve também as contagens por
# estado (já com busca e marca aplicadas, para os botões de filtro) e as
# marcas disponíveis.
def listar_produtos(busca='', marca='', leitura=''):
    from produtos.models import Produto

    por_sku = _agregar_leituras()
    produtos_banco = {
        p['sku']: p
        for p in Produto.objects.filter(sku__in=list(por_sku)).values('id', 'sku', 'titulo', 'marca', 'ean', 'imagem_url')
    }

    todos = []
    for sku, dados in por_sku.items():
        produto = produtos_banco.get(sku)
        if produto is None:
            continue
        n_anuncios, n_lidos = len(dados['anuncios']), len(dados['lidos'])
        estado = _estado_da_leitura(n_anuncios, n_lidos)
        todos.append({
            'sku': sku,
            'produto_id': produto['id'],
            'titulo': produto['titulo'] or '',
            'marca': produto['marca'] or '',
            'ean': produto['ean'] or '',
            'imagem_url': produto['imagem_url'] or '',
            'n_anuncios': n_anuncios,
            'n_lidos': n_lidos,
            'n_categorias': len(dados['categorias']),
            'estado': estado,
            'estado_rotulo': ESTADOS_LEITURA[estado][0],
            'estado_classe': ESTADOS_LEITURA[estado][1],
            'ultima_leitura': dados['ultima_leitura'],
            'mlbs': dados['mlbs'],
        })
    todos.sort(key=lambda p: (p['marca'].lower(), p['sku']))

    marcas = sorted({p['marca'] for p in todos if p['marca']}, key=str.lower)

    termo = (busca or '').strip().lower()
    filtrados = [
        p for p in todos
        if (not marca or p['marca'] == marca)
        and (
            not termo
            or termo in p['sku'].lower()
            or termo in p['ean'].lower()
            or termo in p['titulo'].lower()
            or termo in p['marca'].lower()
            or any(termo in (m or '').lower() for m in p['mlbs'])
        )
    ]

    contagens = {
        'todos': len(filtrados),
        'nunca': sum(1 for p in filtrados if p['estado'] == 'nunca'),
        'parcial': sum(1 for p in filtrados if p['estado'] == 'parcial'),
        'completa': sum(1 for p in filtrados if p['estado'] == 'completa'),
    }
    if leitura in ('nunca', 'parcial', 'completa'):
        filtrados = [p for p in filtrados if p['estado'] == leitura]

    return {'produtos': filtrados, 'contagens': contagens, 'marcas': marcas}


# Função Objetivo: Números para a janela de confirmação da varredura
# completa: quantos anúncios, quantas categorias (as já conhecidas pelo
# banco) e quantas chamadas à API isso deve custar (1 por anúncio + 2 por
# categoria). É estimativa — a categoria real vem do ML na hora da leitura.
def estimar_varredura():
    from mercado_livre.models import VariacaoAnuncioMercadoLivre

    elegiveis = consultar_anuncios_elegiveis()
    n_anuncios = elegiveis.count()
    n_categorias = (
        VariacaoAnuncioMercadoLivre.objects
        .filter(anuncio__in=elegiveis, produto__isnull=False, categoria__isnull=False)
        .values('categoria_id').distinct().count()
    )
    return {
        'n_anuncios': n_anuncios,
        'n_categorias': n_categorias,
        'n_chamadas': n_anuncios + 2 * n_categorias,
    }


# ─── REGRAS DE CADA CAMPO ───────────────────────────────────────────────

def _tags(atributo):
    return set(atributo.tags or [])


# Função Objetivo: Motivo pelo qual o campo não aparece no card, ou None.
def motivo_exclusao(atributo):
    if atributo.atributo_id in CAMPOS_DE_SISTEMA:
        return 'campo de sistema'
    if atributo.tipo_valor in TIPOS_DE_SISTEMA:
        return 'guia de tamanhos'
    tags = _tags(atributo)
    for tag in TAGS_QUE_EXCLUEM:
        if tag in tags:
            return {'read_only': 'somente leitura', 'fixed': 'valor fixo', 'inferred': 'deduzido pelo ML'}[tag]
    return None


def nivel_obrigatoriedade(atributo):
    tags = _tags(atributo)
    if 'required' in tags or 'new_required' in tags:
        return 'Sim'
    if 'conditional_required' in tags:
        return 'Condicional'
    return 'Não'


# Função Objetivo: Tipo real do campo NUMA categoria, pelo que a API diz (e
# não por "tem opções"): lista = list/boolean, ou texto com opções e valor
# próprio NÃO aceito; texto_sugestoes = texto com opções e valor próprio
# aceito (as opções são só sugestões).
def tipo_na_categoria(atributo):
    tipo_valor = atributo.tipo_valor
    opcoes = atributo.opcoes or []
    if tipo_valor in ('list', 'boolean'):
        return 'lista'
    if tipo_valor == 'number_unit':
        return 'numero_unidade'
    if tipo_valor == 'number':
        return 'numero'
    if opcoes and atributo.permite_valor_proprio is False:
        return 'lista'
    if opcoes:
        return 'texto_sugestoes'
    return 'texto'


# Função Objetivo: Em que grupo da ficha o campo fica, quando o produto tem
# categorias diferentes. Se QUALQUER categoria o põe no grupo principal, ele
# fica no principal; senão vale o grupo da categoria mais comum entre os
# anúncios (por_categoria vem nessa ordem). Linha sem grupo (gravada antes
# de o sistema guardar o grupo) conta como principal. Devolve
# (id_do_grupo, rótulo_do_grupo).
def escolher_grupo(por_categoria):
    grupos = []
    for atributo in por_categoria.values():
        grupo_id = atributo.grupo or GRUPO_PRINCIPAL
        rotulo = atributo.grupo_rotulo or (ROTULO_GRUPO_PRINCIPAL if grupo_id == GRUPO_PRINCIPAL else grupo_id)
        grupos.append((grupo_id, rotulo))
    for grupo_id, rotulo in grupos:
        if grupo_id == GRUPO_PRINCIPAL:
            return grupo_id, rotulo
    return grupos[0]


# Função Objetivo: Junta as regras do MESMO campo vindas de várias
# categorias numa só (ver regras de fusão no cabeçalho do arquivo).
# por_categoria = {category_id: AtributoCategoriaMercadoLivre}.
def fundir_atributo(por_categoria):
    categorias = list(por_categoria)
    atributos = list(por_categoria.values())
    tipos = {c: tipo_na_categoria(a) for c, a in por_categoria.items()}
    avisos = []

    niveis = {nivel_obrigatoriedade(a) for a in atributos}
    nivel = max(niveis, key=NIVEL_OBRIGATORIEDADE.get)
    if len(niveis) > 1:
        avisos.append('Obrigatoriedade diferente entre as categorias; vale a mais exigente.')

    resultado = {
        'label': atributos[0].nome,
        'nivel': nivel,
        'multi': any('multivalued' in _tags(a) for a in atributos),
        'booleano': any(a.tipo_valor == 'boolean' for a in atributos),
        'tipo': 'texto',
        'limite': None,
        'opcoes': [],
        'unidades': [],
        'avisos': avisos,
    }

    com_lista = [c for c in categorias if tipos[c] == 'lista']
    com_sugestoes = [c for c in categorias if tipos[c] == 'texto_sugestoes']

    if com_lista:
        resultado['tipo'] = 'lista'
        if len(com_lista) < len(categorias):
            avisos.append('Há categorias com lista fechada e outras com texto livre; a lista vale para todas.')
        conjuntos = [frozenset(o.get('id') for o in (por_categoria[c].opcoes or [])) for c in com_lista]
        ids_comuns = set.intersection(*[set(conjunto) for conjunto in conjuntos])
        resultado['opcoes'] = [
            {'id': o.get('id'), 'name': o.get('name')}
            for o in (por_categoria[com_lista[0]].opcoes or []) if o.get('id') in ids_comuns
        ]
        if len(set(conjuntos)) > 1:
            n_comuns = len(resultado['opcoes'])
            avisos.append(
                f"As opções diferem entre as categorias; {'vale só a opção' if n_comuns == 1 else f'valem as {n_comuns} opções'} em comum."
            )
        if not resultado['opcoes']:
            avisos.append('ATENÇÃO: nenhuma opção em comum entre as categorias.')
        return resultado

    if 'numero_unidade' in tipos.values():
        resultado['tipo'] = 'numero_unidade'
    elif 'numero' in tipos.values():
        resultado['tipo'] = 'numero'
    elif com_sugestoes:
        resultado['tipo'] = 'texto_sugestoes'
        vistos = {}
        for c in com_sugestoes:
            for o in (por_categoria[c].opcoes or []):
                vistos.setdefault(o.get('id'), {'id': o.get('id'), 'name': o.get('name')})
        resultado['opcoes'] = list(vistos.values())
    # Texto livre e texto com sugestões aceitam o mesmo preenchimento; só
    # avisa quando a FAMÍLIA do campo muda (ex.: número numa e texto noutra).
    familias = {'texto' if tipo == 'texto_sugestoes' else tipo for tipo in tipos.values()}
    if len(familias) > 1:
        avisos.append('O tipo do campo difere entre as categorias.')

    tamanhos = {c: a.tamanho_maximo for c, a in por_categoria.items() if a.tamanho_maximo}
    if tamanhos and resultado['tipo'] in ('texto', 'texto_sugestoes'):
        resultado['limite'] = min(tamanhos.values())
        if len(set(tamanhos.values())) > 1:
            valores = ' e '.join(str(v) for v in sorted(set(tamanhos.values())))
            avisos.append(f'Limite mais restrito entre as categorias ({valores}).')

    unidades_por_categoria = {c: (a.unidades_permitidas or []) for c, a in por_categoria.items()}
    com_unidades = [c for c, unidades in unidades_por_categoria.items() if unidades]
    if com_unidades:
        ids_comuns = set.intersection(*[
            {u.get('id') for u in unidades_por_categoria[c]} for c in com_unidades
        ])
        resultado['unidades'] = [
            u.get('name') for u in unidades_por_categoria[com_unidades[0]] if u.get('id') in ids_comuns
        ]
    return resultado


# ─── O QUE O ANÚNCIO TEM HOJE NO ML ─────────────────────────────────────

# Função Objetivo: Lê UM atributo cru do anúncio (item da lista "attributes"
# da API) e diz o que ele é: valor (com o texto), "N/A" (não se aplica) ou
# em branco. Sem nenhuma normalização do texto — é o que o ML tem.
def interpretar_valor(atributo_cru):
    em_branco = {'estado': 'branco', 'texto': '', 'valor_id': None}
    if not atributo_cru:
        return em_branco

    valores = atributo_cru.get('values') or []
    nome = atributo_cru.get('value_name')
    if isinstance(nome, str):
        nome = nome.strip() or None
    if nome is None:
        for item in valores:
            if item.get('name'):
                nome = item['name']
                break

    valor_id = atributo_cru.get('value_id')
    if valor_id is None:
        ids = [item.get('id') for item in valores if item.get('id') is not None]
        valor_id = ids[0] if ids else None

    if nome is not None:
        return {'estado': 'valor', 'texto': str(nome), 'valor_id': valor_id}
    if valor_id is not None and str(valor_id) == VALOR_ID_NA:
        return {'estado': 'na', 'texto': 'N/A', 'valor_id': valor_id}
    if valor_id is not None:
        return {'estado': 'valor', 'texto': f'[sem nome; id={valor_id}]', 'valor_id': valor_id}
    return em_branco


def _esta_na_lista(valor, opcoes):
    ids = {str(o.get('id')) for o in opcoes if o.get('id') is not None}
    nomes = {(o.get('name') or '').strip().lower() for o in opcoes}
    if valor['valor_id'] is not None and str(valor['valor_id']) in ids:
        return True
    return valor['texto'].strip().lower() in nomes


def _plural(n, singular, plural):
    return singular if n == 1 else plural


# * [EXPLICAÇÃO] → Como a obrigatoriedade aparece na etiqueta do card: o texto
#                  e a classe de cor (obrigatório é o mais destacado).
ROTULO_OBRIGATORIEDADE = {
    'Sim': ('Obrigatório', 'car-nivel--obrigatorio'),
    'Condicional': ('Obrigatório em alguns casos', 'car-nivel--condicional'),
    'Não': ('Recomendado', 'car-nivel--recomendado'),
}

# * [EXPLICAÇÃO] → Nível de obrigatoriedade como chave curta (vira a cor do
#                  marcador do card e entra na regra de ordem dos cards).
NIVEL_CHAVE = {'Sim': 'obrigatorio', 'Condicional': 'condicional', 'Não': 'recomendado'}

PILULAS = {
    'uniforme': ('Igual em todos', 'car-pilula--ok'),
    'diverge': ('Valores diferentes', 'car-pilula--alerta'),
    'parcial': ('Parte em branco', 'car-pilula--alerta'),
    'vazio': ('Vazio', 'car-pilula--neutra'),
    'na': ('N/A', 'car-pilula--neutra'),
    'erp': ('Do ERP', 'car-pilula--info'),
}


# Função Objetivo: Garante que o endereço da foto é http(s) e usa https (a
# tela é servida em https; imagem http seria bloqueada). Devolve '' se não for
# um endereço de imagem utilizável.
def _url_foto(valor):
    if not isinstance(valor, str):
        return ''
    url = valor.strip()
    if url.startswith('//'):
        url = 'https:' + url
    if url.startswith('http://'):
        url = 'https://' + url[len('http://'):]
    return url if url.startswith('https://') else ''


# Função Objetivo: Foto de capa de 1 anúncio, só com dados do banco: a 1ª foto
# do próprio anúncio (campo "fotos", como veio do ML) e, se ele não tiver,
# a imagem da variação do SKU. Devolve '' quando não há nenhuma.
def _foto_do_anuncio(anuncio, foto_da_variacao):
    fotos = anuncio.fotos if isinstance(anuncio.fotos, list) else []
    for item in fotos:
        endereco = item if isinstance(item, str) else (
            (item.get('secure_url') or item.get('url')) if isinstance(item, dict) else ''
        )
        url = _url_foto(endereco)
        if url:
            return url
    return foto_da_variacao.get(anuncio.id, '')


def _rotulo_status(codigo, tipo_anuncio=None):
    if codigo is None:
        return '—'
    if tipo_anuncio is not None and tipo_anuncio.status == codigo:
        return tipo_anuncio.get_status_display()
    return ROTULO_STATUS_FALLBACK.get(codigo, codigo)


# ─── FICHA DO PRODUTO (cards + tabela de anúncios) ──────────────────────

# Função Objetivo: Junta, só com dados do banco, tudo que a ficha E o envio de
# 1 produto precisam saber: os anúncios elegíveis, o que cada um tem hoje (o
# array cru lido do ML), a categoria de cada um e os campos que cada categoria
# pede. Devolve None se o SKU não existe. A ficha (cards e tabela) e o envio
# (validação e prévia) partem deste mesmo retrato, para nunca discordarem.
def carregar_contexto_produto(sku):
    from mercado_livre.models import AtributoCategoriaMercadoLivre, CategoriaMercadoLivre, VariacaoAnuncioMercadoLivre
    from produtos.models import Produto

    produto = Produto.objects.filter(sku=sku).first()
    if produto is None:
        return None

    anuncios = list(
        consultar_anuncios_elegiveis([sku]).select_related('tipo_de_anuncio').order_by('mlb')
    )
    total = len(anuncios)

    # Uma só consulta nas variações do SKU: a categoria que o banco conhece e,
    # de reserva, a imagem da variação (para o anúncio sem foto própria).
    categoria_do_banco = {}
    foto_da_variacao = {}
    for anuncio_id, categoria_id, imagem_principal, miniatura in (
        VariacaoAnuncioMercadoLivre.objects
        .filter(anuncio__in=anuncios, produto_id=sku)
        .order_by('pk')
        .values_list('anuncio_id', 'categoria_id', 'imagem_principal_url', 'thumbnail_url')
    ):
        if categoria_id:
            categoria_do_banco.setdefault(anuncio_id, categoria_id)
        url = _url_foto(imagem_principal) or _url_foto(miniatura)
        if url:
            foto_da_variacao.setdefault(anuncio_id, url)
    foto_por_anuncio = {a.id: _foto_do_anuncio(a, foto_da_variacao) for a in anuncios}

    lidos = [a for a in anuncios if a.atributos_ml_lido_em is not None]
    categoria_do_anuncio = {a.id: a.atributos_ml_categoria_id for a in lidos}

    ids_categorias = {c for c in categoria_do_anuncio.values() if c} | set(categoria_do_banco.values())
    categorias = {
        c['category_id']: c
        for c in CategoriaMercadoLivre.objects
        .filter(category_id__in=ids_categorias)
        .values('category_id', 'nome', 'caminho_completo')
    }

    def nome_categoria(category_id):
        if not category_id:
            return '—'
        return categorias.get(category_id, {}).get('nome') or category_id

    contagem_categorias = Counter(c for c in categoria_do_anuncio.values() if c)
    ordem_categorias = [c for c, _ in sorted(contagem_categorias.items(), key=lambda item: (-item[1], item[0]))]

    atributos_por_categoria = defaultdict(list)
    for atributo in (
        AtributoCategoriaMercadoLivre.objects
        .filter(categoria_id__in=ordem_categorias)
        .order_by('categoria_id', 'ordem', 'nome')
    ):
        atributos_por_categoria[atributo.categoria_id].append(atributo)

    # Quais campos existem (união entre as categorias) e quais ficam de fora.
    campos = {}
    ordem_campos = []
    ocultos = {}
    for categoria in ordem_categorias:
        for atributo in atributos_por_categoria.get(categoria, []):
            if TAG_OCULTO in _tags(atributo):
                continue
            motivo = motivo_exclusao(atributo)
            if motivo:
                ocultos.setdefault(atributo.atributo_id, {'label': atributo.nome, 'motivo': motivo})
                continue
            if atributo.atributo_id not in campos:
                campos[atributo.atributo_id] = {}
                ordem_campos.append(atributo.atributo_id)
            campos[atributo.atributo_id][categoria] = atributo
    ocultos = {k: v for k, v in ocultos.items() if k not in campos}

    # Em que grupo da ficha cada campo fica, e a ordem dos grupos: o
    # principal primeiro, os demais na ordem em que aparecem na ficha do ML.
    # Os campos ficam ordenados grupo por grupo (a tabela e o envio seguem
    # a mesma ordem dos cards).
    grupo_do_campo = {atributo_id: escolher_grupo(campos[atributo_id]) for atributo_id in ordem_campos}
    rotulo_do_grupo = {}
    ordem_grupos = []
    for atributo_id in ordem_campos:
        grupo_id, rotulo = grupo_do_campo[atributo_id]
        if grupo_id not in rotulo_do_grupo:
            rotulo_do_grupo[grupo_id] = rotulo
            ordem_grupos.append(grupo_id)
    if GRUPO_PRINCIPAL in ordem_grupos:
        ordem_grupos.remove(GRUPO_PRINCIPAL)
        ordem_grupos.insert(0, GRUPO_PRINCIPAL)
    ordem_campos.sort(key=lambda atributo_id: ordem_grupos.index(grupo_do_campo[atributo_id][0]))

    # O que cada anúncio lido tem hoje, por atributo.
    cru_por_anuncio = {
        a.id: {item.get('id'): item for item in (a.atributos_ml or []) if isinstance(item, dict)}
        for a in lidos
    }

    return {
        'produto': produto,
        'anuncios': anuncios,
        'total': total,
        'lidos': lidos,
        'categoria_do_banco': categoria_do_banco,
        'categoria_do_anuncio': categoria_do_anuncio,
        'foto_por_anuncio': foto_por_anuncio,
        'categorias': categorias,
        'nome_categoria': nome_categoria,
        'contagem_categorias': contagem_categorias,
        'ordem_categorias': ordem_categorias,
        'atributos_por_categoria': atributos_por_categoria,
        'campos': campos,
        'ordem_campos': ordem_campos,
        'grupo_do_campo': grupo_do_campo,
        'ordem_grupos': ordem_grupos,
        'rotulo_do_grupo': rotulo_do_grupo,
        'ocultos': ocultos,
        'cru_por_anuncio': cru_por_anuncio,
    }


# Função Objetivo: Monta tudo que a ficha de 1 produto mostra, só com dados
# do banco. Devolve None se o SKU não existe. Estrutura:
#   produto, resumo (contagens, categorias, última leitura), avisos,
#   cards (1 por característica, grupo por grupo), grupos (os mesmos cards
#   separados por grupo da ficha do ML, na ordem da tela), tabela (colunas
#   e linhas, 1 por anúncio), ocultos (campos que ficam fora do card e por
#   quê).
def montar_ficha_produto(sku):
    contexto = carregar_contexto_produto(sku)
    if contexto is None:
        return None

    produto = contexto['produto']
    anuncios = contexto['anuncios']
    total = contexto['total']
    lidos = contexto['lidos']
    categoria_do_banco = contexto['categoria_do_banco']
    categoria_do_anuncio = contexto['categoria_do_anuncio']
    categorias = contexto['categorias']
    nome_categoria = contexto['nome_categoria']
    contagem_categorias = contexto['contagem_categorias']
    ordem_categorias = contexto['ordem_categorias']
    atributos_por_categoria = contexto['atributos_por_categoria']
    campos = contexto['campos']
    ordem_campos = contexto['ordem_campos']
    grupo_do_campo = contexto['grupo_do_campo']
    ordem_grupos = contexto['ordem_grupos']
    rotulo_do_grupo = contexto['rotulo_do_grupo']
    ocultos = contexto['ocultos']
    cru_por_anuncio = contexto['cru_por_anuncio']
    foto_por_anuncio = contexto['foto_por_anuncio']

    cards = []
    for atributo_id in ordem_campos:
        card = _montar_card(
            produto, sku, atributo_id, campos[atributo_id], lidos, total,
            categoria_do_anuncio, cru_por_anuncio, nome_categoria,
        )
        card['grupo'], card['grupo_rotulo'] = grupo_do_campo[atributo_id]
        cards.append(card)

    # * [EXPLICAÇÃO] → Ordem FIXA dos cards dentro de cada grupo (a posição de
    #                  um card nunca muda enquanto a pessoa digita; só muda se a
    #                  ficha for recarregada depois de um "Atualizar" ou envio).
    #                  O sort do Python é estável: empate = ordem original do ML.
    cards.sort(key=lambda card: (
        ordem_grupos.index(card['grupo']), _posicao_do_card(card), -card['n_pedem'],
    ))

    grupos = []
    for grupo_id in ordem_grupos:
        cards_do_grupo = [card for card in cards if card['grupo'] == grupo_id]
        grupos.append({
            'id': grupo_id,
            'rotulo': rotulo_do_grupo[grupo_id],
            'cards': cards_do_grupo,
            'n': len(cards_do_grupo),
            'n_atencao': sum(1 for card in cards_do_grupo if card['pede_atencao']),
            'n_resolver': sum(1 for card in cards_do_grupo if card['resolver']),
        })

    tabela = _montar_tabela(
        anuncios, cards, categoria_do_anuncio, categoria_do_banco, cru_por_anuncio, nome_categoria,
        foto_por_anuncio,
    )

    ultima_leitura = max((a.atributos_ml_lido_em for a in lidos), default=None)
    avisos = _montar_avisos(
        anuncios, lidos, total, ordem_categorias, atributos_por_categoria,
        categoria_do_anuncio, categoria_do_banco, nome_categoria,
    )

    contagem_cards = {
        'todas': len(cards),
        'resolver': sum(1 for card in cards if card['resolver']),
        'obrigatorias': sum(1 for card in cards if card['obrigatorio_qualquer']),
        'vazios': sum(1 for card in cards if card['estado'] == 'vazio'),
        'atencao': sum(1 for card in cards if card['pede_atencao']),
        'n_obrigatorios': sum(1 for card in cards if card['obrigatorio']),
        'n_condicionais': sum(1 for card in cards if card['nivel_chave'] == 'condicional'),
    }

    return {
        'produto': {
            'id': produto.id, 'sku': sku, 'titulo': produto.titulo or '',
            'marca': produto.marca or '', 'ean': produto.ean or '',
        },
        'resumo': {
            'n_anuncios': total,
            'n_lidos': len(lidos),
            'categorias': [
                {
                    'id': c,
                    'nome': nome_categoria(c),
                    'caminho': categorias.get(c, {}).get('caminho_completo') or '',
                    'n': contagem_categorias[c],
                    # quantos campos desta ficha a categoria pede
                    'n_campos': sum(1 for atributo_id in ordem_campos if c in campos[atributo_id]),
                }
                for c in ordem_categorias
            ],
            'ultima_leitura': ultima_leitura,
        },
        'avisos': avisos,
        'cards': cards,
        'grupos': grupos,
        'contagem_cards': contagem_cards,
        # Filtro que já nasce marcado: "Resolver primeiro" quando há o que
        # resolver; senão mostra tudo (não deixa a tela vazia sem motivo).
        'filtro_inicial': 'resolver' if contagem_cards['resolver'] else 'todos',
        # Campo que a tabela de anúncios mostra ao abrir: o primeiro a resolver
        # (ou, se não há, o primeiro da ficha). A pessoa troca no seletor.
        'campo_tabela_inicial': next(
            (card['atributo_id'] for card in cards if card['resolver']),
            cards[0]['atributo_id'] if cards else '',
        ),
        'tabela': tabela,
        'ocultos': sorted(
            ({'id': k, **v} for k, v in ocultos.items()), key=lambda item: item['label'].lower()
        ),
    }


# Função Objetivo: Posição do card dentro do grupo (menor = mais acima). A
# regra, do mais importante para o menos:
#   0  obrigatório que o usuário pode corrigir e que está diferente, em branco
#      em parte ou vazio;
#   1  obrigatório travado (a Marca, que vem do ERP);
#   2  os demais obrigatórios;
#   3  obrigatório "em alguns casos";
#   4  recomendado com valores diferentes;   5  recomendado em branco em parte;
#   6  recomendado vazio;   7  recomendado já igual em todos;
#   8  o que não dá para editar (vários valores) e os N/A.
def _posicao_do_card(card):
    estado, nivel, editavel = card['estado'], card['nivel_chave'], card['editavel']
    if nivel == 'obrigatorio':
        if editavel and estado in ('diverge', 'parcial', 'vazio'):
            return 0
        return 2 if editavel else 1
    if nivel == 'condicional':
        return 3
    if editavel:
        return {'diverge': 4, 'parcial': 5, 'vazio': 6, 'uniforme': 7}.get(estado, 8)
    return 8


def _montar_avisos(anuncios, lidos, total, ordem_categorias, atributos_por_categoria,
                   categoria_do_anuncio, categoria_do_banco, nome_categoria):
    avisos = []
    nao_lidos = total - len(lidos)
    if total and not lidos:
        avisos.append('Nenhum anúncio deste produto foi lido ainda. Clique em "Atualizar" para ler do Mercado Livre.')
    elif nao_lidos:
        avisos.append(
            f'{nao_lidos} de {total} {_plural(total, "anúncio", "anúncios")} ainda não '
            f'{_plural(nao_lidos, "foi lido", "foram lidos")}. Clique em "Atualizar" para ler.'
        )

    sem_campos = [c for c in ordem_categorias if not atributos_por_categoria.get(c)]
    for categoria in sem_campos:
        avisos.append(f'Os campos da categoria "{nome_categoria(categoria)}" ainda não foram lidos. Clique em "Atualizar".')

    sem_grupo = [
        c for c in ordem_categorias
        if any(not a.grupo for a in atributos_por_categoria.get(c, []))
    ]
    for categoria in sem_grupo:
        avisos.append(
            f'A categoria "{nome_categoria(categoria)}" foi lida antes de a tela mostrar o grupo "Outros" '
            f'e as demais características. Clique em "Atualizar" para ler de novo.'
        )

    mudaram = [
        a for a in lidos
        if a.atributos_ml_categoria_id and categoria_do_banco.get(a.id)
        and a.atributos_ml_categoria_id != categoria_do_banco[a.id]
    ]
    if mudaram:
        avisos.append(
            f'{len(mudaram)} {_plural(len(mudaram), "anúncio está", "anúncios estão")} em categoria diferente da '
            f'que o banco tinha (o ML mudou). A tela usa a categoria atual do ML.'
        )

    fora = [a for a in lidos if a.atributos_ml_status and a.atributos_ml_status not in STATUS_ACEITOS]
    if fora:
        n = len(fora)
        avisos.append(
            f'{n} {_plural(n, "anúncio não está mais ativo nem pausado", "anúncios não estão mais ativos nem pausados")} '
            f'no ML, mas o banco {_plural(n, "ainda o tem", "ainda os tem")} como ativo{"" if n == 1 else "s"}. '
            f'{_plural(n, "Ele sai", "Eles saem")} desta tela depois da próxima atualização dos anúncios.'
        )
    return avisos


def _montar_card(produto, sku, atributo_id, por_categoria, lidos, total,
                 categoria_do_anuncio, cru_por_anuncio, nome_categoria):
    fusao = fundir_atributo(por_categoria)
    eh_marca = atributo_id == ATRIBUTO_MARCA
    valor_erp = (produto.marca or '').strip() if eh_marca else ''

    pedem = [a for a in lidos if categoria_do_anuncio.get(a.id) in por_categoria]
    n_pedem = len(pedem)

    valores = Counter()
    modelo_do_valor = {}
    n_branco = 0
    for anuncio in pedem:
        valor = interpretar_valor(cru_por_anuncio[anuncio.id].get(atributo_id))
        if valor['estado'] == 'branco':
            n_branco += 1
            continue
        valores[valor['texto']] += 1
        modelo_do_valor.setdefault(valor['texto'], valor)

    # chips "Hoje no Mercado Livre": mais comum primeiro
    chips = []
    for texto, n in sorted(valores.items(), key=lambda item: (-item[1], item[0])):
        valor = modelo_do_valor[texto]
        classe = 'car-chip'
        nota = ''
        if valor['estado'] == 'na':
            classe += ' car-chip--neutro'
            nota = 'não se aplica'
        elif eh_marca:
            if valor_erp and texto == valor_erp:
                classe += ' car-chip--ok'
                nota = 'igual ao ERP'
            else:
                classe += ' car-chip--alerta'
                nota = 'diferente do ERP'
        elif fusao['tipo'] == 'lista' and fusao['opcoes'] and not _esta_na_lista(valor, fusao['opcoes']):
            classe += ' car-chip--neutro'
            nota = 'fora da lista'
        # * [EXPLICAÇÃO] → valor_id e texto crus: a gaveta do card usa para o
        #                  botão "Usar este valor" (copia o valor que já está
        #                  nos anúncios para o campo "Valor a enviar").
        chips.append({
            'rotulo': texto, 'n': n, 'n_txt': f'{n} {_plural(n, "anúncio", "anúncios")}',
            'classe': classe, 'nota': nota,
            'copiavel': (
                valor['estado'] == 'valor' and not eh_marca and nota != 'fora da lista'
                and not texto.startswith('[sem nome')
            ),
            'valor_id': '' if valor['valor_id'] is None else str(valor['valor_id']),
        })
    if n_branco:
        chips.append({
            'rotulo': 'em branco', 'n': n_branco,
            'n_txt': f'{n_branco} {_plural(n_branco, "anúncio", "anúncios")}',
            'classe': 'car-chip car-chip--vazio', 'nota': '',
            'copiavel': False, 'valor_id': '',
        })

    # estado do card
    soma = sum(valores.values())
    if eh_marca:
        iguais = valor_erp and set(valores) == {valor_erp} and not n_branco
        estado = 'erp'
        nota_ml = (
            'Todos os anúncios já usam a marca do ERP.' if iguais
            else 'Há anúncios com a marca diferente do ERP ou em branco.' if valores or n_branco
            else 'Nenhum anúncio lido tem este campo.'
        )
        nota_ml_classe = 'car-nota--ok' if iguais else 'car-nota--alerta'
    elif not valores:
        estado, nota_ml, nota_ml_classe = 'vazio', 'Nenhum anúncio tem este campo preenchido.', ''
    elif len(valores) > 1:
        estado = 'diverge'
        nota_ml = 'Os anúncios têm valores diferentes.'
        nota_ml_classe = 'car-nota--alerta'
    elif n_branco:
        estado = 'parcial'
        nota_ml = f'{n_branco} {_plural(n_branco, "anúncio está", "anúncios estão")} em branco.'
        nota_ml_classe = ''
    elif set(valores) == {'N/A'}:
        estado = 'na'
        nota_ml = 'Todos os anúncios estão marcados como N/A (não se aplica).'
        nota_ml_classe = ''
    else:
        estado = 'uniforme'
        nota_ml = 'Todos os anúncios que pedem este campo têm o mesmo valor.'
        nota_ml_classe = 'car-nota--ok'
    if estado == 'diverge' and n_branco:
        nota_ml += f' E {n_branco} {_plural(n_branco, "está em branco", "estão em branco")}.'
    pilula_txt, pilula_classe = PILULAS[estado]
    if estado == 'parcial':
        pilula_txt = f'Em branco em {n_branco}'

    # * [EXPLICAÇÃO] → "Pede atenção" = quem olha tem algo a conferir ou
    #                  preencher: valores diferentes, campo em branco em parte
    #                  dos anúncios, campo vazio ou marca fora do ERP. Alimenta
    #                  o filtro "Pedem atenção" e a cor do card.
    pede_atencao = estado in ('diverge', 'parcial', 'vazio') or (eh_marca and nota_ml_classe == 'car-nota--alerta')
    req_rotulo, req_classe = ROTULO_OBRIGATORIEDADE[fusao['nivel']]

    # * [EXPLICAÇÃO] → O card compacto só tem espaço para o resumo do que há
    #                  hoje nos anúncios, em 1 linha; o detalhe completo (todos
    #                  os valores, anúncio por anúncio) fica na gaveta do card.
    #                  Nos valores diferentes, a linha já mostra o mais comum.
    editavel = not eh_marca and not fusao['multi']
    por_frequencia = sorted(valores.items(), key=lambda item: (-item[1], item[0]))
    if eh_marca:
        micro = f'ERP: {valor_erp}' if valor_erp else 'Marca sem cadastro no ERP'
    elif estado == 'vazio':
        micro = 'Hoje: tudo em branco'
    elif estado == 'na':
        micro = 'Hoje: não se aplica (N/A)'
    elif estado == 'uniforme':
        micro = f'Hoje: {por_frequencia[0][0]}'
    elif estado == 'parcial':
        micro = f'Hoje: {por_frequencia[0][0]} · {n_branco} em branco'
    else:
        mais_comum, vezes = por_frequencia[0]
        micro = f'{len(valores)} valores · mais comum: {mais_comum} ({vezes}×)'
        if n_branco:
            micro += f' · {n_branco} em branco'
    cobertura = f'{n_pedem} de {total} {_plural(total, "anúncio", "anúncios")}'

    # * [EXPLICAÇÃO] → "Resolver primeiro" = o que o usuário PODE corrigir e que
    #                  merece olhar agora: valores diferentes, campo em branco em
    #                  parte dos anúncios, ou obrigatório que ninguém preencheu.
    #                  Não entram campos travados (Marca, vários valores) nem
    #                  recomendado que já está igual em todos.
    resolver = editavel and (
        estado in ('diverge', 'parcial') or (estado == 'vazio' and fusao['nivel'] == 'Sim')
    )

    # "Regra" e "Vale para"
    tipo = fusao['tipo']
    unidades = fusao['unidades']
    if eh_marca:
        regra1 = 'Marca do cadastro do produto (ERP)'
    elif tipo == 'lista' and fusao['booleano']:
        regra1 = 'Sim ou Não'
    elif tipo == 'lista':
        regra1 = f"Lista fechada com {len(fusao['opcoes'])} {_plural(len(fusao['opcoes']), 'opção', 'opções')}"
    elif tipo == 'texto_sugestoes':
        regra1 = f"Texto livre com {len(fusao['opcoes'])} {_plural(len(fusao['opcoes']), 'sugestão', 'sugestões')}"
        if fusao['limite']:
            regra1 += f" (até {fusao['limite']} caracteres)"
    elif tipo == 'numero_unidade':
        regra1 = 'Número com unidade' + (f" ({' ou '.join(unidades)})" if unidades else '')
    elif tipo == 'numero':
        regra1 = 'Número'
    else:
        regra1 = f"Texto de até {fusao['limite']} caracteres" if fusao['limite'] else 'Texto livre'

    if fusao['avisos']:
        regra2 = ' '.join(fusao['avisos'])
    elif len(por_categoria) == 1:
        regra2 = 'Regra da categoria do anúncio.'
    else:
        regra2 = 'Mesma regra em todas as categorias.'
    if fusao['multi']:
        regra2 += ' Aceita mais de um valor.'

    nomes_pedem = [nome_categoria(c) for c in por_categoria]
    vale1 = f'Todos os {total} anúncios' if n_pedem == total else f'{n_pedem} de {total} {_plural(total, "anúncio", "anúncios")}'
    if total == 1:
        vale1 = '1 anúncio'
    if len(nomes_pedem) == 1:
        vale2 = f'Categoria {nomes_pedem[0]}.'
    else:
        vale2 = 'Categorias: ' + ', '.join(nomes_pedem) + '.'
    n_nao_lidos = total - len(lidos)
    if n_nao_lidos:
        vale2 += f' {n_nao_lidos} {_plural(n_nao_lidos, "anúncio ainda não lido", "anúncios ainda não lidos")}.'

    opcoes_nomes = [o.get('name') or '' for o in fusao['opcoes']]

    # Para a digitação do "Valor a enviar": lista fechada = TODAS as opções
    # (id + nome) no select; os botões Sim/Não valem para o booleano do ML e
    # para qualquer lista que seja só Sim e Não.
    opcoes_pares = (
        [{'id': str(o.get('id')), 'name': o.get('name') or ''} for o in fusao['opcoes'] if o.get('id') is not None]
        if tipo == 'lista' else []
    )
    simnao = (
        len(opcoes_pares) == 2
        and {p['name'].strip().lower() for p in opcoes_pares} <= NOMES_SIM_NAO
    )
    return {
        'id_html': f'car-campo-{slugify(sku)}-{slugify(atributo_id)}',
        'atributo_id': atributo_id,
        'label': fusao['label'],
        'req_rotulo': req_rotulo,
        'req_classe': req_classe,
        'nivel_chave': NIVEL_CHAVE[fusao['nivel']],
        'obrigatorio': fusao['nivel'] == 'Sim',
        'obrigatorio_qualquer': fusao['nivel'] in ('Sim', 'Condicional'),
        'editavel': editavel,
        'resolver': resolver,
        'micro': micro,
        'cobertura': cobertura,
        'n_pedem': n_pedem,
        'n_branco': n_branco,
        'pede_atencao': pede_atencao,
        'estado': estado,
        'pilula_txt': pilula_txt,
        'pilula_classe': pilula_classe,
        'eh_marca': eh_marca,
        'valor_erp': valor_erp,
        'tipo': tipo,
        'booleano': fusao['booleano'],
        'simnao': simnao,
        'limite': fusao['limite'],
        'opcoes_pares': opcoes_pares,
        'multi': fusao['multi'],
        'unidades': unidades,
        'opcoes_total': len(opcoes_nomes),
        'opcoes_exibidas': opcoes_nomes[:LIMITE_OPCOES_EXIBIDAS],
        'opcoes_restantes': max(0, len(opcoes_nomes) - LIMITE_OPCOES_EXIBIDAS),
        'chips': chips,
        'ml_nota': nota_ml,
        'ml_nota_classe': nota_ml_classe,
        'regra1': regra1,
        'regra2': regra2,
        'vale1': vale1,
        'vale2': vale2,
        'largura': 'larga' if tipo in ('texto', 'texto_sugestoes') else 'media',
        'soma_valores': soma,
        'pedem_categorias': tuple(por_categoria),
    }


def _montar_tabela(anuncios, cards, categoria_do_anuncio, categoria_do_banco, cru_por_anuncio, nome_categoria,
                   foto_por_anuncio=None):
    foto_por_anuncio = foto_por_anuncio or {}
    colunas = [
        {'label': card['label'], 'api': card['atributo_id'], 'largura': card['largura']}
        for card in cards
    ]

    linhas = []
    for anuncio in anuncios:
        lido = anuncio.atributos_ml_lido_em is not None
        categoria = categoria_do_anuncio.get(anuncio.id) if lido else None
        categoria_exibida = categoria or categoria_do_banco.get(anuncio.id)

        celulas = []
        tem_branco = False
        if lido:
            cru = cru_por_anuncio.get(anuncio.id, {})
            for card in cards:
                atributo_id = card['atributo_id']
                if categoria not in card['pedem_categorias']:
                    celulas.append({'estado': 'nao_pede', 'texto': 'categoria não pede'})
                    continue
                valor = interpretar_valor(cru.get(atributo_id))
                if valor['estado'] == 'branco':
                    tem_branco = True
                    celulas.append({'estado': 'branco', 'texto': 'em branco'})
                else:
                    celulas.append({'estado': valor['estado'], 'texto': valor['texto']})
        else:
            celulas = [{'estado': 'nao_lido', 'texto': 'não lido'} for _ in cards]

        # O id do campo em cada célula: a tabela mostra 1 campo por vez
        # (o escolhido no seletor) e a gaveta do card lê a coluna dele.
        for celula, card in zip(celulas, cards):
            celula['atributo_id'] = card['atributo_id']

        status = anuncio.atributos_ml_status if lido else (
            anuncio.tipo_de_anuncio.status if anuncio.tipo_de_anuncio else None
        )
        linhas.append({
            'mlb': anuncio.mlb,
            'foto': foto_por_anuncio.get(anuncio.id, ''),
            'permalink': anuncio.permalink or '',
            'titulo': anuncio.titulo_anuncio or '',
            'categoria_nome': nome_categoria(categoria_exibida),
            'categoria_id': categoria_exibida or '',
            'status_txt': _rotulo_status(status, anuncio.tipo_de_anuncio),
            'status_fora': bool(lido and status and status not in STATUS_ACEITOS),
            'lido': lido,
            'lido_em': anuncio.atributos_ml_lido_em,
            'tem_branco': tem_branco,
            'celulas': celulas,
        })

    return {
        'colunas': colunas,
        'linhas': linhas,
        'n_total': len(linhas),
        'n_com_branco': sum(1 for linha in linhas if linha['tem_branco']),
        'n_nao_lidos': sum(1 for linha in linhas if not linha['lido']),
    }

