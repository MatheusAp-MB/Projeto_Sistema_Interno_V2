# precificacao/views.py

from dataclasses import dataclass, field
from decimal import Decimal
from django.shortcuts import render
from django.core.paginator import Paginator
from produtos.funcoes_auxiliares.filtros_produtos import listar_produtos_filtrados


# ═══════════════════════════════════════════════════════════════════
# CAMADA 1 — Configuração (constante, nunca instanciada)
# ═══════════════════════════════════════════════════════════════════

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

# * [EXPLICAÇÃO] → Traduz "prefixo de querystring" → (tipo_anuncio,
#                  margem) da GradePrecificacaoML (formato longo,
#                  17/07). Nunca vira "coisa" exibida na tela — fica
#                  como dict de tradução simples.
FAIXAS_PRECO_GRADE = {
    'classico_competicao': ('classico', 'competicao'),
    'classico_minima':     ('classico', 'minima'),
    'classico_padrao':     ('classico', 'padrao'),
    'classico_maxima':     ('classico', 'maxima'),
    'premium_competicao':  ('premium', 'competicao'),
    'premium_minima':      ('premium', 'minima'),
    'premium_padrao':      ('premium', 'padrao'),
    'premium_maxima':      ('premium', 'maxima'),
}

# * [EXPLICAÇÃO] → GradePrecificacaoML.tipo_anuncio usa 'classico'/
#                  'premium' (valores próprios, simples). URLs e os
#                  cards de fallback usam o código REAL do ML
#                  (TipoDeAnuncioMercadoLivre.TipoAnuncio =
#                  'gold_special'/'gold_pro'). Os 2 sentidos de
#                  tradução moram aqui, únicos, reaproveitados pelo
#                  card de MLB e pelo modal de detalhe.
TIPO_GRADE_PARA_ML = {'classico': 'gold_special', 'premium': 'gold_pro'}
TIPO_ML_PARA_GRADE = {v: k for k, v in TIPO_GRADE_PARA_ML.items()}


def _labels_do_tipo(configs, tipo):
    """Rótulos com percentual real da config (ex: 'Padrão (15%)') —
    Clássico e Premium são editáveis de forma independente, cada um
    mostra o percentual da SUA PRÓPRIA config."""
    config = configs.get(tipo)
    return [m.label_com_config(config) for m in MARGENS]


# ═══════════════════════════════════════════════════════════════════
# CAMADA 2 — Filtros vindos do request
# ═══════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════
# CAMADA 3 — Objetos de exibição (1 coisa, instanciada N vezes)
# ═══════════════════════════════════════════════════════════════════

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
        """linhas_por_margem: dict {margem_chave: GradePrecificacaoML} —
        no formato longo, cada margem é 1 linha própria."""
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


# Função Objetivo: Representa 1 MLB real publicado, com suas 4 margens.
@dataclass
class CardMLB:
    mlb: str
    variacao_id: int
    prefixo: str
    tipo_valor: str
    badge: object
    origem_dimensao: str
    origem_dimensao_label: str
    eh_catalogo: bool
    titulo_anuncio: str
    imagem_url: str
    sku_ml: str
    sku_produto: str
    linhas: list = field(default_factory=list)

    # Função Objetivo: Monta 1 card a partir de 1 grupo de linhas (1 variação × 1 tipo).
    @classmethod
    def montar(cls, real_entry, produto, badge_classico, badge_premium, labels_classico, labels_premium, classificacao_catalogo):
        linhas_por_margem = real_entry['linhas_por_margem']
        tipo_grade = real_entry['tipo_anuncio']
        alguma_linha = next(iter(linhas_por_margem.values()))
        variacao = alguma_linha.variacao
        anuncio = variacao.anuncio
        eh_classico = tipo_grade == 'classico'
        labels = labels_classico if eh_classico else labels_premium
        tipo_de_anuncio = anuncio.tipo_de_anuncio

        return cls(
            mlb=anuncio.mlb,
            variacao_id=real_entry['variacao_id'],
            prefixo=tipo_grade,
            tipo_valor=TIPO_GRADE_PARA_ML[tipo_grade],
            badge=badge_classico if eh_classico else badge_premium,
            origem_dimensao=alguma_linha.origem_dimensao,
            origem_dimensao_label='Declarada no ML' if alguma_linha.origem_dimensao == 'variacao_ml' else 'Embalagem ERP',
            eh_catalogo=bool(tipo_de_anuncio and tipo_de_anuncio.classificacao_catalogo == classificacao_catalogo),
            # * [EXPLICAÇÃO] → título/foto do ANÚNCIO/VARIAÇÃO real (podem
            #                  divergir do produto — é o mesmo MLB, mas
            #                  o vendedor pode ter escrito outro título
            #                  ou usado outra foto na hora de publicar).
            #                  sku_ml é o SKU do PRÓPRIO anúncio no ML,
            #                  separado do sku_produto (ERP) — os 2
            #                  aparecem juntos de propósito, divergirem
            #                  é justamente o tipo de coisa que uma
            #                  auditoria precisa pegar.
            titulo_anuncio=anuncio.titulo_anuncio or produto.titulo,
            imagem_url=variacao.imagem_principal_url or variacao.thumbnail_url or produto.imagem_url,
            sku_ml=variacao.sku_ml,
            sku_produto=produto.sku,
            linhas=LinhaMargemExibida.montar_bloco(linhas_por_margem, labels),
        )


# Função Objetivo: Representa 1 produto na árvore da Grade — fallback + MLBs reais.
@dataclass
class ItemGradeProduto:
    produto: object
    linhas_classico: list
    linhas_premium: list
    cards_simples_base: list
    cards_catalogo: list
    total_mlbs: int

    # Função Objetivo: Monta 1 item completo a partir do produto e das linhas já agrupadas.
    @classmethod
    def montar(cls, produto, agrupador, badge_classico, badge_premium, labels_classico, labels_premium, classificacao_catalogo):
        fallback_classico = agrupador.fallback_de(produto.id, 'classico')
        fallback_premium = agrupador.fallback_de(produto.id, 'premium')
        reais = agrupador.reais_de(produto.id)

        cards_simples_base = []
        cards_catalogo = []
        for real_entry in reais:
            card = CardMLB.montar(
                real_entry, produto, badge_classico, badge_premium, labels_classico, labels_premium, classificacao_catalogo
            )
            if card.eh_catalogo:
                cards_catalogo.append(card)
            else:
                cards_simples_base.append(card)

        # * [EXPLICAÇÃO] → Dentro de cada subgrupo (Simples/Base,
        #                  Catálogo), Clássico sempre vem antes de
        #                  Premium — sort é estável, então a ordem
        #                  relativa entre MLBs do MESMO tipo não muda.
        ORDEM_TIPO = {'classico': 0, 'premium': 1}
        cards_simples_base.sort(key=lambda c: ORDEM_TIPO.get(c.prefixo, 2))
        cards_catalogo.sort(key=lambda c: ORDEM_TIPO.get(c.prefixo, 2))

        return cls(
            produto=produto,
            linhas_classico=LinhaMargemExibida.montar_bloco(fallback_classico, labels_classico),
            linhas_premium=LinhaMargemExibida.montar_bloco(fallback_premium, labels_premium),
            cards_simples_base=cards_simples_base,
            cards_catalogo=cards_catalogo,
            total_mlbs=len(reais),
        )


# ═══════════════════════════════════════════════════════════════════
# CAMADA 4 — Agregação (estado, serviço — não é "1 coisa" exibida)
# ═══════════════════════════════════════════════════════════════════

# Função Objetivo: Agrupa as linhas soltas de GradePrecificacaoML (formato longo) em memória.
class AgrupadorLinhasGrade:

    # Função Objetivo: Recebe o queryset flat e já organiza fallback/reais na hora.
    def __init__(self, linhas):
        self._fallback = {}   # (produto_id, tipo_anuncio) -> {margem: linha}
        self._reais = {}      # produto_id -> [{'variacao_id', 'tipo_anuncio', 'linhas_por_margem'}]

        grupos_por_chave = {}
        for linha in linhas:
            chave = (linha.produto_id, linha.variacao_id, linha.tipo_anuncio)
            grupos_por_chave.setdefault(chave, {})[linha.margem] = linha

        for (produto_id, variacao_id, tipo_anuncio), linhas_por_margem in grupos_por_chave.items():
            if variacao_id is None:
                self._fallback[(produto_id, tipo_anuncio)] = linhas_por_margem
            else:
                self._reais.setdefault(produto_id, []).append({
                    'variacao_id': variacao_id,
                    'tipo_anuncio': tipo_anuncio,
                    'linhas_por_margem': linhas_por_margem,
                })

    # Função Objetivo: Devolve as 4 margens de fallback de 1 produto × tipo.
    def fallback_de(self, produto_id, tipo_anuncio):
        return self._fallback.get((produto_id, tipo_anuncio), {})

    # Função Objetivo: Devolve todas as variações reais de 1 produto.
    def reais_de(self, produto_id):
        return self._reais.get(produto_id, [])


# ═══════════════════════════════════════════════════════════════════
# CAMADA 5 — Contexto final da página
# ═══════════════════════════════════════════════════════════════════

# Função Objetivo: Representa tudo que a tela da Grade precisa pra se desenhar.
@dataclass
class ContextoGradePrecificacao:
    pagina: object
    busca: str
    por_pagina: int
    querystring_sem_pagina: str
    produtos_com_grade: list
    badge_classico: object
    badge_premium: object
    tipo_classico: str
    tipo_premium: str
    marcas_disponiveis: object
    categorias_disponiveis: object
    curvas_disponiveis: object
    filtros_selecionados: dict
    get_params: object
    filtros_preco_classico: list
    filtros_preco_premium: list


# ═══════════════════════════════════════════════════════════════════
# CAMADA 6 — A view em si
# ═══════════════════════════════════════════════════════════════════

# Função Objetivo: Exibe a árvore de precificação por produto (fallback + MLBs reais).
def view_grade_precificacao_ml(request):
    from precificacao.models import GradePrecificacaoML
    from produtos.models import Produto
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre
    from mercado_livre.funcoes_auxiliares.badges import BADGES_TIPO_ANUNCIO, badge_de

    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

    filtros = FiltrosGrade.montar(request)

    # * [EXPLICAÇÃO] → Reaproveita a busca/filtros já validados da
    #                  tela de Produtos — não duplica essa lógica.
    produtos_qs = listar_produtos_filtrados(
        busca=filtros.busca or None, filtros=filtros.para_filtros_produto(), ordenar='titulo'
    )
    produtos_qs = produtos_qs.filter(grade_precificacao_ml__isnull=False).distinct()

    # * [EXPLICAÇÃO] → As 8 faixas de preço filtram pela linha de
    #                  FALLBACK do produto (variacao=None) — é a
    #                  referência de planejamento, não um MLB
    #                  específico.
    for chave, (tipo_valor_grade, margem_valor_grade) in FAIXAS_PRECO_GRADE.items():
        minimo = request.GET.get(f'preco_{chave}_min', '')
        maximo = request.GET.get(f'preco_{chave}_max', '')
        if minimo or maximo:
            condicoes = {
                'grade_precificacao_ml__variacao__isnull': True,
                'grade_precificacao_ml__tipo_anuncio': tipo_valor_grade,
                'grade_precificacao_ml__margem': margem_valor_grade,
            }
            if minimo:
                condicoes['grade_precificacao_ml__preco__gte'] = minimo
            if maximo:
                condicoes['grade_precificacao_ml__preco__lte'] = maximo
            produtos_qs = produtos_qs.filter(**condicoes)

    produtos_qs = produtos_qs.distinct()

    paginator = Paginator(produtos_qs, filtros.por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    produtos_ids = [p.id for p in pagina.object_list]
    linhas = GradePrecificacaoML.objects.filter(
        produto_id__in=produtos_ids
    ).select_related('variacao__anuncio__tipo_de_anuncio')

    agrupador = AgrupadorLinhasGrade(linhas)

    configs = {c.tipo_anuncio: c for c in ConfiguracaoTipoAnuncioMercadoLivre.objects.all()}
    labels_classico = _labels_do_tipo(configs, TipoAnuncio.CLASSICO)
    labels_premium = _labels_do_tipo(configs, TipoAnuncio.PREMIUM)

    badge_classico = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.CLASSICO)
    badge_premium = badge_de(BADGES_TIPO_ANUNCIO, TipoAnuncio.PREMIUM)

    produtos_com_grade = [
        ItemGradeProduto.montar(
            produto, agrupador, badge_classico, badge_premium,
            labels_classico, labels_premium, Classificacao.CATALOGO,
        )
        for produto in pagina.object_list
    ]

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    contexto = ContextoGradePrecificacao(
        pagina=pagina,
        busca=filtros.busca,
        por_pagina=filtros.por_pagina,
        querystring_sem_pagina=querystring_sem_pagina.urlencode(),
        produtos_com_grade=produtos_com_grade,
        badge_classico=badge_classico,
        badge_premium=badge_premium,
        tipo_classico=TipoAnuncio.CLASSICO,
        tipo_premium=TipoAnuncio.PREMIUM,
        marcas_disponiveis=Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        categorias_disponiveis=Produto.objects.exclude(categoria__isnull=True).exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
        curvas_disponiveis=Produto.objects.exclude(curva__isnull=True).exclude(curva='').values_list('curva', flat=True).distinct().order_by('curva'),
        filtros_selecionados={
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        get_params=request.GET,
        filtros_preco_classico=FiltroPrecoExibido.montar_bloco(request, 'classico'),
        filtros_preco_premium=FiltroPrecoExibido.montar_bloco(request, 'premium'),
    )

    return render(request, 'precificacao/estrutura_grade_precificacao_ml.html', vars(contexto))


# ═══════════════════════════════════════════════════════════════════
# CAMADA 7 — Modal de detalhe
# ═══════════════════════════════════════════════════════════════════

# Função Objetivo: Representa 1 linha com par percentual/R$ direto (1 correspondente só).
@dataclass
class LinhaPercentualValor:
    label: str
    percentual: object
    valor: object


# Função Objetivo: Representa 1 linha sem par percentual (só R$ ou só um número).
@dataclass
class LinhaValorUnico:
    label: str
    valor: object


# Função Objetivo: Representa o bloco especial de PIS/COFINS — usado 2x, bases diferentes.
@dataclass
class BlocoPisCofins:
    percentual: object
    credito_entrada: object
    taxa_saida: object


# Função Objetivo: Representa a dimensão efetiva usada no cálculo (altura/largura/comprimento/peso).
@dataclass
class DimensaoUsada:
    origem_label: str
    altura: object
    largura: object
    comprimento: object
    peso: object


# Função Objetivo: Passo 1 — custo final (custo_com_boni + IPI + frete CIF/FOB + ST).
@dataclass
class PassoCustoFinal:
    custo_com_boni: object
    ipi_valor: object
    frete_cif_fob_valor: object
    st_valor: object
    resultado: object


# Função Objetivo: Passo 2 — coleta (metro cúbico × fator de coleta).
@dataclass
class PassoColeta:
    metro_cubico: object
    fator_coleta: object
    resultado: object


# Função Objetivo: Passo 3 — armazenagem (planilha, ou faixa × período).
@dataclass
class PassoArmazenagem:
    origem: str
    periodo_dias: object
    resultado: object


# Função Objetivo: Passo 4 — FIXO (coleta + armazenagem + custo final − créditos).
@dataclass
class PassoFixo:
    coleta: object
    armazenagem: object
    custo_final: object
    credito_icms: object
    credito_pis: object
    resultado: object


# Função Objetivo: Passo 5 — taxa (comissão + ICMS saída + PIS/COFINS saída).
@dataclass
class PassoTaxa:
    itens: list
    resultado: object


# Função Objetivo: Passo 6 — denominador (1 − taxa − margem-alvo).
@dataclass
class PassoDenominador:
    taxa_percentual: object
    margem_alvo_percentual: object
    resultado: object


# Função Objetivo: Passo 7 — faixa de frete escolhida (por peso).
@dataclass
class PassoFaixaFrete:
    peso: object
    faixa_min: object
    faixa_max: object
    resultado: object


# Função Objetivo: Passo 8 — preço exato ((frete + FIXO − rebate) ÷ denominador).
@dataclass
class PassoPrecoExato:
    frete: object
    fixo: object
    rebate: object
    denominador: object
    resultado: object


# Função Objetivo: Representa 1 linha do resultado final (bloco 3).
@dataclass
class LinhaSaida:
    label: str
    valor: object
    tipo: str  # 'reais' ou 'percentual'
    destaque: bool = False


# Função Objetivo: Representa tudo que o modal de auditoria precisa pra se desenhar.
@dataclass
class DetalheFormulaExibida:
    tipo_label: str
    margem_label: str

    tabela_percentuais: list
    pis_cofins: object
    valores_soltos: list
    dimensao: object

    passo_1: object
    passo_2: object
    passo_3: object
    passo_4: object
    passo_5: object
    passo_6: object
    passo_7: object
    passo_8: object
    saida: list

    # Função Objetivo: Lê o detalhamento já persistido e monta a exibição completa.
    # Explicação em detalhe: detalhamento é {entrada, intermediarios, saida} — as 3
    # dataclasses de FormulaPrecificacao já serializadas. NUNCA recalcula nada ao vivo —
    # só lê o que já foi persistido. Valores dentro de um JSONField voltam do MySQL como
    # STRING (JSON não tem tipo Decimal nativo) — por isso toda conversão pra Decimal é
    # feita aqui, não no template. Os 8 passos seguem a ORDEM REAL do cálculo (nunca a
    # ordem de um "extrato" de preço) — entrada → processamento → saída.
    @classmethod
    def montar(cls, linha, tipo_label, margem_label):
        det = linha.detalhamento or {}
        e = det.get('entrada', {})
        i = det.get('intermediarios', {})
        s = det.get('saida', {})

        def dec(valor):
            return Decimal(str(valor)) if valor is not None else None

        origem_label = 'Declarada no ML' if e.get('origem_dimensao') == 'variacao_ml' else 'Embalagem ERP'
        armazenagem_origem = i.get('armazenagem_origem')

        tabela_percentuais = [
            LinhaPercentualValor('IPI', dec(e.get('ipi_percentual')), dec(i.get('ipi_valor'))),
            LinhaPercentualValor('Frete CIF/FOB', dec(e.get('frete_cif_fob_percentual')), dec(i.get('frete_cif_fob_valor'))),
            LinhaPercentualValor('ICMS entrada', dec(e.get('icms_entrada_percentual')), dec(i.get('credito_icms_entrada'))),
            LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor'))),
            LinhaPercentualValor('Comissão', dec(e.get('comissao_percentual')), dec(i.get('comissao_valor'))),
            LinhaPercentualValor('Margem-alvo', dec(e.get('margem_alvo_percentual')), dec(i.get('margem_alvo_valor'))),
        ]

        pis_cofins = BlocoPisCofins(
            percentual=dec(e.get('pis_cofins_percentual')),
            credito_entrada=dec(i.get('credito_pis')),
            taxa_saida=dec(i.get('pis_cofins_valor')),
        )

        valores_soltos = [
            LinhaValorUnico('Custo do produto', dec(e.get('custo'))),
            LinhaValorUnico('Custo com bonificação', dec(e.get('custo_com_boni'))),
            LinhaValorUnico('Substituição tributária (ST)', dec(e.get('st_valor'))),
            LinhaValorUnico('Fator de coleta', dec(e.get('fator_coleta'))),
            LinhaValorUnico('Período de armazenagem (dias)', dec(e.get('periodo_armazenagem'))),
        ]

        dimensao = DimensaoUsada(
            origem_label=origem_label,
            altura=dec(e.get('altura')), largura=dec(e.get('largura')),
            comprimento=dec(e.get('comprimento')), peso=dec(e.get('peso')),
        )

        passo_1 = PassoCustoFinal(
            custo_com_boni=dec(e.get('custo_com_boni')), ipi_valor=dec(i.get('ipi_valor')),
            frete_cif_fob_valor=dec(i.get('frete_cif_fob_valor')), st_valor=dec(e.get('st_valor')),
            resultado=dec(i.get('custo_final')),
        )
        passo_2 = PassoColeta(
            metro_cubico=dec(i.get('metro_cubico')), fator_coleta=dec(e.get('fator_coleta')),
            resultado=dec(i.get('coleta')),
        )
        passo_3 = PassoArmazenagem(
            origem=armazenagem_origem, periodo_dias=dec(e.get('periodo_armazenagem')),
            resultado=dec(i.get('armazenagem')),
        )
        passo_4 = PassoFixo(
            coleta=dec(i.get('coleta')), armazenagem=dec(i.get('armazenagem')),
            custo_final=dec(i.get('custo_final')), credito_icms=dec(i.get('credito_icms_entrada')),
            credito_pis=dec(i.get('credito_pis')), resultado=dec(i.get('fixo')),
        )
        passo_5 = PassoTaxa(
            itens=[
                LinhaPercentualValor('Comissão', dec(e.get('comissao_percentual')), dec(i.get('comissao_valor'))),
                LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor'))),
                LinhaPercentualValor('PIS/COFINS (saída)', dec(e.get('pis_cofins_percentual')), dec(i.get('pis_cofins_valor'))),
            ],
            resultado=dec(i.get('taxa_percentual')),
        )
        passo_6 = PassoDenominador(
            taxa_percentual=dec(i.get('taxa_percentual')), margem_alvo_percentual=dec(e.get('margem_alvo_percentual')),
            resultado=dec(i.get('denominador')),
        )
        passo_7 = PassoFaixaFrete(
            peso=dec(e.get('peso')), faixa_min=dec(i.get('faixa_frete_preco_min')),
            faixa_max=dec(i.get('faixa_frete_preco_max')), resultado=dec(s.get('frete_usado')),
        )
        passo_8 = PassoPrecoExato(
            frete=dec(s.get('frete_usado')), fixo=dec(i.get('fixo')), rebate=dec(i.get('rebate_valor')),
            denominador=dec(i.get('denominador')), resultado=dec(i.get('preco_exato_antes_arredondar')),
        )

        saida = [
            LinhaSaida('Preço exato', dec(i.get('preco_exato_antes_arredondar')), 'reais'),
            LinhaSaida('Margem exata', dec(s.get('margem_exata_percentual')), 'percentual'),
            LinhaSaida('Preço final (arredondado pra ,90)', dec(s.get('preco_final')), 'reais', destaque=True),
            LinhaSaida('Margem final', dec(s.get('margem_percentual_obtida')), 'percentual', destaque=True),
            LinhaSaida('Custo de frete final', dec(s.get('frete_usado')), 'reais'),
        ]

        return cls(
            tipo_label=tipo_label,
            margem_label=margem_label,
            tabela_percentuais=tabela_percentuais,
            pis_cofins=pis_cofins,
            valores_soltos=valores_soltos,
            dimensao=dimensao,
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=saida,
        )


# Função Objetivo: Exibe o modal "como chegamos nesse preço" pra 1 margem específica.
def view_grade_detalhe(request, produto_id, tipo, margem):
    from precificacao.models import GradePrecificacaoML

    # * [EXPLICAÇÃO] → variacao vem por querystring (?variacao=<id>),
    #                  não pelo caminho da URL — ausente/vazio =
    #                  fallback do produto (variacao=None).
    variacao_id = request.GET.get('variacao') or None
    tipo_grade = TIPO_ML_PARA_GRADE.get(tipo)

    linha = None
    if tipo_grade and margem in MARGENS_POR_CHAVE:
        linha = GradePrecificacaoML.objects.filter(
            produto_id=produto_id, variacao_id=variacao_id,
            tipo_anuncio=tipo_grade, margem=margem,
        ).select_related('produto', 'variacao__anuncio').first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
            'sem_detalhamento': True,
        })

    tipo_label = 'Clássico' if tipo_grade == 'classico' else 'Premium'
    margem_label = MARGENS_POR_CHAVE[margem].label_base

    # * [EXPLICAÇÃO] → Identificação do anúncio no cabeçalho do modal —
    #                  sem variação real (fallback do produto), só
    #                  título/EAN do produto fazem sentido, não tem
    #                  MLB nenhum pra mostrar.
    if linha.variacao_id:
        mlb = linha.variacao.anuncio.mlb
        titulo_anuncio = linha.variacao.anuncio.titulo_anuncio or linha.produto.titulo
    else:
        mlb = None
        titulo_anuncio = linha.produto.titulo

    det = DetalheFormulaExibida.montar(linha, tipo_label, margem_label)

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe.html', {
        'det': det,
        'mlb': mlb,
        'titulo_anuncio': titulo_anuncio,
        'produto_id': produto_id,
        'tipo': tipo,
        'variacao_id': variacao_id or '',
    })


# ═══════════════════════════════════════════════════════════════════
# Resumo por Marketplace — FORA DE ESCOPO, ainda quebrado
# (só ajustado pra referenciar MARGENS em vez de ORDEM_MARGENS/
# LABELS_MARGEM_FILTRO, que não existem mais — evita NameError na
# importação do módulo. A leitura de campos largos de
# GradePrecificacaoML continua quebrada, como já era esperado.)
# ═══════════════════════════════════════════════════════════════════

def _montar_linha_resumo(produto, margem_alvo):
    """Monta o dict de 1 linha da tabela de resumo — SEMPRE a partir
    do FALLBACK do produto (variacao=None), a referência de
    planejamento. AINDA NÃO MIGRADO pro formato longo — pendência
    registrada."""
    from precificacao.models import GradePrecificacaoML

    linha = GradePrecificacaoML.objects.filter(produto=produto, variacao__isnull=True).first()

    def campo(prefixo, sufixo):
        return getattr(linha, f'{prefixo}_{margem_alvo}_{sufixo}', None) if linha else None

    return {
        'produto': produto,
        'margem_atual': margem_alvo,
        'classico_preco': campo('classico', 'preco'),
        'classico_margem': campo('classico', 'margem'),
        'classico_frete': linha.frete_classico_usado if linha else None,
        'premium_preco': campo('premium', 'preco'),
        'premium_margem': campo('premium', 'margem'),
        'premium_frete': linha.frete_premium_usado if linha else None,
    }


def view_resumo_marketplaces(request):
    from produtos.models import Produto
    from precificacao.models import GradePrecificacaoML

    margem_geral = request.GET.get('margem', 'padrao')
    if margem_geral not in MARGENS_CHAVES:
        margem_geral = 'padrao'

    busca = request.GET.get('busca', '').strip()
    por_pagina = request.GET.get('por_pagina', '25')
    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    filtros_produto = {
        'marcas': request.GET.getlist('marca'),
        'categorias': request.GET.getlist('categoria'),
        'curvas': request.GET.getlist('curva'),
        'estoque_min': request.GET.get('estoque_min', ''),
        'estoque_max': request.GET.get('estoque_max', ''),
        'custo_min': request.GET.get('custo_min', ''),
        'custo_max': request.GET.get('custo_max', ''),
    }
    produtos_qs = listar_produtos_filtrados(busca=busca or None, filtros=filtros_produto, ordenar='titulo')
    produtos_qs = produtos_qs.filter(grade_precificacao_ml__isnull=False).distinct()

    paginator = Paginator(produtos_qs, por_pagina)
    pagina = paginator.get_page(request.GET.get('pagina', 1))

    linhas_tabela = [_montar_linha_resumo(produto, margem_geral) for produto in pagina.object_list]

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'precificacao/estrutura_resumo_marketplaces.html', {
        'pagina': pagina,
        'busca': busca,
        'por_pagina': por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
        'margem_geral': margem_geral,
        'opcoes_margem': [(m.chave, m.label_padrao) for m in MARGENS],
        'linhas_tabela': linhas_tabela,
        'marcas_disponiveis': Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca'),
        'categorias_disponiveis': Produto.objects.exclude(categoria__isnull=True).exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
        'curvas_disponiveis': Produto.objects.exclude(curva__isnull=True).exclude(curva='').values_list('curva', flat=True).distinct().order_by('curva'),
        'filtros_selecionados': {
            'marca': filtros_produto['marcas'],
            'categoria': filtros_produto['categorias'],
            'curva': filtros_produto['curvas'],
        },
        'get_params': request.GET,
    })


def view_resumo_linha(request, produto_id):
    from django.shortcuts import get_object_or_404
    from produtos.models import Produto

    margem = request.GET.get('margem', 'padrao')
    if margem not in MARGENS_CHAVES:
        margem = 'padrao'

    produto = get_object_or_404(Produto, id=produto_id)
    linha = _montar_linha_resumo(produto, margem)

    return render(request, 'precificacao/parciais/estrutura_parcial_resumo_linha.html', {
        'linha': linha,
        'opcoes_margem': [(m.chave, m.label_padrao) for m in MARGENS],
    })