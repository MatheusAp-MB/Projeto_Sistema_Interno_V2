# * [RESUMO] → Busca, filtros e ordenação da tela de Produtos. Mesma
#              arquitetura já validada no Hub de Anúncios e no Resumo de
#              Critérios: tudo resolvido no servidor, sem DataTables
#              client-side (a tela antiga travava com ~1.631 linhas x
#              30 colunas de SearchPanes escaneando tudo de uma vez).

from django.db.models import Q
from django.db.models.functions import Trim
from produtos.models import Produto

# * [EXPLICAÇÃO] → Campos de texto sofrem do mesmo problema já visto na
#                  tela de Resumo de Critérios: dado bruto vindo da API/
#                  ERP pode ter espaço sobrando nas pontas, o que
#                  bagunça a ordenação alfabética. Trim() aqui só afeta
#                  a ORDENAÇÃO — o valor salvo no banco nunca é tocado
#                  (princípio do projeto: nunca "corrigir" dado bruto).
CAMPOS_TEXTO = {
    'ean', 'sku', 'cod_fabricante', 'ncm', 'titulo', 'marca', 'categoria', 'curva',
}

# * [EXPLICAÇÃO] → Única fonte de verdade dos campos ordenáveis — nunca
#                  usar o valor de "ordenar" direto num order_by() sem
#                  passar por esse whitelist (evita alguém manipular a
#                  URL pra tentar ordenar por um campo/relação que não
#                  devia ser exposto).
CAMPOS_ORDENACAO = {
    'ean': 'ean', 'sku': 'sku', 'cod_fabricante': 'cod_fabricante', 'ncm': 'ncm',
    'titulo': 'titulo', 'marca': 'marca', 'categoria': 'categoria', 'curva': 'curva',
    'estoque': 'estoque',
    'custo': 'custo', 'custo_com_boni': 'custo_com_boni',
    'peso': 'peso', 'peso_cubado': 'peso_cubado', 'altura': 'altura',
    'largura': 'largura', 'profundidade': 'profundidade',
    'mva': 'mva', 'st_valor': 'st_valor', 'icms_entrada': 'icms_entrada',
    'icms_saida_sp': 'icms_saida_sp', 'icms_saida_media': 'icms_saida_media',
    'ipi': 'ipi', 'pis_cofins': 'pis_cofins', 'frete_cif_fob': 'frete_cif_fob',
    'ultima_compra': 'ultima_compra', 'cadastrado_erp_em': 'cadastrado_erp_em',
    'criado_em': 'criado_em', 'atualizado_em': 'atualizado_em',
}

# * [EXPLICAÇÃO] → Os 20 campos numéricos/data que ganham filtro de
#                  faixa (mín/máx), organizados pelas mesmas 3 seções
#                  que o usuário já definiu (Dimensões, Financeiro,
#                  Fiscal + Controle DB/ERP tratados juntos aqui, já
#                  que a função de filtro é idêntica pra número e data).
CAMPOS_FAIXA = [
    'estoque',
    'peso', 'peso_cubado', 'altura', 'largura', 'profundidade',
    'custo', 'custo_com_boni',
    'ipi', 'icms_entrada', 'icms_saida_sp', 'icms_saida_media',
    'pis_cofins', 'mva', 'st_valor', 'frete_cif_fob',
    'ultima_compra', 'cadastrado_erp_em', 'criado_em', 'atualizado_em',
]


def aplicar_filtro_faixa(qs, filtros_faixa, campo):
    """Filtro genérico de mín/máx — funciona igual pra número e data,
    porque __gte/__lte do Django não diferenciam tipo. Reaproveitado
    pelos 20 campos de CAMPOS_FAIXA, em vez de escrever 20 blocos quase
    idênticos."""
    minimo = filtros_faixa.get(f'{campo}_min')
    maximo = filtros_faixa.get(f'{campo}_max')

    if minimo:
        qs = qs.filter(**{f'{campo}__gte': minimo})
    if maximo:
        qs = qs.filter(**{f'{campo}__lte': maximo})

    return qs


def listar_produtos_filtrados(busca=None, filtros=None, ordenar='titulo'):
    filtros = filtros or {}
    qs = Produto.objects.all()

    # * [EXPLICAÇÃO] → Busca por texto: cada palavra digitada precisa
    #                  bater em ALGUM dos 5 campos (Título/SKU/EAN/Cód.
    #                  Fabricante/Marca), mas TODAS as palavras da frase
    #                  precisam bater em algum lugar — não necessariamente
    #                  no mesmo campo. É o que permite "pulverizador 6671"
    #                  achar o produto certo mesmo se "pulverizador" só
    #                  aparece no título e "6671" só aparece no SKU.
    if busca:
        termos = busca.split()
        for termo in termos:
            qs = qs.filter(
                Q(titulo__icontains=termo) |
                Q(sku__icontains=termo) |
                Q(ean__icontains=termo) |
                Q(cod_fabricante__icontains=termo) |
                Q(marca__icontains=termo)
            )

    if filtros.get('marcas'):
        qs = qs.filter(marca__in=filtros['marcas'])

    if filtros.get('categorias'):
        qs = qs.filter(categoria__in=filtros['categorias'])

    if filtros.get('curvas'):
        qs = qs.filter(curva__in=filtros['curvas'])

    for campo in CAMPOS_FAIXA:
        qs = aplicar_filtro_faixa(qs, filtros, campo)

    campo_orm = CAMPOS_ORDENACAO.get(ordenar.lstrip('-'), 'titulo')
    descendente = ordenar.startswith('-')

    if ordenar.lstrip('-') in CAMPOS_TEXTO:
        expressao = Trim(campo_orm)
        ordenacao = expressao.desc() if descendente else expressao.asc()
    else:
        ordenacao = f'-{campo_orm}' if descendente else campo_orm

    return qs.order_by(ordenacao)
