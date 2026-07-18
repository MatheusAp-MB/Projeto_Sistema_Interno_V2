# precificacao/views/comum.py

# Função Objetivo: Peças genuinamente compartilhadas por TODOS os marketplaces da Grade.
# Explicação em detalhe: Margem/MARGENS, FiltrosGrade, FiltroPrecoExibido,
# LinhaMargemExibida já eram usadas por ML e Magalu. _filtrar_paginar_produtos_grade e
# _opcoes_filtro_produto nasceram aqui (18/07) — agora que existem 2 marketplaces reais
# repetindo o mesmo bloco de busca/filtro/paginação, a duplicação vira extração de
# verdade (regra do projeto: "nasce solta com evidência real de 2+ casos", não antes).

from dataclasses import dataclass
from django.core.paginator import Paginator
from produtos.funcoes_auxiliares.filtros_produtos import listar_produtos_filtrados


# Função Objetivo: Representa 1 margem configurável (Mínima/Padrão/Máxima/Competição).
@dataclass(frozen=True)
class Margem:
    chave: str
    label_base: str
    campo_config: str
    percentual_padrao: str

    # Função Objetivo: Rótulo genérico, sem config real (ex: usado nos filtros de faixa de preço).
    @property
    def label_padrao(self):
        return f'{self.label_base} ({self.percentual_padrao})'

    # Função Objetivo: Rótulo com o percentual REAL da config do tipo de anúncio.
    def label_com_config(self, config):
        valor = getattr(config, self.campo_config, None) if config else None
        return f'{self.label_base} ({valor:.0f}%)' if valor is not None else self.label_padrao


MARGENS = [
    Margem('competicao', 'Competição', 'margem_competicao', '5%'),
    Margem('minima', 'Mínima', 'margem_minima', '10%'),
    Margem('padrao', 'Padrão', 'margem_padrao', '15%'),
    Margem('maxima', 'Máxima', 'margem_maxima', '20%'),
]
MARGENS_CHAVES = [m.chave for m in MARGENS]
MARGENS_POR_CHAVE = {m.chave: m for m in MARGENS}


def _labels_do_tipo(configs, tipo):
    """Rótulos com percentual real da config (ex: 'Padrão (15%)') —
    Clássico e Premium são editáveis de forma independente, cada um
    mostra o percentual da SUA PRÓPRIA config."""
    config = configs.get(tipo)
    return [m.label_com_config(config) for m in MARGENS]


# Função Objetivo: Representa os filtros de produto vindos da querystring.
@dataclass
class FiltrosGrade:
    busca: str
    por_pagina: int
    marcas: list
    categorias: list
    curvas: list
    estoque_min: str
    estoque_max: str
    custo_min: str
    custo_max: str

    # Função Objetivo: Lê o request e monta os filtros já validados.
    @classmethod
    def montar(cls, request):
        try:
            por_pagina = int(request.GET.get('por_pagina', '25'))
        except ValueError:
            por_pagina = 25

        return cls(
            busca=request.GET.get('busca', '').strip(),
            por_pagina=por_pagina,
            marcas=request.GET.getlist('marca'),
            categorias=request.GET.getlist('categoria'),
            curvas=request.GET.getlist('curva'),
            estoque_min=request.GET.get('estoque_min', ''),
            estoque_max=request.GET.get('estoque_max', ''),
            custo_min=request.GET.get('custo_min', ''),
            custo_max=request.GET.get('custo_max', ''),
        )

    # Função Objetivo: Devolve o dict no formato que listar_produtos_filtrados espera.
    def para_filtros_produto(self):
        return {
            'marcas': self.marcas, 'categorias': self.categorias, 'curvas': self.curvas,
            'estoque_min': self.estoque_min, 'estoque_max': self.estoque_max,
            'custo_min': self.custo_min, 'custo_max': self.custo_max,
        }


# Função Objetivo: Representa 1 filtro de faixa de preço exibido no painel de filtros.
@dataclass
class FiltroPrecoExibido:
    label: str
    campo_min: str
    campo_max: str
    valor_min: str
    valor_max: str

    # Função Objetivo: Monta as 4 faixas (1 por margem) de 1 tipo de anúncio.
    @classmethod
    def montar_bloco(cls, request, prefixo_tipo):
        resultado = []
        for m in MARGENS:
            campo_min = f'preco_{prefixo_tipo}_{m.chave}_min'
            campo_max = f'preco_{prefixo_tipo}_{m.chave}_max'
            resultado.append(cls(
                label=m.label_padrao,
                campo_min=campo_min,
                campo_max=campo_max,
                valor_min=request.GET.get(campo_min, ''),
                valor_max=request.GET.get(campo_max, ''),
            ))
        return resultado


# Função Objetivo: Representa 1 margem exibida (1 card pequeno na grade de margens).
@dataclass
class LinhaMargemExibida:
    label: str
    margem_chave: str
    preco: object
    margem: object
    eh_padrao: bool

    # Função Objetivo: Monta as 4 margens (Mínima/Padrão/Máxima/Competição) de uma vez.
    @classmethod
    def montar_bloco(cls, linhas_por_margem, labels):
        """linhas_por_margem: dict {margem_chave: linha} — no formato longo,
        cada margem é 1 linha própria (vale pra GradePrecificacaoML e
        GradePrecificacaoMagalu, ambas têm .preco/.margem_percentual_obtida)."""
        return [
            cls(
                label=label,
                margem_chave=m.chave,
                preco=linha.preco if linha else None,
                margem=linha.margem_percentual_obtida if linha else None,
                eh_padrao=m.chave == 'padrao',
            )
            for m, label in zip(MARGENS, labels)
            for linha in [linhas_por_margem.get(m.chave)]
        ]


# Função Objetivo: Devolve as 3 listas de opções de filtro (marca/categoria/curva).
# Explicação em detalhe: idêntico pra qualquer tela de Grade — não depende de
# marketplace nenhum, é sempre sobre o catálogo de Produto inteiro.
def _opcoes_filtro_produto():
    from produtos.models import Produto
    return {
        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'categorias_disponiveis': Produto.objects.exclude(categoria__isnull=True).exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
        'curvas_disponiveis': Produto.objects.exclude(curva__isnull=True).exclude(curva='').values_list('curva', flat=True).distinct().order_by('curva'),
    }


# Função Objetivo: Busca/filtra/pagina produtos pra qualquer tela de Grade de marketplace.
# Explicação em detalhe: comum entre ML e Magalu (e qualquer marketplace futuro) — busca
# textual, filtros de marca/categoria/curva/estoque/custo (reaproveitados da tela de
# Produtos), faixas de preço específicas do marketplace (via callback), e paginação.
def _filtrar_paginar_produtos_grade(request, filtro_relacionado, faixas_preco_config, aplicar_filtro_preco):
    filtros = FiltrosGrade.montar(request)

    produtos_qs = listar_produtos_filtrados(
        busca=filtros.busca or None, filtros=filtros.para_filtros_produto(), ordenar='titulo'
    )
    produtos_qs = produtos_qs.filter(**{f'{filtro_relacionado}__isnull': False}).distinct()

    for chave, dados_extra in faixas_preco_config.items():
        minimo = request.GET.get(f'preco_{chave}_min', '')
        maximo = request.GET.get(f'preco_{chave}_max', '')
        if minimo or maximo:
            produtos_qs = aplicar_filtro_preco(produtos_qs, dados_extra, minimo, maximo)

    produtos_qs = produtos_qs.distinct()

    paginator = Paginator(produtos_qs, filtros.por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return filtros, pagina, querystring_sem_pagina.urlencode()


# Função Objetivo: Representa 1 cabeçalho de coluna clicável, com seta de direção.
@dataclass
class ColunaOrdenavel:
    label: str
    url: str
    seta: str
    ativa: bool


# Função Objetivo: Monta o link + seta de 1 cabeçalho, preservando os outros filtros ativos.
def montar_coluna_ordenavel(request, chave, label, coluna_ativa, direcao_ativa):
    params = request.GET.copy()
    params.pop('pagina', None)

    if chave == coluna_ativa:
        nova_direcao = 'desc' if direcao_ativa == 'asc' else 'asc'
        seta = '▲' if direcao_ativa == 'asc' else '▼'
    else:
        nova_direcao = 'asc'
        seta = '⇅'

    params['ordenar'] = chave
    params['direcao'] = nova_direcao
    return ColunaOrdenavel(label=label, url=f'?{params.urlencode()}', seta=seta, ativa=(chave == coluna_ativa))