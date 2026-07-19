# precificacao/views/grade_amazon.py

from dataclasses import dataclass
from decimal import Decimal
from django.shortcuts import render
from precificacao.views.comum import (
    MARGENS, MARGENS_POR_CHAVE, FiltroPrecoExibido, LinhaMargemExibida,
    _opcoes_filtro_produto, _filtrar_paginar_produtos_grade,
)
from precificacao.views.modal_comum import (
    PassoFaixaFrete, PassoPrecoExato, LinhaValorUnico,
    montar_tabela_percentuais, montar_pis_cofins, montar_valores_soltos,
    montar_dimensao, montar_passos_1_a_6, montar_saida,
)

FAIXAS_PRECO_GRADE_AMAZON = {
    'amazon_dba_competicao': ('dba', 'competicao'),
    'amazon_dba_minima': ('dba', 'minima'),
    'amazon_dba_padrao': ('dba', 'padrao'),
    'amazon_dba_maxima': ('dba', 'maxima'),
    'amazon_fba_competicao': ('fba', 'competicao'),
    'amazon_fba_minima': ('fba', 'minima'),
    'amazon_fba_padrao': ('fba', 'padrao'),
    'amazon_fba_maxima': ('fba', 'maxima'),
}


def _aplicar_filtro_preco_amazon(produtos_qs, dados_extra, minimo, maximo):
    tipo, margem_valor = dados_extra
    condicoes = {'grade_precificacao_amazon__tipo': tipo, 'grade_precificacao_amazon__margem': margem_valor}
    if minimo:
        condicoes['grade_precificacao_amazon__preco__gte'] = minimo
    if maximo:
        condicoes['grade_precificacao_amazon__preco__lte'] = maximo
    return produtos_qs.filter(**condicoes)


@dataclass
class ItemGradeAmazonProduto:
    produto: object
    linhas_dba: list
    linhas_fba: list

    @classmethod
    def montar(cls, produto, agrupador, labels):
        return cls(
            produto=produto,
            linhas_dba=LinhaMargemExibida.montar_bloco(agrupador.linhas_de(produto.id, 'dba'), labels),
            linhas_fba=LinhaMargemExibida.montar_bloco(agrupador.linhas_de(produto.id, 'fba'), labels),
        )


class AgrupadorLinhasGradeAmazon:

    def __init__(self, linhas):
        self._por_produto_tipo = {}
        for linha in linhas:
            self._por_produto_tipo.setdefault((linha.produto_id, linha.tipo), {})[linha.margem] = linha

    def linhas_de(self, produto_id, tipo):
        return self._por_produto_tipo.get((produto_id, tipo), {})


def view_grade_precificacao_amazon(request):
    from precificacao.models import GradePrecificacaoAmazon

    filtros, pagina, querystring_sem_pagina = _filtrar_paginar_produtos_grade(
        request, 'grade_precificacao_amazon', FAIXAS_PRECO_GRADE_AMAZON, _aplicar_filtro_preco_amazon
    )

    produtos_ids = [p.id for p in pagina.object_list]
    linhas = GradePrecificacaoAmazon.objects.filter(produto_id__in=produtos_ids)
    agrupador = AgrupadorLinhasGradeAmazon(linhas)

    labels_amazon = [m.label_padrao for m in MARGENS]

    produtos_com_grade = [
        ItemGradeAmazonProduto.montar(produto, agrupador, labels_amazon)
        for produto in pagina.object_list
    ]

    return render(request, 'precificacao/estrutura_grade_precificacao_amazon.html', {
        'pagina': pagina,
        'busca': filtros.busca,
        'por_pagina': filtros.por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina,
        'produtos_com_grade': produtos_com_grade,
        'filtros_selecionados': {
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        'get_params': request.GET,
        'filtros_preco_dba': FiltroPrecoExibido.montar_bloco(request, 'amazon_dba'),
        'filtros_preco_fba': FiltroPrecoExibido.montar_bloco(request, 'amazon_fba'),
        **_opcoes_filtro_produto(),
    })


@dataclass
class DetalheFormulaExibidaAmazon:
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

    # Função Objetivo: Lê o detalhamento persistido e monta a exibição completa.
    # Explicação em detalhe: tipo_label (DBA/FBA) igual ao ML (Clássico/Premium). Comissão
    # é FLAT (sem variar por faixa) — passo_5 usa os 3 itens padrão, sem item extra. Passo 7
    # mostra a faixa de preço + peso usado (quando veio da matriz) ou "sem depender de
    # peso" (faixa baixa) — reaproveita PassoFaixaFrete igual ao Shopee/TikTok.
    @classmethod
    def montar(cls, linha, tipo_label, margem_label):
        det = linha.detalhamento or {}
        e = det.get('entrada', {})
        i = det.get('intermediarios', {})
        s = det.get('saida', {})

        def dec(valor):
            return Decimal(str(valor)) if valor is not None else None

        passo_1, passo_2, passo_3, passo_4, passo_5, passo_6 = montar_passos_1_a_6(
            e, i, dec, label_comissao='Comissão Amazon'
        )

        passo_7 = PassoFaixaFrete(
            peso=dec(e.get('peso')), faixa_min=dec(i.get('faixa_preco_min')),
            faixa_max=dec(i.get('faixa_preco_max')), resultado=dec(s.get('frete_usado')),
        )
        passo_8 = PassoPrecoExato(
            frete=dec(s.get('frete_usado')), fixo=dec(i.get('fixo')), rebate=Decimal('0'),
            denominador=dec(i.get('denominador')), resultado=dec(i.get('preco_exato_antes_arredondar')),
        )

        valores_soltos = montar_valores_soltos(e, dec)
        peso_min_usado = dec(i.get('peso_min_usado'))
        peso_max_usado = dec(i.get('peso_max_usado'))
        if peso_min_usado is not None:
            valores_soltos.append(LinhaValorUnico(
                'Faixa de peso usada na matriz', f'{peso_min_usado}-{peso_max_usado}kg',
            ))
        else:
            valores_soltos.append(LinhaValorUnico('Faixa de peso usada', 'nenhuma — preço abaixo de R$79, frete fixo'))

        return cls(
            tipo_label=tipo_label,
            margem_label=margem_label,
            tabela_percentuais=montar_tabela_percentuais(e, i, dec, label_comissao='Comissão Amazon'),
            pis_cofins=montar_pis_cofins(e, i, dec),
            valores_soltos=valores_soltos,
            dimensao=montar_dimensao(e, dec, origem_label='Embalagem ERP'),
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=montar_saida(i, s, dec),
        )


def view_grade_detalhe_amazon(request, produto_id, tipo, margem):
    from precificacao.models import GradePrecificacaoAmazon

    linha = None
    if margem in MARGENS_POR_CHAVE and tipo in ('dba', 'fba'):
        linha = GradePrecificacaoAmazon.objects.filter(
            produto_id=produto_id, tipo=tipo, margem=margem,
        ).select_related('produto').first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_amazon.html', {
            'sem_detalhamento': True,
        })

    tipo_label = 'DBA' if tipo == 'dba' else 'FBA'
    margem_label = MARGENS_POR_CHAVE[margem].label_base
    det = DetalheFormulaExibidaAmazon.montar(linha, tipo_label, margem_label)

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_amazon.html', {
        'det': det,
        'produto_id': produto_id,
        'produto_titulo': linha.produto.titulo,
        'tipo': tipo,
        'margem': margem,
    })


def subquery_grade_amazon_campo(tipo, campo, margem_geral):
    from django.db.models import Subquery, OuterRef, DecimalField
    from precificacao.models import GradePrecificacaoAmazon

    return Subquery(
        GradePrecificacaoAmazon.objects.filter(
            produto=OuterRef('pk'), tipo=tipo, margem=margem_geral,
        ).values(campo)[:1],
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )