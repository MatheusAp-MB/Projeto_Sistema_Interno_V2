# precificacao/views/grade_mercado_livre.py

from dataclasses import dataclass, field
from decimal import Decimal
from django.shortcuts import render
from precificacao.views.comum import (
    MARGENS_POR_CHAVE, _labels_do_tipo, FiltroPrecoExibido,
    LinhaMargemExibida, _opcoes_filtro_produto, _filtrar_paginar_produtos_grade,
)
from precificacao.views.modal_comum import (
    PassoFaixaFrete, PassoPrecoExato,
    montar_tabela_percentuais, montar_pis_cofins, montar_valores_soltos,
    montar_dimensao, montar_passos_1_a_6, montar_saida,
)

# * [EXPLICAÇÃO] → GradePrecificacaoML.tipo_anuncio usa 'classico'/
#                  'premium' (valores próprios, simples). URLs e os
#                  cards de fallback usam o código REAL do ML
#                  (TipoDeAnuncioMercadoLivre.TipoAnuncio =
#                  'gold_special'/'gold_pro'). Os 2 sentidos de
#                  tradução moram aqui, únicos, reaproveitados pelo
#                  card de MLB e pelo modal de detalhe.
TIPO_GRADE_PARA_ML = {'classico': 'gold_special', 'premium': 'gold_pro'}
TIPO_ML_PARA_GRADE = {v: k for k, v in TIPO_GRADE_PARA_ML.items()}

# * [EXPLICAÇÃO] → Traduz "prefixo de querystring" → (tipo_anuncio,
#                  margem) da GradePrecificacaoML (formato longo).
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


# Função Objetivo: Aplica 1 faixa de preço (tipo+margem) do ML — usada por _filtrar_paginar_produtos_grade.
def _aplicar_filtro_preco_ml(produtos_qs, dados_extra, minimo, maximo):
    tipo_valor_grade, margem_valor_grade = dados_extra
    condicoes = {
        'grade_precificacao_ml__variacao__isnull': True,
        'grade_precificacao_ml__tipo_anuncio': tipo_valor_grade,
        'grade_precificacao_ml__margem': margem_valor_grade,
    }
    if minimo:
        condicoes['grade_precificacao_ml__preco__gte'] = minimo
    if maximo:
        condicoes['grade_precificacao_ml__preco__lte'] = maximo
    return produtos_qs.filter(**condicoes)


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


# Função Objetivo: Agrupa as linhas soltas de GradePrecificacaoML (formato longo) em memória.
class AgrupadorLinhasGrade:

    def __init__(self, linhas):
        self._fallback = {}
        self._reais = {}

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

    def fallback_de(self, produto_id, tipo_anuncio):
        return self._fallback.get((produto_id, tipo_anuncio), {})

    def reais_de(self, produto_id):
        return self._reais.get(produto_id, [])


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


# Função Objetivo: Exibe a árvore de precificação por produto (fallback + MLBs reais).
def view_grade_precificacao_ml(request):
    from precificacao.models import GradePrecificacaoML
    from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre
    from mercado_livre.funcoes_auxiliares.badges import BADGES_TIPO_ANUNCIO, badge_de

    TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
    Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

    filtros, pagina, querystring_sem_pagina = _filtrar_paginar_produtos_grade(
        request, 'grade_precificacao_ml', FAIXAS_PRECO_GRADE, _aplicar_filtro_preco_ml
    )

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

    contexto = ContextoGradePrecificacao(
        pagina=pagina,
        busca=filtros.busca,
        por_pagina=filtros.por_pagina,
        querystring_sem_pagina=querystring_sem_pagina,
        produtos_com_grade=produtos_com_grade,
        badge_classico=badge_classico,
        badge_premium=badge_premium,
        tipo_classico=TipoAnuncio.CLASSICO,
        tipo_premium=TipoAnuncio.PREMIUM,
        filtros_selecionados={
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        get_params=request.GET,
        filtros_preco_classico=FiltroPrecoExibido.montar_bloco(request, 'classico'),
        filtros_preco_premium=FiltroPrecoExibido.montar_bloco(request, 'premium'),
        **_opcoes_filtro_produto(),
    )

    return render(request, 'precificacao/estrutura_grade_precificacao_ml.html', vars(contexto))


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
    # Explicação em detalhe: NUNCA recalcula nada ao vivo — só lê o que já foi persistido.
    @classmethod
    def montar(cls, linha, tipo_label, margem_label):
        det = linha.detalhamento or {}
        e = det.get('entrada', {})
        i = det.get('intermediarios', {})
        s = det.get('saida', {})

        def dec(valor):
            return Decimal(str(valor)) if valor is not None else None

        origem_label = 'Declarada no ML' if e.get('origem_dimensao') == 'variacao_ml' else 'Embalagem ERP'

        passo_1, passo_2, passo_3, passo_4, passo_5, passo_6 = montar_passos_1_a_6(e, i, dec)

        # * [EXPLICAÇÃO] → passo_7/8 ficam FORA do helper compartilhado —
        #                  faixa_min/max aqui é limite de PREÇO (o ML
        #                  busca faixa por peso×preço), e existe rebate,
        #                  os 2 pontos que genuinamente divergem do Magalu.
        passo_7 = PassoFaixaFrete(
            peso=dec(e.get('peso')), faixa_min=dec(i.get('faixa_frete_preco_min')),
            faixa_max=dec(i.get('faixa_frete_preco_max')), resultado=dec(s.get('frete_usado')),
        )
        passo_8 = PassoPrecoExato(
            frete=dec(s.get('frete_usado')), fixo=dec(i.get('fixo')), rebate=dec(i.get('rebate_valor')),
            denominador=dec(i.get('denominador')), resultado=dec(i.get('preco_exato_antes_arredondar')),
        )

        return cls(
            tipo_label=tipo_label,
            margem_label=margem_label,
            tabela_percentuais=montar_tabela_percentuais(e, i, dec),
            pis_cofins=montar_pis_cofins(e, i, dec),
            valores_soltos=montar_valores_soltos(e, dec),
            dimensao=montar_dimensao(e, dec, origem_label),
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=montar_saida(i, s, dec),
        )


# Função Objetivo: Exibe o modal "como chegamos nesse preço" pra 1 margem específica.
def view_grade_detalhe(request, produto_id, tipo, margem):
    from precificacao.models import GradePrecificacaoML

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


# Função Objetivo: Monta a subquery que busca 1 campo de 1 marketplace/margem, por produto.
def subquery_grade_campo(tipo, campo, margem_geral):
    from django.db.models import Subquery, OuterRef, DecimalField
    from precificacao.models import GradePrecificacaoML

    return Subquery(
        GradePrecificacaoML.objects.filter(
            produto=OuterRef('pk'), variacao__isnull=True,
            tipo_anuncio=tipo, margem=margem_geral,
        ).values(campo)[:1],
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )