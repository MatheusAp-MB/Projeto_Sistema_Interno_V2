# produtos/funcoes_auxiliares/contexto_tela_produtos.py

# Função Objetivo: Monta todo o contexto da tela de Produtos (busca/filtro/ordenação/
# paginação), em classes de responsabilidade única — substitui a view_produtos antiga
# (145 linhas procedurais misturando tudo).

from dataclasses import dataclass, field
from django.core.paginator import Paginator
from produtos.models import Produto
from produtos.funcoes_auxiliares.filtros_produtos import (
    listar_produtos_filtrados, CAMPOS_ORDENACAO, CAMPOS_FAIXA,
)

# * [EXPLICAÇÃO] → Rótulo amigável de cada coluna — única fonte, usada tanto
#                  pros cabeçalhos ordenáveis quanto pros chips de filtro ativo.
#                  Corrigido (23/07): os 4 nomes antigos ('peso', 'altura',
#                  'largura', 'profundidade') não existem no Produto — viraram
#                  os 8 campos reais (sem embalar + após embalado).
LABELS_COLUNAS = {
    'ean': 'EAN', 'sku': 'SKU', 'cod_fabricante': 'Cód. Fabricante', 'ncm': 'NCM',
    'titulo': 'Nome', 'marca': 'Marca', 'categoria': 'Categoria', 'curva': 'Curva',
    'estoque': 'Estoque',
    'custo': 'Custo', 'custo_com_boni': 'Custo c/ Boni',
    'peso_sem_embalar': 'Peso (sem embalar)', 'altura_sem_embalar': 'Altura (sem embalar)',
    'largura_sem_embalar': 'Largura (sem embalar)', 'comprimento_sem_embalar': 'Comprimento (sem embalar)',
    'peso_apos_embalado': 'Peso (após embalado)', 'altura_apos_embalado': 'Altura (após embalado)',
    'largura_apos_embalado': 'Largura (após embalado)', 'comprimento_apos_embalado': 'Comprimento (após embalado)',
    'peso_cubado': 'Peso Cubado',
    'mva': 'MVA', 'st_valor': 'ST Valor', 'icms_entrada': 'ICMS Entrada',
    'icms_saida_sp': 'ICMS Saída SP', 'icms_saida_media': 'ICMS Saída Média',
    'ipi': 'IPI', 'pis_cofins': 'PIS/COFINS',
    'pis_percentual': 'PIS %', 'cofins_percentual': 'COFINS %',
    'frete_cif_fob': 'Frete CIF/FOB',
    'ultima_compra': 'Última Compra', 'cadastrado_erp_em': 'Cadastro no ERP',
    'criado_em': 'Entrada no DB', 'atualizado_em': 'Atualização no DB',
}

# * [EXPLICAÇÃO] → Estrutura do painel de filtro por faixa — mesmas 6 seções
#                  do ERP, dimensão agora com os 8 campos reais.
SECOES_FILTRO_FAIXA = [
    {'titulo': 'Identificação', 'campos': [('estoque', 'Estoque')]},
    {'titulo': 'Dimensões — sem embalar', 'campos': [
        ('peso_sem_embalar', 'Peso'), ('altura_sem_embalar', 'Altura'),
        ('largura_sem_embalar', 'Largura'), ('comprimento_sem_embalar', 'Comprimento'),
    ]},
    {'titulo': 'Dimensões — após embalado', 'campos': [
        ('peso_apos_embalado', 'Peso'), ('altura_apos_embalado', 'Altura'),
        ('largura_apos_embalado', 'Largura'), ('comprimento_apos_embalado', 'Comprimento'),
        ('peso_cubado', 'Peso Cubado'),
    ]},
    {'titulo': 'Financeiro', 'campos': [
        ('custo', 'Custo'), ('custo_com_boni', 'Custo c/ Boni')]},
    {'titulo': 'Fiscal', 'campos': [
        ('ipi', 'IPI'), ('icms_entrada', 'ICMS Entrada'), ('icms_saida_sp', 'ICMS Saída SP'),
        ('icms_saida_media', 'ICMS Saída Média'), ('pis_cofins', 'PIS/COFINS'),
        ('pis_percentual', 'PIS %'), ('cofins_percentual', 'COFINS %'),
        ('mva', 'MVA'), ('st_valor', 'ST Valor'), ('frete_cif_fob', 'Frete CIF/FOB'),
    ]},
    {'titulo': 'Controle DB', 'campos': [
        ('criado_em', 'Entrada no DB'), ('atualizado_em', 'Atualização no DB')]},
    {'titulo': 'Controle ERP', 'campos': [
        ('ultima_compra', 'Última Compra'), ('cadastrado_erp_em', 'Cadastro no ERP')]},
]


# Função Objetivo: Representa os parâmetros de busca/filtro/ordenação já validados.
@dataclass
class ParametrosBuscaProdutos:
    busca: str
    por_pagina: int
    ordenar: str
    numero_pagina: int
    filtros: dict = field(default_factory=dict)

    # Função Objetivo: Lê e valida tudo direto da querystring da requisição.
    @classmethod
    def a_partir_da_requisicao(cls, request):
        busca = request.GET.get('busca', '').strip()

        por_pagina_bruto = request.GET.get('por_pagina', '25')
        try:
            por_pagina = int(por_pagina_bruto)
        except ValueError:
            por_pagina = 25

        ordenar = request.GET.get('ordenar', 'titulo')
        if ordenar.lstrip('-') not in CAMPOS_ORDENACAO:
            ordenar = 'titulo'

        filtros = {
            'marcas': request.GET.getlist('marca'),
            'categorias': request.GET.getlist('categoria'),
            'curvas': request.GET.getlist('curva'),
        }
        for campo in CAMPOS_FAIXA:
            filtros[f'{campo}_min'] = request.GET.get(f'{campo}_min', '')
            filtros[f'{campo}_max'] = request.GET.get(f'{campo}_max', '')

        return cls(
            busca=busca, por_pagina=por_pagina, ordenar=ordenar,
            numero_pagina=request.GET.get('pagina', 1), filtros=filtros,
        )


# Função Objetivo: Monta o link/seta de ordenação de cada cabeçalho de coluna.
class ConstrutorCabecalhosOrdenacao:

    def __init__(self, ordenar, querystring_base):
        self.ordenar = ordenar
        self.querystring_base = querystring_base

    # Função Objetivo: Monta 1 cabeçalho (chave, label).
    def _montar_um(self, chave, label):
        ativo = self.ordenar.lstrip('-') == chave
        esta_asc = ativo and not self.ordenar.startswith('-')
        proximo = f'-{chave}' if esta_asc else chave
        if ativo:
            icone = 'fa-sort-up' if esta_asc else 'fa-sort-down'
        else:
            icone = 'fa-sort'
        return {
            'label': label, 'icone': icone, 'ativo': ativo,
            'href': f'?{self.querystring_base}&ordenar={proximo}',
        }

    # Função Objetivo: Monta todos os cabeçalhos, a partir do dicionário de rótulos.
    def montar(self, labels_colunas):
        return {chave: self._montar_um(chave, label) for chave, label in labels_colunas.items()}


# Função Objetivo: Monta os chips de "filtro ativo" exibidos acima da tabela.
class ConstrutorChipsAtivos:

    def __init__(self, filtros, labels_colunas):
        self.filtros = filtros
        self.labels_colunas = labels_colunas

    # Função Objetivo: Monta os chips dos 3 filtros de checkbox (marca/categoria/curva).
    def _chips_checkbox(self):
        return (
            [{'label': v} for v in self.filtros['marcas']] +
            [{'label': v} for v in self.filtros['categorias']] +
            [{'label': v} for v in self.filtros['curvas']]
        )

    # Função Objetivo: Monta os chips dos filtros de faixa (mín/máx), 1 frase cada.
    def _chips_faixa(self):
        chips = []
        for campo in CAMPOS_FAIXA:
            minimo = self.filtros.get(f'{campo}_min')
            maximo = self.filtros.get(f'{campo}_max')
            if not (minimo or maximo):
                continue
            label = self.labels_colunas.get(campo, campo)
            if minimo and maximo:
                chips.append({'label': f'{label}: {minimo} até {maximo}'})
            elif minimo:
                chips.append({'label': f'{label}: a partir de {minimo}'})
            else:
                chips.append({'label': f'{label}: até {maximo}'})
        return chips

    # Função Objetivo: Monta todos os chips ativos.
    def montar(self):
        return self._chips_checkbox() + self._chips_faixa()


# Função Objetivo: Orquestra a montagem inteira do contexto da tela de Produtos.
class ContextoTelaProdutos:

    def __init__(self, request):
        self.request = request
        self.parametros = ParametrosBuscaProdutos.a_partir_da_requisicao(request)

    # Função Objetivo: Monta a querystring base (sem "ordenar"/"pagina"), pros cabeçalhos.
    def _querystring_base(self):
        querystring = self.request.GET.copy()
        querystring.pop('ordenar', None)
        querystring.pop('pagina', None)
        return querystring.urlencode()

    # Função Objetivo: Monta a querystring sem "pagina", pros links de paginação.
    def _querystring_sem_pagina(self):
        querystring = self.request.GET.copy()
        querystring.pop('pagina', None)
        return querystring.urlencode()

    # Função Objetivo: Monta a página atual de produtos, já filtrada/ordenada.
    def _montar_pagina(self):
        produtos = listar_produtos_filtrados(
            busca=self.parametros.busca or None,
            filtros=self.parametros.filtros,
            ordenar=self.parametros.ordenar,
        )
        paginator = Paginator(produtos, self.parametros.por_pagina)
        return paginator.get_page(self.parametros.numero_pagina)

    # Função Objetivo: Monta o contexto completo, pronto pro render().
    def montar(self):
        cabecalhos = ConstrutorCabecalhosOrdenacao(
            self.parametros.ordenar, self._querystring_base(),
        ).montar(LABELS_COLUNAS)

        chips_ativos = ConstrutorChipsAtivos(
            self.parametros.filtros, LABELS_COLUNAS,
        ).montar()

        return {
            'pagina': self._montar_pagina(),
            'busca': self.parametros.busca,
            'por_pagina': self.parametros.por_pagina,
            'filtros': self.parametros.filtros,
            'cabecalhos': cabecalhos,
            'chips_ativos': chips_ativos,
            'secoes_filtro_faixa': SECOES_FILTRO_FAIXA,
            'querystring_sem_pagina': self._querystring_sem_pagina(),
            'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True)
                .exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
            'categorias_disponiveis': Produto.objects.exclude(categoria__isnull=True)
                .exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
            'curvas_disponiveis': Produto.objects.exclude(curva__isnull=True)
                .exclude(curva='').values_list('curva', flat=True).distinct().order_by('curva'),
        }