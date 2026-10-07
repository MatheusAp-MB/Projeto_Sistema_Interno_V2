# gestao_full/funcoes_auxiliares/full_ml.py
#
# Monta a "ficha" de 1 código do Full (Planejamento de envios) a partir da
# consulta SALVA NO BANCO. LÊ SÓ DO BANCO — nada aqui chama a API do ML (quem
# chama, só por botão, é integracao_mercado_livre/servicos/consultar_full_ml.py).
#
# A ficha tem 3 NÍVEIS, porque cada informação pertence a uma coisa diferente:
#   Nível 1  PRODUTO              o cadastro do produto no nosso sistema (tabela Produto,
#                                 achada pelo SKU). Um bloco por SKU.
#   Nível 2  CÓDIGO ML DO FULL    estoque, vendas e reposição do Full. Pertencem ao Código ML
#                                 (inventory_id / user_product_id), não a um anúncio.
#   Nível 3  ANÚNCIOS             título, status, preço, tipo logístico... Um bloco para CADA
#                                 MLB (e cada variação). Dado de um anúncio NUNCA é misturado
#                                 com o de outro no mesmo campo.
#
# O que a ficha mostra, linha a linha, é sempre: o nome da informação, o valor, a FONTE do
# valor (REPOS, ESTOQUE, ARQUIVO, BANCO ou TELA), o campo exato dessa fonte e se o endpoint é
# NOVO ou JÁ USADO no projeto — mais o nome interno, a situação (A validar / Hipótese /
# Válido / Inválido) e a observação que a equipe registra em CampoFullMercadoLivre.
#
# As 5 fontes:
#   REPOS    GET /marketplace/fbm/user-products/{user_product_id}/replenishment
#            = os dados da própria tela "Planejamento de envios".
#   ESTOQUE  GET /inventories/{inventory_id}/stock/fulfillment
#            = o estoque do Full detalhado (apto, não apto e o motivo).
#   ARQUIVO  detalhes_mlbs.json = foto local gravada pelo comando buscar_detalhes
#            (via GET /items?ids=..., endpoint que o projeto já usa).
#   BANCO    as tabelas do próprio sistema (Produto, AnuncioMercadoLivre e
#            VariacaoAnuncioMercadoLivre) — sem chamada ao ML.
#   TELA     o HTML da página do ML — o que as APIs não entregam.
#
# As funções que montam a ficha são puras (recebem a consulta e devolvem
# dicionários); só ler_banco, listar_recentes, buscar_ultima_consulta e
# carregar_validacoes tocam o banco (todas só LEEM).

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# AS FONTES
# ---------------------------------------------------------------------------
# * [EXPLICAÇÃO] → "projeto" diz se o endpoint é NOVO (nenhum outro código do
#                  projeto o chama — só esta tela) ou JÁ USADO (outro código do
#                  projeto já o chama). Escrito à mão: se um dia outro módulo
#                  passar a usar REPOS/ESTOQUE, atualize aqui. BANCO não é endpoint:
#                  é leitura das tabelas do sistema (projeto = 'banco').
FONTES_FULL = {
    'REPOS': {
        'nome': 'API de reposição (os dados da própria tela "Planejamento de envios")',
        'endpoint_modelo': 'GET /marketplace/fbm/user-products/{user_product_id}/replenishment?country=BR',
        'projeto': 'novo',
        'projeto_texto': 'NOVO — nenhum outro código do projeto chama este endpoint (só esta tela).',
    },
    'ESTOQUE': {
        'nome': 'API de estoque do Full (apto, não apto e o motivo)',
        'endpoint_modelo': 'GET /inventories/{inventory_id}/stock/fulfillment',
        'projeto': 'novo',
        'projeto_texto': 'NOVO — nenhum outro código do projeto chama este endpoint (só esta tela).',
    },
    'ARQUIVO': {
        'nome': 'seu detalhes_mlbs.json (foto gravada pelo comando buscar_detalhes)',
        'endpoint_modelo': 'Nenhuma chamada agora. O arquivo vem de GET /items?ids=MLB1,MLB2,MLB3 (a lista pode ter até 20 códigos por lote).',
        'projeto': 'ja_usado',
        'projeto_texto': 'JÁ USADO — api_mercado_livre/detalhes_ml.py (DetalhesML.buscar_lote), pelo comando buscar_detalhes.',
    },
    'BANCO': {
        'nome': 'Banco de dados do sistema (Produto, Anúncio e Variação)',
        'endpoint_modelo': 'Nenhuma chamada ao ML. Lido das tabelas Produto, AnuncioMercadoLivre e VariacaoAnuncioMercadoLivre desta empresa.',
        'projeto': 'banco',
        'projeto_texto': ('São as tabelas do próprio sistema. Os anúncios entram no banco pelo popular_banco '
                          '(importar_anuncios_ml) a partir do detalhes_mlbs.json, então o banco pode estar '
                          'atrás do arquivo.'),
    },
    'TELA': {
        'nome': 'O HTML da página do Mercado Livre (a comparação é feita à mão)',
        'endpoint_modelo': 'Não é endpoint: só existe na tela.',
        'projeto': 'tela',
        'projeto_texto': 'Não é endpoint.',
    },
}

ROTULO_PROJETO = {'novo': 'NOVO', 'ja_usado': 'JÁ USADO', 'banco': 'DO BANCO', 'tela': 'SÓ NA TELA'}


# Função Objetivo: O texto da etiqueta ao lado de cada fonte ("endpoint NOVO", "tabela do sistema"...).
def etiqueta_projeto(fonte):
    projeto = FONTES_FULL[fonte]['projeto']
    if projeto == 'tela':
        return ''
    if projeto == 'banco':
        return 'tabela do sistema (sem ML)'
    return f'endpoint {ROTULO_PROJETO[projeto]}'


SITUACAO_PADRAO = 'a_validar'

# Chaves que a DOC cita em cada resposta. Tudo que a API mandar fora disso aparece
# como "campo fora da doc" — é justamente o tipo de coisa que queremos descobrir.
CHAVES_DOC_REPOSICAO = {
    '(raiz)': {'identifiers', 'product', 'stock', 'sales', 'recommendation', 'eligibility_benefits'},
    'identifiers': {'user_product_id', 'inventory_id', 'seller_sku'},
    'product': {'tags', 'packages_master_case'},
    'stock': {'total_stock', 'shipping_urgency', 'minimum_distributable_stock'},
    'sales': {'sales_totals', 'sales_history'},
    'recommendation': {'recommendation_type', 'suggested_quantity', 'replenishment_deadline', 'replenishment_frequency'},
}
CHAVES_DOC_ESTOQUE = {
    '(raiz)': {'inventory_id', 'total', 'available_quantity', 'not_available_quantity',
               'not_available_detail', 'external_references'},
}

# Traduções só para ajudar a leitura (o valor original da API aparece sempre ao lado).
URGENCIA = {'URGENT': 'urgente', 'THIS_WEEK': 'esta semana', 'NEXT_WEEK': 'próxima semana',
            'IN_TWO_WEEKS': 'em 2 semanas', 'NO_URGENCY': 'sem urgência', 'EXCEDENT': 'excedente'}
RECOMENDACAO = {'REPLENISH': 'repor', 'NO_REPLENISHMENT': 'não repor',
                'NO_REPLENISHMENT_BY_RESTRICTION': 'não repor, por restrição'}
MOTIVO_INDISPONIVEL = {'damaged': 'danificada', 'lost': 'perdida', 'withdrawal': 'em retirada',
                       'internal_process': 'em processo interno', 'transfer': 'em transferência',
                       'noFiscalCoverage': 'sem cobertura fiscal', 'not_supported': 'não suportada'}


# * [EXPLICAÇÃO] → Status, tipo de anúncio, tipo logístico e classificação de catálogo já têm os
#                  rótulos escritos no model TipoDeAnuncioMercadoLivre. Lemos de lá (não repetimos a
#                  lista aqui), assim um rótulo novo no model aparece na ficha sozinho.
def _rotulos_do_tipo_de_anuncio():
    from mercado_livre.models import TipoDeAnuncioMercadoLivre as Tipo
    return {
        'status': dict(Tipo.Status.choices),
        'tipo_anuncio': dict(Tipo.TipoAnuncio.choices),
        'tipo_logistico': dict(Tipo.TipoLogistico.choices),
        'classificacao_catalogo': dict(Tipo.ClassificacaoCatalogo.choices),
    }


# ---------------------------------------------------------------------------
# O CATÁLOGO DE CAMPOS DA FICHA
# ---------------------------------------------------------------------------
# * [EXPLICAÇÃO] → Cada entrada é 1 linha da ficha: em que bloco aparece, de qual
#                  fonte vem, o caminho exato do campo naquela fonte (para TELA,
#                  um nome curto nosso), o nome da informação e o formato de exibição.
#                  O mesmo campo (fonte + caminho) vale para TODOS os anúncios: o que a
#                  equipe registra (nome interno, situação, observação) descreve o CAMPO,
#                  então ao validar "ARQUIVO · status" num anúncio, o outro anúncio
#                  mostra o mesmo registro — mas o VALOR de cada anúncio é só dele.
#                  Para criar uma linha nova, basta uma entrada aqui — a tela e o registro
#                  de validação já a pegam. Opcionais: "explicacao" (texto fixo sob o nome,
#                  só com o que o código do projeto garante) e "nota_vazio" (o que significa
#                  o campo vir vazio).
NIVEIS_FULL = (
    ('produto', 'Nível 1 — Produto',
     'Quem é o produto para o nosso sistema. Vem do banco (tabela Produto), achado pelo SKU. '
     'Nada deste nível vem do Mercado Livre.'),
    ('codigo', 'Nível 2 — Código ML do Full',
     'O que o Full sabe de estoque, vendas e reposição. Pertence ao Código ML '
     '(inventory_id / user_product_id), não a um anúncio.'),
    ('anuncio', 'Nível 3 — Anúncios (um bloco para cada MLB)',
     'O que cada anúncio tem de seu: título, status, preço, tipo logístico... Cada MLB (e cada '
     'variação) tem o seu bloco. Nada de um anúncio é misturado com o de outro.'),
)

BLOCOS_FULL = {
    'produto': (
        ('produto_cadastro', 'Cadastro do produto', 'Identificação do produto no sistema (tabela Produto).'),
        ('produto_erp', 'Situação no ERP', 'Estoque, situação e imagem do produto no cadastro.'),
    ),
    'codigo': (
        ('identificacao', 'Quem é o código', 'Identificadores do Código ML no Full.'),
        ('estoque', 'Estoque', 'REPOS dá o total; ESTOQUE separa o que está disponível do que não está.'),
        ('vendas', 'Vendas', 'As vendas do Full que a tela mostra no resumo e no gráfico semanal.'),
        ('decisao', 'O que fazer', 'Urgência, sugestão e a recomendação de reposição.'),
        ('so_tela', 'Só existe na tela', 'Itens da página do ML que nenhuma das APIs usadas aqui entrega.'),
    ),
    'anuncio': (
        ('anuncio_identificacao', 'Identificação do anúncio',
         'Quem é este anúncio. Lado a lado: o que o arquivo guarda (ARQUIVO) e o que está no banco (BANCO).'),
        ('anuncio_sku', 'SKU e produto',
         'O SKU liga o anúncio ao produto do Nível 1.'),
        ('anuncio_situacao', 'Situação e tipo',
         'Status, tipo do anúncio e catálogo.'),
        ('anuncio_quantidades', 'Quantidades do anúncio',
         'Estoque e vendas guardados NESTE anúncio.'),
        ('anuncio_preco', 'Preço', 'Preço e promoções deste anúncio.'),
        ('anuncio_logistica', 'Logística e dimensões', 'Tipo de envio, Flex e medidas deste anúncio.'),
        ('anuncio_full', 'Ligação com o Full',
         'Os códigos que ligam este anúncio ao Nível 2 (Código ML do Full).'),
        ('anuncio_familia', 'Família, categoria e relações', 'Como o ML agrupa e classifica este anúncio.'),
        ('anuncio_datas', 'Datas', 'Criação, atualização e encerramento.'),
        ('anuncio_fotos', 'Fotos', 'Imagens deste anúncio.'),
        ('anuncio_so_tela', 'Só existe na tela',
         'O que a página Anúncios do ML mostra e nenhuma fonte desta ficha entrega.'),
    ),
}


def _campo(bloco, fonte, caminho, nome, formato='texto', **extra):
    return {'bloco': bloco, 'fonte': fonte, 'caminho': caminho, 'nome': nome, 'formato': formato, **extra}


_SO_COM_VARIACAO = 'Só existe quando o anúncio tem variações.'
_SO_COM_DESCONTO = 'Só existe quando há desconto ativo (o preço "de", riscado).'

CATALOGO_FULL = (
    # ===================== NÍVEL 1 — PRODUTO (BANCO) =====================
    _campo('produto_cadastro', 'BANCO', 'produto.sku', 'SKU do produto',
           explicacao='É a chave que liga o produto aos anúncios.'),
    _campo('produto_cadastro', 'BANCO', 'produto.titulo', 'Título do produto',
           explicacao='O título do cadastro do sistema. Cada anúncio tem o seu próprio título (Nível 3).'),
    _campo('produto_cadastro', 'BANCO', 'produto.ean', 'EAN'),
    _campo('produto_cadastro', 'BANCO', 'produto.marca', 'Marca'),
    _campo('produto_cadastro', 'BANCO', 'produto.categoria', 'Categoria (do cadastro)'),
    _campo('produto_cadastro', 'BANCO', 'produto.cod_fabricante', 'Código do fabricante'),
    _campo('produto_cadastro', 'BANCO', 'produto.ncm', 'NCM'),
    _campo('produto_cadastro', 'BANCO', 'produto.curva', 'Curva'),
    _campo('produto_erp', 'BANCO', 'produto.estoque', 'Estoque no cadastro (un.)', 'inteiro'),
    _campo('produto_erp', 'BANCO', 'produto.ativo_no_erp', 'Ativo no ERP?', 'sim_nao'),
    _campo('produto_erp', 'BANCO', 'produto.imagem_url', 'Imagem principal do produto'),

    # ===================== NÍVEL 2 — CÓDIGO ML DO FULL =====================
    # --- Quem é o código ---
    _campo('identificacao', 'REPOS', 'identifiers.inventory_id', 'Código ML (inventory_id)'),
    _campo('identificacao', 'REPOS', 'identifiers.user_product_id', 'Produto do vendedor (user_product_id)'),
    _campo('identificacao', 'REPOS', 'identifiers.seller_sku', 'SKU'),
    _campo('identificacao', 'REPOS', 'product.tags', 'ESTRELA', 'estrela'),
    # --- Estoque ---
    _campo('estoque', 'REPOS', 'stock.total_stock', 'Aptas e a caminho', 'inteiro'),
    _campo('estoque', 'ESTOQUE', 'total', 'Total no estoque do Full', 'inteiro'),
    _campo('estoque', 'ESTOQUE', 'available_quantity', 'Disponível para venda', 'inteiro'),
    _campo('estoque', 'ESTOQUE', 'not_available_quantity', 'Indisponível (total)', 'inteiro'),
    _campo('estoque', 'ESTOQUE', 'not_available_detail', 'Indisponível (motivo)', 'motivos'),
    _campo('estoque', 'REPOS', 'stock.minimum_distributable_stock',
           'Mínimo (unidades mínimas para envios rápidos)', 'inteiro'),
    _campo('estoque', 'TELA', 'aptas_e_a_caminho_separados', 'Aptas  /  A caminho (separados)', 'tela',
           nota='Só na tela. A API de reposição dá só o total (Aptas e a caminho).'),
    _campo('estoque', 'TELA', 'deposito', 'Depósito', 'tela',
           nota=('Aparece nas páginas Anúncios e Controle de estoque do ML. Em OPXW24140 apareceu 30 em cada um '
                 'dos 2 anúncios. Ainda não achamos a API que entrega.')),
    _campo('estoque', 'TELA', 'controle_de_estoque_colunas', 'Colunas do "Controle de estoque"', 'tela',
           nota='Falta mapear de qual API vem cada coluna.'),
    # --- Vendas ---
    _campo('vendas', 'REPOS', 'sales.sales_totals.units_sold[0].full', 'Vendas no Full — últ. 30 dias (un.)', 'vendas'),
    _campo('vendas', 'REPOS', 'sales.sales_totals.gmv[0].full',
           'Valor vendido no Full (a tela mostra sem centavos)', 'moeda'),
    _campo('vendas', 'REPOS', 'sales.sales_history', 'Histórico de vendas semanais', 'semanas'),
    _campo('vendas', 'TELA', 'tendencia', 'Tendência', 'tela', nota='Só na tela. Ex.: "Sem tendência identificada".'),
    # --- O que fazer ---
    _campo('decisao', 'REPOS', 'stock.shipping_urgency', 'Urgência de envio', 'urgencia'),
    _campo('decisao', 'REPOS', 'recommendation.suggested_quantity', 'Sugestão de envio', 'sugestao'),
    _campo('decisao', 'REPOS', 'recommendation.recommendation_type',
           'Observações (ex.: "Recomendamos não repor, pois você tem estoque antigo impactando suas métricas.")',
           'recomendacao'),
    _campo('decisao', 'REPOS', 'recommendation.replenishment_deadline', 'Prazo para repor'),
    _campo('decisao', 'REPOS', 'recommendation.replenishment_frequency', 'Frequência de reposição (semanas)', 'inteiro'),
    _campo('decisao', 'REPOS', 'eligibility_benefits', '"Sem isenção em estoque antigo"', 'beneficios'),
    # --- Só na tela ---
    _campo('so_tela', 'TELA', 'tamanho_do_produto', 'Tamanho do produto', 'tela',
           nota='PEQUENO / MÉDIO / GRANDE / EXTRAGRANDE — só na tela.'),
    _campo('so_tela', 'TELA', 'cor_e_tamanho', 'Cor e tamanho (ex.: "Amarelo")', 'tela',
           nota=('O arquivo guarda a variação de cada anúncio em variacao_atributos (Nível 3), '
                 'mas não há um campo "cor" separado.')),
    _campo('so_tela', 'TELA', 'mais_n_identificadores', '"+ N identificadores"', 'tela',
           nota='Ainda não sabemos o que são: o texto aparece ao passar o mouse e o HTML salvo não guarda.'),
    _campo('so_tela', 'TELA', 'limites_de_envio', 'Limites "Você pode enviar até N un."', 'tela',
           nota=('São da CONTA (1 para pequenos/médios, outro para grandes/extragrandes) e mudam entre '
                 'capturas — não são do produto.')),
    _campo('so_tela', 'TELA', 'cartoes_do_topo', 'Cartões do topo da página', 'tela',
           nota=('Contagens por urgência (ex.: "ENVIE 48 — Esta semana", sendo 2 Estrela e 46 Outros) '
                 'e o resumo de Estrela (ex.: "6 dos seus 12 produtos Estrela ficaram acima do estoque '
                 'mínimo nos últimos 30 dias.") — só na tela.')),

    # ===================== NÍVEL 3 — ANÚNCIO (um bloco por MLB) =====================
    # --- Identificação do anúncio ---
    _campo('anuncio_identificacao', 'ARQUIVO', 'mlb', 'Código do anúncio (MLB)'),
    _campo('anuncio_identificacao', 'BANCO', 'anuncio.mlb', 'Código do anúncio (MLB)'),
    _campo('anuncio_identificacao', 'ARQUIVO', 'title', 'Título do anúncio'),
    _campo('anuncio_identificacao', 'BANCO', 'anuncio.titulo_anuncio', 'Título do anúncio'),
    _campo('anuncio_identificacao', 'ARQUIVO', 'permalink', 'Link do anúncio'),
    _campo('anuncio_identificacao', 'BANCO', 'anuncio.permalink', 'Link do anúncio'),
    _campo('anuncio_identificacao', 'ARQUIVO', 'condition', 'Condição (condition)'),
    _campo('anuncio_identificacao', 'ARQUIVO', 'tem_variacoes', 'O anúncio tem variações?', 'sim_nao'),
    _campo('anuncio_identificacao', 'ARQUIVO', 'variacao_id', 'Código da variação', nota_vazio=_SO_COM_VARIACAO),
    _campo('anuncio_identificacao', 'BANCO', 'variacao.variacao_id', 'Código da variação',
           explicacao='Quando o anúncio não tem variação, o sistema usa o próprio MLB como código da variação.'),
    _campo('anuncio_identificacao', 'ARQUIVO', 'variacao_atributos', 'Variação (ex.: cor)', nota_vazio=_SO_COM_VARIACAO),
    _campo('anuncio_identificacao', 'BANCO', 'variacao.atributos', 'Variação (ex.: cor)', nota_vazio=_SO_COM_VARIACAO),
    # --- SKU e produto ---
    _campo('anuncio_sku', 'ARQUIVO', 'sku', 'SKU do anúncio'),
    _campo('anuncio_sku', 'BANCO', 'variacao.sku_ml', 'SKU do anúncio'),
    _campo('anuncio_sku', 'BANCO', 'variacao.produto', 'Produto ligado a esta variação (SKU do Produto)',
           explicacao='Só é preenchido quando o SKU do anúncio existe no cadastro de produtos.',
           nota_vazio='Nenhum Produto do cadastro tem o SKU deste anúncio (ou o anúncio não tem SKU).'),
    # --- Situação e tipo ---
    _campo('anuncio_situacao', 'ARQUIVO', 'status', 'Status do anúncio', 'status_anuncio'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.tipo_de_anuncio.status', 'Status do anúncio', 'status_anuncio'),
    _campo('anuncio_situacao', 'ARQUIVO', 'sub_status', 'Subestado (sub_status)', 'json_curto',
           explicacao='O arquivo guarda esta lista como texto JSON.'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.atributos_ml_status', 'Status na última leitura de características',
           'status_anuncio',
           explicacao='Gravado numa leitura de características (outro momento): pode diferir do status do arquivo.'),
    _campo('anuncio_situacao', 'ARQUIVO', 'listing_type_id', 'Tipo de anúncio (Clássico / Premium)', 'tipo_anuncio'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.tipo_de_anuncio.tipo_anuncio', 'Tipo de anúncio (Clássico / Premium)',
           'tipo_anuncio'),
    _campo('anuncio_situacao', 'ARQUIVO', 'catalog_listing', 'Anúncio de catálogo?', 'sim_nao'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.catalog_listing', 'Anúncio de catálogo?', 'sim_nao'),
    _campo('anuncio_situacao', 'ARQUIVO', 'catalog_product_id', 'Produto de catálogo (catalog_product_id)'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.catalog_product_id', 'Produto de catálogo (catalog_product_id)'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.tipo_de_anuncio.classificacao_catalogo',
           'Classificação de catálogo (Simples / Base / Catálogo)', 'classificacao_catalogo'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.tipo_de_anuncio.nome', 'Tipo de anúncio no sistema (nome)',
           explicacao=('Linha da tabela TipoDeAnuncioMercadoLivre, que junta status, tipo, logística, '
                       'catálogo e Flex.'),
           nota_vazio='Esta linha de tipo não tem nome preenchido.'),
    _campo('anuncio_situacao', 'BANCO', 'anuncio.eh_fossil_migracao', 'Anúncio "fóssil" de migração de variações?',
           'sim_nao',
           explicacao='Marca os anúncios antigos encerrados que carregam histórico de uma migração de variações do ML.'),
    _campo('anuncio_situacao', 'ARQUIVO', 'tags', 'Tags do anúncio (tags)', 'json_curto',
           explicacao='O arquivo guarda esta lista como texto JSON.'),
    _campo('anuncio_situacao', 'ARQUIVO', 'ga_status', 'Status na lista de MLBs (ga_status)',
           explicacao='Vem da lista_mlbs.json (comando buscar_mlbs), não do GET /items.'),
    _campo('anuncio_situacao', 'ARQUIVO', 'ga_logistica', 'Logística na lista de MLBs (ga_logistica)',
           explicacao='Vem da lista_mlbs.json (comando buscar_mlbs), não do GET /items.'),
    _campo('anuncio_situacao', 'ARQUIVO', 'ga_tipo', 'Tipo na lista de MLBs (ga_tipo)',
           explicacao='Vem da lista_mlbs.json (comando buscar_mlbs), não do GET /items.'),
    _campo('anuncio_situacao', 'ARQUIVO', 'ga_catalogo', 'Catálogo na lista de MLBs (ga_catalogo)',
           explicacao='Vem da lista_mlbs.json (comando buscar_mlbs), não do GET /items.'),
    # --- Quantidades ---
    _campo('anuncio_quantidades', 'ARQUIVO', 'available_quantity', 'Estoque do anúncio', 'inteiro',
           explicacao='No Full, o mesmo estoque aparece em cada anúncio do mesmo Código ML — não some os anúncios.'),
    _campo('anuncio_quantidades', 'BANCO', 'variacao.estoque', 'Estoque do anúncio', 'inteiro'),
    _campo('anuncio_quantidades', 'ARQUIVO', 'sold_quantity', 'Vendidos no anúncio (sold_quantity)', 'inteiro'),
    _campo('anuncio_quantidades', 'BANCO', 'variacao.qtd_vendas', 'Vendidos no anúncio', 'inteiro'),
    _campo('anuncio_quantidades', 'ARQUIVO', 'initial_quantity', 'Quantidade inicial (initial_quantity)', 'inteiro'),
    # --- Preço ---
    _campo('anuncio_preco', 'ARQUIVO', 'price', 'Preço atual', 'preco'),
    _campo('anuncio_preco', 'BANCO', 'variacao.preco_atual', 'Preço atual', 'preco'),
    _campo('anuncio_preco', 'ARQUIVO', 'original_price', 'Preço original ("de")', 'preco', nota_vazio=_SO_COM_DESCONTO),
    _campo('anuncio_preco', 'BANCO', 'variacao.preco_original', 'Preço original ("de")', 'preco', nota_vazio=_SO_COM_DESCONTO),
    _campo('anuncio_preco', 'ARQUIVO', 'base_price', 'Preço base (base_price)', 'preco'),
    _campo('anuncio_preco', 'ARQUIVO', 'differential_pricing', 'Preço diferenciado (differential_pricing)', 'json_curto'),
    _campo('anuncio_preco', 'ARQUIVO', 'deal_ids', 'Promoções (deal_ids)', 'json_curto',
           explicacao='O arquivo guarda esta lista como texto JSON.'),
    # --- Logística ---
    _campo('anuncio_logistica', 'ARQUIVO', 'logistic_type', 'Tipo logístico', 'tipo_logistico'),
    _campo('anuncio_logistica', 'BANCO', 'anuncio.tipo_de_anuncio.tipo_logistico', 'Tipo logístico', 'tipo_logistico'),
    _campo('anuncio_logistica', 'ARQUIVO', 'flex', 'Flex', 'sim_nao',
           explicacao='Calculado pelo buscar_detalhes: "sim" quando shipping_tags tem "self_service_in".'),
    _campo('anuncio_logistica', 'BANCO', 'anuncio.tipo_de_anuncio.flex', 'Flex', 'sim_nao'),
    _campo('anuncio_logistica', 'ARQUIVO', 'free_shipping', 'Frete grátis (free_shipping)', 'sim_nao'),
    _campo('anuncio_logistica', 'ARQUIVO', 'shipping_tags', 'Tags do envio (shipping_tags)', 'json_curto',
           explicacao='O arquivo guarda esta lista como texto JSON.'),
    _campo('anuncio_logistica', 'ARQUIVO', 'shipping_dim_width', 'Largura do envio (shipping.dimensions.width)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'shipping_dim_height', 'Altura do envio (shipping.dimensions.height)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'shipping_dim_length', 'Comprimento do envio (shipping.dimensions.length)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'shipping_dim_weight', 'Peso do envio (shipping.dimensions.weight)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'attr_seller_package_height', 'Altura do pacote declarada (SELLER_PACKAGE_HEIGHT)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'attr_seller_package_width', 'Largura do pacote declarada (SELLER_PACKAGE_WIDTH)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'attr_seller_package_length', 'Comprimento do pacote declarado (SELLER_PACKAGE_LENGTH)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'attr_seller_package_weight', 'Peso do pacote declarado (SELLER_PACKAGE_WEIGHT)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'attr_dimensions', 'Dimensões (atributo DIMENSIONS)'),
    _campo('anuncio_logistica', 'ARQUIVO', 'attr_weight', 'Peso (atributo WEIGHT)'),
    # --- Ligação com o Full ---
    _campo('anuncio_full', 'ARQUIVO', 'inventory_id', 'Código ML (inventory_id) deste anúncio'),
    _campo('anuncio_full', 'ARQUIVO', 'user_product_id', 'Produto do vendedor (user_product_id) deste anúncio'),
    _campo('anuncio_full', 'BANCO', 'variacao.mlbu', 'Produto do vendedor (mlbu) desta variação',
           explicacao='O banco guarda o user_product_id com o nome mlbu. O banco não guarda o inventory_id.'),
    # --- Família, categoria e relações ---
    _campo('anuncio_familia', 'ARQUIVO', 'family_name', 'Nome da família (family_name)'),
    _campo('anuncio_familia', 'ARQUIVO', 'family_id', 'Código da família (family_id)'),
    _campo('anuncio_familia', 'ARQUIVO', 'item_relations', 'Relações do anúncio (item_relations)', 'json_curto',
           explicacao='O arquivo guarda esta lista como texto JSON.'),
    _campo('anuncio_familia', 'BANCO', 'anuncio.item_relations', 'Relações do anúncio (item_relations)', 'json_curto'),
    _campo('anuncio_familia', 'ARQUIVO', 'parent_item_id', 'Anúncio pai (parent_item_id)'),
    _campo('anuncio_familia', 'ARQUIVO', 'category_id', 'Categoria do ML (category_id)'),
    _campo('anuncio_familia', 'BANCO', 'variacao.categoria.category_id', 'Categoria do ML (da variação)'),
    _campo('anuncio_familia', 'BANCO', 'variacao.categoria.nome', 'Nome da categoria do ML (da variação)'),
    _campo('anuncio_familia', 'BANCO', 'anuncio.atributos_ml_categoria_id', 'Categoria na última leitura de características',
           explicacao='Gravada numa leitura de características (outro momento): pode diferir da categoria da variação.'),
    _campo('anuncio_familia', 'ARQUIVO', 'domain_id', 'Domínio (domain_id)'),
    _campo('anuncio_familia', 'ARQUIVO', 'warranty', 'Garantia (warranty)'),
    # --- Datas ---
    _campo('anuncio_datas', 'ARQUIVO', 'date_created', 'Criado em (date_created)'),
    _campo('anuncio_datas', 'BANCO', 'anuncio.data_criacao_ml', 'Criado em'),
    _campo('anuncio_datas', 'ARQUIVO', 'last_updated', 'Última atualização (last_updated)'),
    _campo('anuncio_datas', 'BANCO', 'anuncio.ultima_atualizacao_ml', 'Última atualização'),
    _campo('anuncio_datas', 'ARQUIVO', 'start_time', 'Início (start_time)'),
    _campo('anuncio_datas', 'ARQUIVO', 'stop_time', 'Parada (stop_time)'),
    _campo('anuncio_datas', 'ARQUIVO', 'end_time', 'Fim (end_time)'),
    _campo('anuncio_datas', 'ARQUIVO', 'expiration_time', 'Expiração (expiration_time)'),
    # --- Fotos ---
    _campo('anuncio_fotos', 'ARQUIVO', 'thumbnail', 'Miniatura (thumbnail)'),
    _campo('anuncio_fotos', 'ARQUIVO', 'imagem_principal', 'Imagem principal'),
    _campo('anuncio_fotos', 'ARQUIVO', 'pictures', 'Fotos do anúncio (pictures)', 'quantidade_fotos'),
    _campo('anuncio_fotos', 'ARQUIVO', 'variacao_num_fotos', 'Fotos da variação', 'inteiro', nota_vazio=_SO_COM_VARIACAO),
    _campo('anuncio_fotos', 'BANCO', 'variacao.num_fotos', 'Fotos da variação', 'inteiro'),
    # --- Só na tela (página Anúncios) ---
    _campo('anuncio_so_tela', 'TELA', 'anuncio_full_na_tela', 'Full mostrado na linha deste anúncio', 'tela',
           nota=('Aparece na página Anúncios do ML. Em OPXW24140 os 2 anúncios mostraram o mesmo Full (95). '
                 'Confira se isso vale para qualquer código com mais de 1 anúncio.')),
    _campo('anuncio_so_tela', 'TELA', 'anuncio_deposito_na_tela', 'Depósito mostrado na linha deste anúncio', 'tela',
           nota=('Aparece na página Anúncios do ML. Em OPXW24140 os 2 anúncios mostraram o mesmo Depósito (30). '
                 'Confira se isso vale para qualquer código com mais de 1 anúncio.')),
)


def chave_campo(fonte: str, caminho: str) -> str:
    return f'{fonte}|{caminho}'


CHAVES_VALIDAS = {chave_campo(c['fonte'], c['caminho']) for c in CATALOGO_FULL}
assert len(CHAVES_VALIDAS) == len(CATALOGO_FULL), 'O catálogo da ficha tem um campo (fonte + caminho) repetido.'


# ---------------------------------------------------------------------------
# O CÓDIGO DIGITADO
# ---------------------------------------------------------------------------
_PADRAO_CODIGO = re.compile(r'^#?[A-Za-z0-9_-]{1,39}$')


# Função Objetivo: Normaliza o que o usuário digitou. "opxw24140 " -> ("OPXW24140",
# "inventory_id", "OPXW24140"); "#5838589786" -> ("#5838589786", "mlb", "MLB5838589786").
# Devolve (None, None, None) se o texto não parece um código.
def interpretar_codigo(texto):
    codigo = str(texto or '').strip().upper()
    if not _PADRAO_CODIGO.match(codigo):
        return None, None, None
    if codigo.startswith('#'):
        digitos = re.sub(r'\D', '', codigo)
        if not digitos:
            return None, None, None
        return f'#{digitos}', 'mlb', f'MLB{digitos}'
    return codigo, 'inventory_id', codigo


# ---------------------------------------------------------------------------
# LER VALORES DO JSON CRU
# ---------------------------------------------------------------------------
_PEDACOS_CAMINHO = re.compile(r'([^.\[\]]+)|\[(\d+)\]')


# * [EXPLICAÇÃO] → _AUSENTE marca "esse campo nem existe na resposta". É diferente de
#                  o campo existir com o valor null — a ficha mostra as duas
#                  situações separadas em "Como veio da API".
_AUSENTE = object()


# Função Objetivo: _descer(dados, "sales.sales_totals.units_sold[0].full") — desce pelo
# caminho e devolve o valor CRU (None se a API mandou null) ou _AUSENTE se algum nível
# do caminho não existe. Nunca quebra.
def _descer(dados, caminho):
    atual = dados
    for nome, indice in _PEDACOS_CAMINHO.findall(caminho):
        if indice != '':
            if not isinstance(atual, list) or int(indice) >= len(atual):
                return _AUSENTE
            atual = atual[int(indice)]
        else:
            if not isinstance(atual, dict) or nome not in atual:
                return _AUSENTE
            atual = atual[nome]
    return atual


# Função Objetivo: pegar(dados, "sales.sales_totals.units_sold[0].full") — desce
# pelo caminho sem quebrar quando algum nível é null/ausente (devolve None).
def pegar(dados, caminho):
    valor = _descer(dados, caminho)
    return None if valor is _AUSENTE else valor


def _n_br(valor):
    """1234 -> '1.234'   |   88848.09 -> '88.848,09'"""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return str(valor)
    if isinstance(valor, int):
        return f'{valor:,}'.replace(',', '.')
    return f'{valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _data_curta(texto):
    """'2026-08-25' -> '25/08'."""
    partes = str(texto or '').split('-')
    return f'{partes[2]}/{partes[1]}' if len(partes) == 3 else str(texto or '—')


# ---------------------------------------------------------------------------
# FORMATOS DE EXIBIÇÃO — cada um devolve (texto, nota)
# ---------------------------------------------------------------------------
def _fmt_texto(valor, dados):
    return str(valor), ''


def _fmt_inteiro(valor, dados):
    return _n_br(valor), ''


def _fmt_moeda(valor, dados):
    moeda = pegar(dados, 'sales.sales_totals.currency')
    return f'R$ {_n_br(valor)}', (f'({moeda})' if moeda else '')


def _fmt_vendas(valor, dados):
    periodo = pegar(dados, 'sales.sales_totals.period')
    return f'{_n_br(valor)} un.', (f'(período = {periodo})' if periodo else '')


def _fmt_estrela(valor, dados):
    if not isinstance(valor, list):
        return str(valor), ''
    return ('SIM' if 'star_product' in valor else 'não'), f'(tags: {", ".join(str(t) for t in valor) or "nenhuma"})'


def _fmt_motivos(valor, dados):
    if not isinstance(valor, list) or not valor:
        return 'nenhuma unidade indisponível', ''
    partes = []
    for item in valor:
        if isinstance(item, dict):
            status = item.get('status')
            partes.append(f"{status} = {item.get('quantity')} ({MOTIVO_INDISPONIVEL.get(status, 'motivo não traduzido')})")
    return '; '.join(partes) or 'nenhuma unidade indisponível', ''


def _fmt_urgencia(valor, dados):
    return str(valor), f"(= {URGENCIA.get(valor, 'valor não traduzido')})"


def _fmt_recomendacao(valor, dados):
    return str(valor), f"(= {RECOMENDACAO.get(valor, 'valor não traduzido')})"


def _fmt_sugestao(valor, dados):
    if isinstance(valor, dict) and valor.get('type') == 'exact':
        return f"{_n_br(valor.get('value'))} un.", '(exata)'
    if isinstance(valor, dict) and valor.get('type') == 'range':
        return f"de {_n_br(valor.get('min'))} a {_n_br(valor.get('max'))} un.", '(faixa)'
    return str(valor), ''


def _fmt_beneficios(valor, dados):
    if isinstance(valor, list) and not valor:
        return 'nenhum benefício (lista vazia)', ''
    if isinstance(valor, list):
        return ', '.join(str(v) for v in valor), '(AGING = estoque antigo)' if 'AGING' in valor else ''
    return str(valor), ''


def _fmt_semanas(valor, dados):
    semanas = _ordenar_semanas(valor)
    if not semanas:
        return 'sem semanas na resposta', ''
    return ' · '.join(_n_br(s.get('units_sold')) for s in semanas), '(un. vendidas por semana, da mais antiga para a mais nova)'


def _fmt_preco(valor, dados):
    """89.9 -> 'R$ 89,90'   |   '1234.50' (texto do banco) -> 'R$ 1.234,50'."""
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        return str(valor), ''
    return 'R$ ' + f'{numero:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.'), ''


def _fmt_sim_nao(valor, dados):
    return _sim_nao(valor), ''


def _traduzir(grupo, valor):
    return f"(= {_rotulos_do_tipo_de_anuncio()[grupo].get(valor, 'valor não traduzido')})"


def _fmt_status_anuncio(valor, dados):
    return str(valor), _traduzir('status', valor)


def _fmt_tipo_anuncio(valor, dados):
    return str(valor), _traduzir('tipo_anuncio', valor)


def _fmt_tipo_logistico(valor, dados):
    return str(valor), _traduzir('tipo_logistico', valor)


def _fmt_classificacao_catalogo(valor, dados):
    return str(valor), _traduzir('classificacao_catalogo', valor)


# * [EXPLICAÇÃO] → O buscar_detalhes grava algumas listas como TEXTO JSON (sub_status, tags,
#                  shipping_tags, deal_ids, item_relations); o banco guarda item_relations como
#                  JSON de verdade. Aqui as duas formas viram o mesmo texto curto de leitura.
def _fmt_json_curto(valor, dados):
    nota = ''
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
            nota = '(estava guardado como texto JSON)'
        except ValueError:
            return valor, ''
    if isinstance(valor, (list, dict)) and not valor:
        return ('lista vazia' if isinstance(valor, list) else 'vazio'), nota
    if isinstance(valor, list) and all(not isinstance(i, (list, dict)) for i in valor):
        return ', '.join(str(i) for i in valor), nota
    return json.dumps(valor, ensure_ascii=False), nota


def _fmt_quantidade_fotos(valor, dados):
    if not isinstance(valor, list):
        return str(valor), ''
    return f"{len(valor)} {'foto' if len(valor) == 1 else 'fotos'}", ''


FORMATOS = {
    'texto': _fmt_texto, 'inteiro': _fmt_inteiro, 'moeda': _fmt_moeda, 'vendas': _fmt_vendas,
    'estrela': _fmt_estrela, 'motivos': _fmt_motivos, 'urgencia': _fmt_urgencia,
    'recomendacao': _fmt_recomendacao, 'sugestao': _fmt_sugestao, 'beneficios': _fmt_beneficios,
    'semanas': _fmt_semanas, 'preco': _fmt_preco, 'sim_nao': _fmt_sim_nao,
    'status_anuncio': _fmt_status_anuncio, 'tipo_anuncio': _fmt_tipo_anuncio,
    'tipo_logistico': _fmt_tipo_logistico, 'classificacao_catalogo': _fmt_classificacao_catalogo,
    'json_curto': _fmt_json_curto, 'quantidade_fotos': _fmt_quantidade_fotos,
}


def _ordenar_semanas(valor):
    """A API manda da semana mais NOVA para a mais antiga; a tela mostra da mais antiga para a mais nova."""
    if not isinstance(valor, list):
        return []
    return sorted((s for s in valor if isinstance(s, dict)), key=lambda s: str(s.get('start_date')))


# ---------------------------------------------------------------------------
# O VALOR DE CADA FONTE
# ---------------------------------------------------------------------------
VAZIO = '— (vazio)'


def _valor_api(entrada, pacote):
    """(estado, texto, nota) de uma linha cuja fonte é uma API (REPOS ou ESTOQUE)."""
    if pacote is None:
        return 'sem_chamada', 'não consultado', 'Não havia o que consultar para este código.'
    if pacote.get('erro') or pacote.get('dados') is None:
        return 'erro', 'a consulta falhou', str(pacote.get('erro') or 'sem resposta')
    valor = pegar(pacote['dados'], entrada['caminho'])
    if valor is None:
        return 'vazio', VAZIO, ''
    texto, nota = FORMATOS[entrada['formato']](valor, pacote['dados'])
    return 'ok', texto, nota


# * [EXPLICAÇÃO] → Quando o anúncio tem variações, o buscar_detalhes (DetalhesML._processar_item) grava 1 registro
#                  POR VARIAÇÃO, mas só estes campos são trocados pelos da variação; todos os outros são copiados
#                  do anúncio inteiro e se repetem iguais em cada variação.
CAMPOS_DA_VARIACAO_NO_ARQUIVO = {
    'variacao_id', 'variacao_atributos', 'variacao_num_fotos', 'sku', 'price', 'available_quantity', 'sold_quantity',
    'inventory_id', 'user_product_id', 'catalog_product_id', 'item_relations',
}
NOTA_DO_ANUNCIO_INTEIRO = ('Valor do anúncio inteiro: com variações, o arquivo repete o mesmo valor em cada variação '
                           '(só preço, estoque, vendidos, SKU, códigos do Full, fotos e cor são da variação).')


def _valor_arquivo(entrada, registro):
    """(estado, texto, nota) de uma linha cuja fonte é o detalhes_mlbs.json — de 1 registro (1 anúncio ou 1 variação)."""
    if registro is None:
        return 'sem_chamada', 'sem registro no arquivo', 'O detalhes_mlbs.json não tem este anúncio.'
    campo = entrada['caminho']
    valor = registro.get(campo, _AUSENTE)
    if valor is _AUSENTE:
        return 'vazio', VAZIO, f'Este registro do arquivo não tem a chave "{campo}".'
    anuncio_inteiro = registro.get('variacao_id') is not None and campo not in CAMPOS_DA_VARIACAO_NO_ARQUIVO
    if valor is None:
        nota = entrada.get('nota_vazio') or 'O arquivo tem a chave, mas o valor é null.'
        return 'vazio', VAZIO, f'{nota} {NOTA_DO_ANUNCIO_INTEIRO}' if anuncio_inteiro else nota
    texto, nota = FORMATOS[entrada['formato']](valor, registro)
    if anuncio_inteiro:
        nota = f'{nota} {NOTA_DO_ANUNCIO_INTEIRO}' if nota else NOTA_DO_ANUNCIO_INTEIRO
    return 'ok', texto, nota


# Função Objetivo: (estado, texto, nota) de uma linha cuja fonte é o BANCO. "pacote" =
# {"dados": {"anuncio": {...} ou None, "variacao": {...} ou None}, "procurou": {"anuncio": "texto do filtro", ...}}.
# O primeiro pedaço do caminho ("anuncio", "variacao" ou "produto") diz em qual linha do banco olhar.
def _valor_banco(entrada, pacote):
    if pacote is None:
        return 'sem_chamada', 'o banco não foi lido', 'A ficha foi montada sem ler o banco.'
    raiz = entrada['caminho'].split('.')[0]
    if (pacote.get('dados') or {}).get(raiz) is None:
        return 'nao_achou', 'não encontrado no banco', f"Procurei: {(pacote.get('procurou') or {}).get(raiz, raiz)}."
    valor = pegar(pacote['dados'], entrada['caminho'])
    if valor is None:
        return 'vazio', VAZIO, entrada.get('nota_vazio') or 'O banco tem a linha, mas este campo está vazio (null).'
    texto, nota = FORMATOS[entrada['formato']](valor, pacote['dados'])
    return 'ok', texto, nota


# ---------------------------------------------------------------------------
# "COMO VEIO DA API" — o dado CRU de cada linha, de cada fonte e de cada tabela
# ---------------------------------------------------------------------------
# * [EXPLICAÇÃO] → A ficha mostra o valor "traduzido" (ex.: NO_REPLENISHMENT = não repor).
#                  Para conferir, ao lado dele fica o trecho EXATO que o ML mandou, do
#                  jeito que está guardado no banco: o campo e o bloco em volta dele
#                  (assim dá para ver se há outros campos ao lado, como um texto).
#                  Só muda a formatação (quebras de linha para ler) — nada é renomeado
#                  nem corrigido. O ARQUIVO é diferente: não é a resposta crua do ML,
#                  é o que o comando buscar_detalhes extraiu e gravou no detalhes_mlbs.json.
#                  E o BANCO é diferente de novo: é a linha da tabela do sistema ("Como está
#                  no banco"), não uma resposta do ML.
ROTULO_BRUTO_API = 'Como veio da API'
ROTULO_BRUTO_ARQUIVO = 'Como está no arquivo'
ROTULO_BRUTO_BANCO = 'Como está no banco'
NOTA_ORDEM_DAS_CHAVES = ('O conteúdo é o que foi guardado do ML. Só a ordem das chaves pode aparecer '
                         'diferente da original, porque o banco (MySQL) reordena as chaves de campos JSON.')
NOTA_ARQUIVO = ('O arquivo guarda os campos que o buscar_detalhes tirou do ML; alguns nomes '
                '(mlb, variacao_atributos) são do nosso projeto, não do ML.')
NOTA_BANCO = ('Linha da tabela do sistema, só lida (nada é gravado). Números decimais e datas aparecem como '
              'texto; variacao.produto é o SKU do Produto ligado.')


def _json_legivel(valor):
    return json.dumps(valor, ensure_ascii=False, indent=2, default=str)


def _bruto(rotulo, nota, partes):
    return {'rotulo': rotulo, 'nota': nota, 'partes': partes}


# Função Objetivo: O trecho CRU que gerou uma linha: o campo exato e o bloco em volta dele (o "pai"
# do campo). Serve para a resposta de uma API e, com rotulo/origem trocados, para uma linha do banco.
# Devolve None quando não há resposta para mostrar (não consultou ou a consulta falhou — a própria
# linha já explica isso).
def _bruto_api(caminho, pacote, com_bloco=True, nota='', rotulo=ROTULO_BRUTO_API, onde='na resposta da API'):
    if not pacote or pacote.get('erro') or pacote.get('dados') is None:
        return None
    dados = pacote['dados']
    valor = _descer(dados, caminho)
    if valor is _AUSENTE:
        return _bruto(rotulo, f'O campo {caminho} não existe {onde} (nem como null).', [])
    notas = [n for n in ('Este campo veio como null.' if valor is None else '', nota) if n]
    partes = [{'titulo': 'O campo', 'texto': _json_legivel(valor)}]
    pai = caminho.rsplit('.', 1)[0] if '.' in caminho else ''
    if com_bloco and pai and not isinstance(valor, (dict, list)):
        bloco = _descer(dados, pai)
        if isinstance(bloco, (dict, list)):
            partes.append({'titulo': f'O bloco onde ele está ({pai})', 'texto': _json_legivel(bloco)})
    return _bruto(rotulo, ' '.join(notas), partes)


# Função Objetivo: O que o detalhes_mlbs.json guarda para 1 campo de 1 anúncio (1 registro).
def _bruto_arquivo(campo, registro):
    if registro is None:
        return None
    nota = NOTA_ARQUIVO
    if campo not in registro:
        nota += f' Este registro não tem a chave {campo}.'
        return _bruto(ROTULO_BRUTO_ARQUIVO, nota, [])
    return _bruto(ROTULO_BRUTO_ARQUIVO, nota, [{'titulo': 'O campo, neste anúncio', 'texto': _json_legivel({campo: registro[campo]})}])


# Função Objetivo: O que o banco guarda para 1 campo: o campo e a linha em volta dele. Se a linha nem existe
# no banco, a nota diz o que foi procurado.
def _bruto_banco(caminho, pacote):
    if not pacote:
        return None
    raiz = caminho.split('.')[0]
    if (pacote.get('dados') or {}).get(raiz) is None:
        procurou = (pacote.get('procurou') or {}).get(raiz, raiz)
        return _bruto(ROTULO_BRUTO_BANCO, f'Procurei: {procurou}. Nenhuma linha encontrada.', [])
    return _bruto_api(caminho, pacote, nota=NOTA_BANCO, rotulo=ROTULO_BRUTO_BANCO, onde='na linha do banco')


# Função Objetivo: Os registros do arquivo inteiros (cartão ARQUIVO e tabela de anúncios).
def _bruto_registros(registros, rotulo_extra=''):
    if not registros:
        return None
    return _bruto(ROTULO_BRUTO_ARQUIVO + rotulo_extra, f'{NOTA_ARQUIVO} {NOTA_ORDEM_DAS_CHAVES}',
                  [{'titulo': '', 'texto': _json_legivel(registros)}])


# Função Objetivo: A resposta COMPLETA de 1 chamada (cartões REPOS e ESTOQUE).
def _bruto_do_pacote(pacote):
    rotulo = ROTULO_BRUTO_API + ' — resposta completa'
    if pacote.get('erro'):
        return _bruto(rotulo, 'A consulta falhou; não há resposta para mostrar.',
                      [{'titulo': 'O erro', 'texto': str(pacote['erro'])}])
    if pacote.get('dados') is None:
        return None
    return _bruto(rotulo, NOTA_ORDEM_DAS_CHAVES, [{'titulo': '', 'texto': _json_legivel(pacote['dados'])}])


# Função Objetivo: Escolhe de onde tirar o dado cru de 1 linha do catálogo (TELA não tem: só existe na tela).
# "origem" é o que a fonte da linha entrega: o pacote da API, o registro do arquivo ou o pacote do banco.
def _bruto_da_linha(entrada, origem):
    fonte = entrada['fonte']
    if fonte == 'TELA':
        return None
    if fonte == 'ARQUIVO':
        return _bruto_arquivo(entrada['caminho'], origem)
    if fonte == 'BANCO':
        return _bruto_banco(entrada['caminho'], origem)
    return _bruto_api(entrada['caminho'], origem)


# ---------------------------------------------------------------------------
# A FICHA
# ---------------------------------------------------------------------------
# Função Objetivo: Junta uma entrada do catálogo com o valor lido e o que a equipe
# registrou (nome interno, situação, observação) — é 1 linha da tabela da tela.
# "origens" diz de onde cada fonte lê neste bloco: {"REPOS": pacote, "ESTOQUE": pacote,
# "ARQUIVO": 1 registro, "BANCO": pacote do banco} — só as fontes que o nível usa.
def _montar_linha(entrada, origens, validacoes, rotulos_situacao):
    fonte = entrada['fonte']
    origem = origens.get(fonte)
    if fonte == 'TELA':
        estado, texto, nota = 'so_tela', entrada['nota'], ''
    elif fonte == 'ARQUIVO':
        estado, texto, nota = _valor_arquivo(entrada, origem)
    elif fonte == 'BANCO':
        estado, texto, nota = _valor_banco(entrada, origem)
    else:
        estado, texto, nota = _valor_api(entrada, origem)

    registro = validacoes.get(chave_campo(fonte, entrada['caminho'])) or {}
    situacao = registro.get('situacao') or SITUACAO_PADRAO
    projeto = FONTES_FULL[fonte]['projeto']
    return {
        'fonte': fonte,
        'caminho': entrada['caminho'],
        'nome_na_tela': entrada['nome'],
        'explicacao': entrada.get('explicacao', ''),
        'estado': estado,
        'valor_txt': texto,
        'valor_nota': nota,
        'projeto': projeto,
        'projeto_rotulo': ROTULO_PROJETO[projeto],
        'projeto_etiqueta': etiqueta_projeto(fonte),
        'bruto': _bruto_da_linha(entrada, origem),
        'nome_interno': registro.get('nome_interno', ''),
        'situacao': situacao,
        'situacao_rotulo': rotulos_situacao.get(situacao, situacao),
        'observacao': registro.get('observacao', ''),
    }


# Função Objetivo: Os blocos de 1 nível, cada um com as linhas do catálogo que pertencem a ele.
def _montar_blocos(nivel, origens, validacoes, rotulos_situacao):
    blocos = []
    for chave_bloco, titulo, descricao in BLOCOS_FULL[nivel]:
        linhas = [_montar_linha(c, origens, validacoes, rotulos_situacao)
                  for c in CATALOGO_FULL if c['bloco'] == chave_bloco]
        blocos.append({'chave': chave_bloco, 'titulo': titulo, 'descricao': descricao, 'linhas': linhas})
    return blocos


def _inventario_do_upid(dados_rep, registros_upid, estoque):
    """Qual inventory_id pertence a este produto: o que a própria API de reposição diz; senão o do arquivo."""
    inv = pegar(dados_rep, 'identifiers.inventory_id') if dados_rep else None
    if not inv:
        inv = next((r.get('inventory_id') for r in registros_upid if r.get('inventory_id')), None)
    if not inv and len(estoque) == 1:
        inv = next(iter(estoque))
    return inv


def _sim_nao(valor):
    return ('sim' if valor else 'não') if isinstance(valor, bool) else str(valor)


def _semanas_da_tabela(dados_rep):
    linhas = []
    for s in _ordenar_semanas(pegar(dados_rep, 'sales.sales_history') if dados_rep else None):
        linhas.append({
            'periodo': f"{_data_curta(s.get('start_date'))} a {_data_curta(s.get('end_date'))}",
            'unidades': _n_br(s.get('units_sold')),
            'dias_sem_estoque': _n_br(s.get('days_out_of_stock')),
            'campanhas': _sim_nao(s.get('campaigns')),
        })
    return linhas


# ---------------------------------------------------------------------------
# NÍVEL 3 — OS ANÚNCIOS (1 registro do arquivo = 1 anúncio, ou 1 variação dele)
# ---------------------------------------------------------------------------
def _id_da_variacao(registro):
    """O mesmo código de variação que o importar_anuncios_ml usa: sem variação real, é o próprio MLB."""
    return str(registro.get('variacao_id') or registro.get('mlb') or '')


def _rotulo_do_anuncio(registro):
    mlb = str(registro.get('mlb') or '—')
    return f"{mlb} · variação {registro['variacao_id']}" if registro.get('variacao_id') else mlb


def _variacao_do_banco(banco, registro):
    if not banco:
        return None
    return banco['variacoes'].get((str(registro.get('mlb') or ''), _id_da_variacao(registro)))


# Função Objetivo: O "pacote" do banco de 1 anúncio: a linha do anúncio e a da variação, mais o texto de
# como foram procuradas (para a tela dizer o que buscou quando não achou). None se o banco não foi lido.
def _pacote_banco_do_anuncio(banco, registro):
    if banco is None:
        return None
    mlb = str(registro.get('mlb') or '')
    variacao_id = _id_da_variacao(registro)
    return {
        'dados': {'anuncio': banco['anuncios'].get(mlb), 'variacao': _variacao_do_banco(banco, registro)},
        'procurou': {
            'anuncio': f'AnuncioMercadoLivre com mlb = {mlb}',
            'variacao': f'VariacaoAnuncioMercadoLivre com anuncio.mlb = {mlb} e variacao_id = {variacao_id}',
        },
    }


def _pacote_banco_do_produto(banco, sku):
    if banco is None:
        return None
    return {'dados': {'produto': banco['produtos'].get(sku)}, 'procurou': {'produto': f'Produto com sku = {sku}'}}


def _anuncio_na_tabela(registro, ancora):
    status = registro.get('status')
    return {
        'ancora': ancora, 'mlb': registro.get('mlb'), 'variacao_id': registro.get('variacao_id') or '',
        'status': status,
        'status_rotulo': _rotulos_do_tipo_de_anuncio()['status'].get(status, '') if status else '',
        'tipo_logistico': registro.get('logistic_type'), 'estoque': registro.get('available_quantity'),
        'sku': registro.get('sku') or '', 'titulo': registro.get('title') or '',
    }


# ---------------------------------------------------------------------------
# CONFERÊNCIAS AUTOMÁTICAS — sempre entre valores do MESMO anúncio (ou do mesmo código)
# ---------------------------------------------------------------------------
def _conferencia(verificacao, igual, detalhe):
    return {'verificacao': verificacao, 'resultado': 'nao_da' if igual is None else ('igual' if igual else 'diferente'),
            'detalhe': detalhe}


def _texto_limpo(valor):
    return None if valor is None else str(valor).strip()


def _texto_maiusculo(valor):
    texto = _texto_limpo(valor)
    return None if texto is None else texto.upper()


def _decimal(valor):
    try:
        return None if valor is None else Decimal(str(valor))
    except InvalidOperation:
        return None


# * [EXPLICAÇÃO] → O ML manda datas como "2024-03-12T14:03:22.000Z" e o banco guarda o instante; para
#                  comparar, as duas viram o mesmo instante (sem os milésimos).
def _instante(valor):
    if valor is None:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00')).replace(microsecond=0)
    except ValueError:
        return None


def _mostrar(valor):
    return VAZIO if valor is None else str(valor)


# Função Objetivo: Compara 2 valores e devolve a conferência (IGUAL / DIFERENTE / NÃO DÁ PRA CONFERIR se
# algum dos 2 está vazio). normalizar deixa os dois no mesmo formato antes de comparar.
def _comparar(verificacao, rotulo_a, a, rotulo_b, b, normalizar=_texto_limpo, aviso_se_diferente=''):
    na, nb = normalizar(a), normalizar(b)
    detalhe = f'{rotulo_a} {_mostrar(a)}  •  {rotulo_b} {_mostrar(b)}'
    igual = None if (na is None or nb is None) else na == nb
    if igual is False and aviso_se_diferente:
        detalhe += f' ({aviso_se_diferente})'
    return _conferencia(verificacao, igual, detalhe)


def _lista_de_anuncios(pares):
    return ', '.join(m if v == m else f'{m} / variação {v}' for m, v in sorted(pares)) or VAZIO


# Função Objetivo: As conferências do CÓDIGO ML (nível 2) — entre REPOS, ESTOQUE e o banco. As do
# anúncio ficam em _conferencias_do_anuncio: cada anúncio é conferido sozinho.
def _conferencias_do_codigo(codigo, tipo, valor_interno, upid, dados_rep, dados_est, inventario, registros_upid, banco):
    conf = []

    if tipo == 'inventory_id':
        inv_rep = pegar(dados_rep, 'identifiers.inventory_id') if dados_rep else None
        conf.append(_comparar(f'Código digitado ({codigo}) = REPOS identifiers.inventory_id',
                              'digitado', valor_interno, 'REPOS', inv_rep, normalizar=_texto_maiusculo))

    inv_est = pegar(dados_est, 'inventory_id') if dados_est else None
    conf.append(_comparar('inventory_id: o que pedi ao ESTOQUE x o que o ESTOQUE devolveu',
                          'pedido', inventario, 'ESTOQUE', inv_est))

    total_rep = pegar(dados_rep, 'stock.total_stock') if dados_rep else None
    total_est = pegar(dados_est, 'total') if dados_est else None
    conf.append(_conferencia(
        'Total: REPOS stock.total_stock x ESTOQUE total',
        None if (total_rep is None or total_est is None) else total_rep == total_est,
        f'REPOS {_n_br(total_rep) if total_rep is not None else VAZIO}  •  '
        f'ESTOQUE {_n_br(total_est) if total_est is not None else VAZIO}'))

    disponivel = pegar(dados_est, 'available_quantity') if dados_est else None
    indisponivel = pegar(dados_est, 'not_available_quantity') if dados_est else None
    soma_ok = None not in (total_est, disponivel, indisponivel)
    conf.append(_conferencia(
        'ESTOQUE: total = disponível + indisponível',
        (total_est == disponivel + indisponivel) if soma_ok else None,
        f'{total_est} = {disponivel} + {indisponivel}' if soma_ok else VAZIO))

    no_arquivo = {(str(r.get('mlb') or ''), _id_da_variacao(r)) for r in registros_upid}
    por_mlbu = (banco or {}).get('variacoes_por_mlbu', {}).get(upid) if upid else None
    no_banco = {(v['mlb'], v['variacao_id']) for v in (por_mlbu or [])}
    conf.append(_conferencia(
        'Anúncios deste código: os do ARQUIVO são os mesmos do BANCO (variações com este mlbu)?',
        None if (banco is None or not upid or not no_arquivo) else no_arquivo == no_banco,
        f'ARQUIVO {_lista_de_anuncios(no_arquivo)}  •  BANCO {_lista_de_anuncios(no_banco)}'))
    return conf


# Função Objetivo: As conferências de 1 ANÚNCIO: o que o arquivo diz dele x o que o banco diz dele x o que o
# Código ML (REPOS/ESTOQUE) diz. Nenhuma conferência junta dados de 2 anúncios.
def _conferencias_do_anuncio(r, anuncio_banco, variacao_banco, dados_rep, dados_est, arquivo_gerado_em):
    tipo_banco = (anuncio_banco or {}).get('tipo_de_anuncio') or {}
    conf = [
        _comparar('Título: ARQUIVO title x BANCO anuncio.titulo_anuncio',
                  'ARQUIVO', r.get('title'), 'BANCO', (anuncio_banco or {}).get('titulo_anuncio')),
        _comparar('Status: ARQUIVO status x BANCO tipo_de_anuncio.status',
                  'ARQUIVO', r.get('status'), 'BANCO', tipo_banco.get('status')),
        _comparar('Tipo logístico: ARQUIVO logistic_type x BANCO tipo_de_anuncio.tipo_logistico',
                  'ARQUIVO', r.get('logistic_type'), 'BANCO', tipo_banco.get('tipo_logistico')),
        _comparar('Preço: ARQUIVO price x BANCO variacao.preco_atual',
                  'ARQUIVO', r.get('price'), 'BANCO', (variacao_banco or {}).get('preco_atual'), normalizar=_decimal),
        _comparar('Estoque do anúncio: ARQUIVO available_quantity x BANCO variacao.estoque',
                  'ARQUIVO', r.get('available_quantity'), 'BANCO', (variacao_banco or {}).get('estoque'),
                  aviso_se_diferente='o BANCO só muda quando o importar_anuncios_ml roda de novo'),
        _comparar('Última atualização: ARQUIVO last_updated x BANCO anuncio.ultima_atualizacao_ml',
                  'ARQUIVO', r.get('last_updated'), 'BANCO', (anuncio_banco or {}).get('ultima_atualizacao_ml'),
                  normalizar=_instante),
        _comparar('user_product_id: ARQUIVO x BANCO variacao.mlbu',
                  'ARQUIVO', r.get('user_product_id'), 'BANCO', (variacao_banco or {}).get('mlbu')),
        _comparar('user_product_id: ARQUIVO x REPOS identifiers.user_product_id',
                  'ARQUIVO', r.get('user_product_id'), 'REPOS', pegar(dados_rep, 'identifiers.user_product_id') if dados_rep else None),
        _comparar('inventory_id: ARQUIVO x REPOS identifiers.inventory_id',
                  'ARQUIVO', r.get('inventory_id'), 'REPOS', pegar(dados_rep, 'identifiers.inventory_id') if dados_rep else None),
        _comparar('SKU: ARQUIVO sku x BANCO variacao.sku_ml',
                  'ARQUIVO', r.get('sku'), 'BANCO', (variacao_banco or {}).get('sku_ml')),
        _comparar('SKU: ARQUIVO sku x REPOS identifiers.seller_sku',
                  'ARQUIVO', r.get('sku'), 'REPOS', pegar(dados_rep, 'identifiers.seller_sku') if dados_rep else None),
    ]

    sku_ml = (variacao_banco or {}).get('sku_ml')
    produto = (variacao_banco or {}).get('produto')
    if variacao_banco is not None and sku_ml and not produto:
        conf.append(_conferencia('SKU: BANCO variacao.sku_ml existe no cadastro de Produto?', False,
                                 f'SKU {sku_ml} não tem nenhum Produto com esse SKU (variacao.produto ficou vazio)'))
    else:
        conf.append(_comparar('SKU: BANCO variacao.sku_ml x BANCO variacao.produto (SKU do Produto)',
                              'sku_ml', sku_ml, 'produto', produto))

    disponivel = pegar(dados_est, 'available_quantity') if dados_est else None
    conf.append(_comparar(
        'Estoque do anúncio (ARQUIVO) x Disponível para venda (ESTOQUE do código)',
        'ARQUIVO', r.get('available_quantity'), 'ESTOQUE available_quantity', disponivel, normalizar=_decimal,
        aviso_se_diferente=(f"o ARQUIVO é uma foto de {arquivo_gerado_em or 'data desconhecida'}; "
                            f"rode o buscar_detalhes de novo para atualizar")))
    return conf


def _resumo_das_conferencias(conferencias):
    return {chave: sum(1 for c in conferencias if c['resultado'] == chave) for chave in ('igual', 'diferente', 'nao_da')}


CAMPOS_ARQUIVO_NO_CATALOGO = {c['caminho'] for c in CATALOGO_FULL if c['fonte'] == 'ARQUIVO'}


# Função Objetivo: As chaves que o registro do arquivo tem e o catálogo ainda não mostra (ex.: um campo novo que o
# buscar_detalhes passe a gravar). Assim nada do registro fica escondido: o que não tem linha própria aparece aqui.
def _campos_do_arquivo_fora_do_catalogo(registro):
    return [{'campo': campo, 'valor': json.dumps(valor, ensure_ascii=False, default=str)}
            for campo, valor in registro.items() if campo not in CAMPOS_ARQUIVO_NO_CATALOGO]


# Função Objetivo: O bloco completo de 1 anúncio (nível 3): as linhas de cada tópico, as conferências só
# dele e o registro inteiro como está no arquivo.
def _montar_anuncio(ficha_n, posicao, r, dados_rep, dados_est, banco, validacoes, rotulos_situacao, arquivo_gerado_em):
    ancora = f'ful-anuncio-{ficha_n}-{posicao}'
    origens = {'ARQUIVO': r, 'BANCO': _pacote_banco_do_anuncio(banco, r)}
    anuncio_banco = banco['anuncios'].get(str(r.get('mlb') or '')) if banco else None
    conferencias = _conferencias_do_anuncio(r, anuncio_banco, _variacao_do_banco(banco, r), dados_rep, dados_est,
                                            arquivo_gerado_em)
    status = r.get('status')
    return {
        'ancora': ancora,
        'rotulo': _rotulo_do_anuncio(r),
        'mlb': r.get('mlb'),
        'status': status,
        'status_rotulo': _rotulos_do_tipo_de_anuncio()['status'].get(status, '') if status else '',
        'titulo': r.get('title') or '',
        'blocos': _montar_blocos('anuncio', origens, validacoes, rotulos_situacao),
        'conferencias': conferencias,
        'resumo_conferencias': _resumo_das_conferencias(conferencias),
        'bruto': _bruto_registros([r], ' — este anúncio (registro completo)'),
        'fora_do_catalogo': _campos_do_arquivo_fora_do_catalogo(r),
    }


# ---------------------------------------------------------------------------
# NÍVEL 1 — OS PRODUTOS (1 por SKU encontrado)
# ---------------------------------------------------------------------------
# Função Objetivo: Os SKUs que ligam este Código ML a produtos do cadastro, na ordem em que aparecem, cada um com
# a lista de onde foi visto (REPOS, o registro de cada anúncio, a variação no banco). Um bloco por SKU: se os
# anúncios do código tiverem SKUs diferentes, aparecem produtos diferentes — nada é fundido.
def _skus_do_codigo(dados_rep, registros_upid, banco):
    vistos = {}

    def somar(sku, onde):
        vistos.setdefault(str(sku), []).append(onde)

    sku_rep = pegar(dados_rep, 'identifiers.seller_sku') if dados_rep else None
    if sku_rep:
        somar(sku_rep, 'REPOS (identifiers.seller_sku)')
    for r in registros_upid:
        if r.get('sku'):
            somar(r['sku'], f"ARQUIVO — anúncio {_rotulo_do_anuncio(r)}")
        variacao = _variacao_do_banco(banco, r)
        if variacao and variacao.get('produto'):
            somar(variacao['produto'], f"BANCO — variação do anúncio {_rotulo_do_anuncio(r)} (campo produto)")
    return vistos


def _montar_produtos(dados_rep, registros_upid, banco, validacoes, rotulos_situacao):
    produtos = []
    for sku, origens_do_sku in _skus_do_codigo(dados_rep, registros_upid, banco).items():
        pacote = _pacote_banco_do_produto(banco, sku)
        dados = (pacote or {}).get('dados', {}).get('produto')
        produtos.append({
            'sku': sku,
            'titulo': (dados or {}).get('titulo') or '',
            'achou': dados is not None,
            'lido': pacote is not None,
            'origens': origens_do_sku,
            'blocos': _montar_blocos('produto', {'BANCO': pacote}, validacoes, rotulos_situacao),
        })
    return produtos


# ---------------------------------------------------------------------------
# AS FONTES DA PÁGINA
# ---------------------------------------------------------------------------
def _campos_fora_da_doc(dados, chaves_doc):
    novos = []
    if not isinstance(dados, dict):
        return novos
    for bloco, esperadas in chaves_doc.items():
        objeto = dados if bloco == '(raiz)' else dados.get(bloco)
        if isinstance(objeto, dict):
            for chave in objeto:
                if chave not in esperadas:
                    novos.append(chave if bloco == '(raiz)' else f'{bloco}.{chave}')
    return novos


def _resultado_do_pacote(pacote):
    if pacote.get('erro'):
        return False, f"ERRO — {pacote['erro']}"
    texto = f"HTTP {pacote.get('http')}"
    if pacote.get('x_content_missing'):
        texto += f" · X-Content-Missing: {pacote['x_content_missing']}"
    return True, texto


def _endereco_do_pacote(pacote):
    params = pacote.get('params')
    return f"GET {pacote.get('endpoint')}" + (f"?country={params['country']}" if params and 'country' in params else '')


def _cartao_fonte(chave, chamadas, fora_da_doc, aviso, bruto=None):
    info = FONTES_FULL[chave]
    return {'chave': chave, 'nome': info['nome'], 'projeto': info['projeto'],
            'projeto_rotulo': ROTULO_PROJETO[info['projeto']], 'projeto_etiqueta': etiqueta_projeto(chave),
            'projeto_texto': info['projeto_texto'],
            'endpoint_modelo': info['endpoint_modelo'], 'chamadas': chamadas, 'fora_da_doc': fora_da_doc,
            'aviso': aviso, 'bruto': bruto}


# Função Objetivo: Os quadros "De onde vêm os dados" — 1 por fonte, com o endpoint
# EXATO que foi chamado, o resultado, se o endpoint é novo ou já usado e os campos
# que a API mandou e a doc não cita. No BANCO, as "chamadas" são as leituras feitas nas tabelas.
def montar_fontes(consulta, banco=None):
    fontes = []
    for chave, pacotes, chaves_doc in (('REPOS', consulta.reposicao, CHAVES_DOC_REPOSICAO),
                                       ('ESTOQUE', consulta.estoque, CHAVES_DOC_ESTOQUE)):
        chamadas, fora_da_doc = [], []
        for pacote in pacotes.values():
            ok, resultado = _resultado_do_pacote(pacote)
            chamadas.append({'endereco': _endereco_do_pacote(pacote), 'resultado': resultado, 'ok': ok,
                             'bruto': _bruto_do_pacote(pacote)})
            fora_da_doc += [c for c in _campos_fora_da_doc(pacote.get('dados'), chaves_doc) if c not in fora_da_doc]
        fontes.append(_cartao_fonte(
            chave, chamadas, fora_da_doc,
            '' if chamadas else 'Não consultado: não havia o que consultar para este código.'))

    fontes.append(_cartao_fonte(
        'ARQUIVO', [], [],
        f"Foto de {consulta.arquivo_gerado_em or 'data não registrada no arquivo'} — "
        f"{len(consulta.registros_arquivo)} registro(s) deste código. "
        f"O arquivo NÃO acompanha o ML sozinho.",
        bruto=_bruto_registros(consulta.registros_arquivo, ' — registros deste código')))
    if banco is None:
        fontes.append(_cartao_fonte('BANCO', [], [], 'O banco não foi lido nesta montagem da ficha.'))
    else:
        fontes.append(_cartao_fonte(
            'BANCO', banco['consultas'], [],
            '' if banco['consultas'] else 'Nada para procurar: o código não tem anúncio, user_product_id nem SKU.'))
    fontes.append(_cartao_fonte(
        'TELA', [], [],
        'Estes itens só existem na página do Mercado Livre: confira olhando a tela e registre aqui o que bater.'))
    return fontes


# Função Objetivo: A página inteira a partir de 1 consulta salva: os quadros das fontes e
# 1 ficha por user_product_id do código (quase sempre só 1). Cada ficha tem os 3 níveis:
# produtos (BANCO), o código ML do Full (REPOS/ESTOQUE) e 1 bloco por anúncio (ARQUIVO/BANCO).
# validacoes = {"FONTE|caminho": {"nome_interno", "situacao", "observacao"}}; rotulos_situacao =
# {"valido": "Válido", ...} (vem do model, para não duplicar a lista de situações); banco = o que
# ler_banco devolveu (ou None, se o banco não foi lido).
def montar_pagina(consulta, validacoes, rotulos_situacao, banco=None):
    codigo, tipo, valor_interno = interpretar_codigo(consulta.codigo)
    registros = consulta.registros_arquivo or []

    upids = list(consulta.reposicao.keys())
    for r in registros:
        upid = r.get('user_product_id')
        if upid and upid not in upids:
            upids.append(upid)

    niveis = {chave: {'numero': i, 'titulo': titulo, 'descricao': descricao}
              for i, (chave, titulo, descricao) in enumerate(NIVEIS_FULL, start=1)}

    fichas = []
    for numero, upid in enumerate(upids or [None], start=1):
        registros_upid = [r for r in registros if (r.get('user_product_id') == upid if upid else not r.get('user_product_id'))]
        pacote_rep = consulta.reposicao.get(upid) if upid else None
        dados_rep = (pacote_rep or {}).get('dados')
        inventario = _inventario_do_upid(dados_rep, registros_upid, consulta.estoque)
        pacote_est = consulta.estoque.get(inventario) if inventario else None
        dados_est = (pacote_est or {}).get('dados')

        anuncios = [_montar_anuncio(numero, posicao, r, dados_rep, dados_est, banco, validacoes, rotulos_situacao,
                                    consulta.arquivo_gerado_em)
                    for posicao, r in enumerate(registros_upid, start=1)]

        fichas.append({
            'numero': numero,
            'user_product_id': upid,
            'inventory_id': inventario,
            'niveis': niveis,
            'produtos': _montar_produtos(dados_rep, registros_upid, banco, validacoes, rotulos_situacao),
            'blocos_codigo': _montar_blocos('codigo', {'REPOS': pacote_rep, 'ESTOQUE': pacote_est},
                                            validacoes, rotulos_situacao),
            'semanas': _semanas_da_tabela(dados_rep),
            'semanas_bruto': _bruto_api('sales.sales_history', pacote_rep, com_bloco=False,
                                        nota='Na mesma ordem em que a API mandou.'),
            'conferencias_codigo': _conferencias_do_codigo(codigo, tipo, valor_interno, upid, dados_rep, dados_est,
                                                           inventario, registros_upid, banco),
            'anuncios_indice': [_anuncio_na_tabela(r, a['ancora']) for r, a in zip(registros_upid, anuncios)],
            'anuncios_bruto': _bruto_registros(registros_upid),
            'anuncios': anuncios,
        })
    return {'fontes': montar_fontes(consulta, banco), 'fichas': fichas}


# Função Objetivo: O placar do topo da tela — quantos dos campos do catálogo estão em
# cada situação. Campo sem registro conta como "A validar". Devolve uma lista na ordem
# de rotulos_situacao: [{"chave", "rotulo", "n"}].
def contar_situacoes(validacoes, rotulos_situacao):
    contagem = {chave: 0 for chave in rotulos_situacao}
    for entrada in CATALOGO_FULL:
        registro = validacoes.get(chave_campo(entrada['fonte'], entrada['caminho'])) or {}
        situacao = registro.get('situacao') or SITUACAO_PADRAO
        contagem[situacao] = contagem.get(situacao, 0) + 1
    return [{'chave': chave, 'rotulo': rotulo, 'n': contagem.get(chave, 0)}
            for chave, rotulo in rotulos_situacao.items()]


# ---------------------------------------------------------------------------
# BANCO (as únicas funções deste arquivo que tocam o banco — só leitura)
# ---------------------------------------------------------------------------
LIMITE_CONSULTAS_RECENTES = 12


def buscar_ultima_consulta(codigo):
    from mercado_livre.models import ConsultaFullMercadoLivre
    return ConsultaFullMercadoLivre.objects.filter(codigo=codigo).first()


# Função Objetivo: Os últimos códigos consultados (1 por código, o mais recente de cada),
# para a tela oferecer atalhos sem ninguém precisar digitar de novo.
def listar_recentes(limite=LIMITE_CONSULTAS_RECENTES):
    from mercado_livre.models import ConsultaFullMercadoLivre
    vistos, recentes = set(), []
    for consulta in ConsultaFullMercadoLivre.objects.only('codigo', 'consultado_em')[:limite * 6]:
        if consulta.codigo in vistos:
            continue
        vistos.add(consulta.codigo)
        recentes.append(consulta)
        if len(recentes) >= limite:
            break
    return recentes


def carregar_validacoes():
    """{"FONTE|caminho": {"nome_interno", "situacao", "observacao"}} de tudo que a equipe já registrou."""
    from mercado_livre.models import CampoFullMercadoLivre
    return {
        chave_campo(c.fonte, c.caminho): {'nome_interno': c.nome_interno, 'situacao': c.situacao, 'observacao': c.observacao}
        for c in CampoFullMercadoLivre.objects.all()
    }


# Função Objetivo: Lê no banco (SÓ LEITURA, 4 consultas no máximo) as linhas que correspondem ao que a consulta
# salva trouxe: o Anúncio e a Variação de cada MLB do arquivo, as variações que têm o mlbu do código e os
# Produtos dos SKUs vistos (REPOS, arquivo e a variação no banco). Devolve um dicionário simples para as
# funções que montam a ficha — quem não achou no banco simplesmente não aparece nos dicionários:
#   {"anuncios": {mlb: {...}}, "variacoes": {(mlb, variacao_id): {...}}, "variacoes_por_mlbu": {mlbu: [{mlb, variacao_id}]},
#    "produtos": {sku: {...}}, "consultas": [{endereco, resultado, ok, bruto}]}
# Os valores saem como texto/número simples (decimais e datas viram texto) para a tela mostrar "Como está no banco".
CAMPOS_PRODUTO_BANCO = ('sku', 'ean', 'titulo', 'marca', 'categoria', 'cod_fabricante', 'ncm', 'curva',
                        'estoque', 'ativo_no_erp', 'imagem_url')
CAMPOS_ANUNCIO_BANCO = ('mlb', 'titulo_anuncio', 'catalog_product_id', 'catalog_listing', 'item_relations',
                        'atributos_ml_status', 'atributos_ml_categoria_id', 'permalink', 'data_criacao_ml',
                        'ultima_atualizacao_ml', 'eh_fossil_migracao')
CAMPOS_TIPO_BANCO = ('nome', 'status', 'tipo_anuncio', 'tipo_logistico', 'classificacao_catalogo', 'flex')
CAMPOS_VARIACAO_BANCO = ('variacao_id', 'mlbu', 'sku_ml', 'estoque', 'qtd_vendas', 'atributos', 'num_fotos',
                         'preco_atual', 'preco_original')


def _simples(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if hasattr(valor, 'isoformat'):
        return valor.isoformat()
    return valor


def _linha_do_banco(objeto, campos):
    return {campo: _simples(getattr(objeto, campo)) for campo in campos}


def _anuncio_do_banco(anuncio):
    dados = _linha_do_banco(anuncio, CAMPOS_ANUNCIO_BANCO)
    tipo = anuncio.tipo_de_anuncio
    dados['tipo_de_anuncio'] = None if tipo is None else _linha_do_banco(tipo, CAMPOS_TIPO_BANCO)
    return dados


def _variacao_do_banco_dict(variacao):
    dados = _linha_do_banco(variacao, CAMPOS_VARIACAO_BANCO)
    # Produto é ligado pelo SKU (to_field='sku'), então produto_id já é o próprio SKU do Produto.
    dados['produto'] = variacao.produto_id
    categoria = variacao.categoria
    dados['categoria'] = None if categoria is None else {'category_id': categoria.category_id, 'nome': categoria.nome}
    return dados


def _consulta_do_banco(modelo, filtro, resultado, ok):
    return {'endereco': f'{modelo} onde {filtro}', 'resultado': resultado, 'ok': ok, 'bruto': None}


def _achados_de_pedidos(achados, pedidos):
    return f'{achados} de {pedidos} encontrado(s)', achados == pedidos


def ler_banco(consulta):
    from mercado_livre.models import AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre
    from produtos.models import Produto

    registros = consulta.registros_arquivo or []
    mlbs = sorted({str(r['mlb']) for r in registros if r.get('mlb')})
    upids = sorted(set(consulta.reposicao) | {str(r['user_product_id']) for r in registros if r.get('user_product_id')})
    skus = {str(r['sku']) for r in registros if r.get('sku')}
    for pacote in consulta.reposicao.values():
        sku_rep = pegar(pacote.get('dados'), 'identifiers.seller_sku')
        if sku_rep:
            skus.add(str(sku_rep))

    banco = {'anuncios': {}, 'variacoes': {}, 'variacoes_por_mlbu': {}, 'produtos': {}, 'consultas': []}

    if mlbs:
        for anuncio in AnuncioMercadoLivre.objects.filter(mlb__in=mlbs).select_related('tipo_de_anuncio'):
            banco['anuncios'][anuncio.mlb] = _anuncio_do_banco(anuncio)
        banco['consultas'].append(_consulta_do_banco(
            'AnuncioMercadoLivre', f"mlb está em [{', '.join(mlbs)}]",
            *_achados_de_pedidos(len(banco['anuncios']), len(mlbs))))

        for variacao in VariacaoAnuncioMercadoLivre.objects.filter(anuncio__mlb__in=mlbs).select_related('anuncio', 'categoria'):
            banco['variacoes'][(variacao.anuncio.mlb, variacao.variacao_id)] = _variacao_do_banco_dict(variacao)
            if variacao.produto_id:
                skus.add(str(variacao.produto_id))
        pedidas = len({(str(r.get('mlb') or ''), _id_da_variacao(r)) for r in registros if r.get('mlb')})
        banco['consultas'].append(_consulta_do_banco(
            'VariacaoAnuncioMercadoLivre', f"anuncio.mlb está em [{', '.join(mlbs)}]",
            *_achados_de_pedidos(len(banco['variacoes']), pedidas)))

    if upids:
        achadas = 0
        for mlb, variacao_id, mlbu in VariacaoAnuncioMercadoLivre.objects.filter(mlbu__in=upids).values_list(
                'anuncio__mlb', 'variacao_id', 'mlbu').order_by('anuncio__mlb', 'variacao_id'):
            banco['variacoes_por_mlbu'].setdefault(mlbu, []).append({'mlb': mlb, 'variacao_id': variacao_id})
            achadas += 1
        banco['consultas'].append(_consulta_do_banco(
            'VariacaoAnuncioMercadoLivre', f"mlbu está em [{', '.join(upids)}]",
            f'{achadas} variação(ões) encontrada(s)', achadas > 0))

    if skus:
        for produto in Produto.objects.filter(sku__in=sorted(skus)):
            banco['produtos'][produto.sku] = _linha_do_banco(produto, CAMPOS_PRODUTO_BANCO)
        banco['consultas'].append(_consulta_do_banco(
            'Produto', f"sku está em [{', '.join(sorted(skus))}]",
            *_achados_de_pedidos(len(banco['produtos']), len(skus))))
    return banco
