# precificacao/views/grade_raia.py

from dataclasses import dataclass
from decimal import Decimal
from django.shortcuts import render
from precificacao.views.comum import (
    MARGENS, MARGENS_POR_CHAVE, FiltroPrecoExibido, LinhaMargemExibida,
    _opcoes_filtro_produto, _filtrar_paginar_produtos_grade,
)
from precificacao.views.modal_comum import (
    PassoFaixaFrete, PassoPrecoExato,
    montar_tabela_percentuais, montar_pis_cofins, montar_valores_soltos,
    montar_dimensao, montar_passos_1_a_6, montar_saida,
)

# * [EXPLICAÇÃO] → Sem tipo_anuncio (Raia não tem Clássico/Premium) —
#                  só 4 faixas de preço, não 8.
FAIXAS_PRECO_GRADE_RAIA = {
    'raia_competicao': 'competicao',
    'raia_minima': 'minima',
    'raia_padrao': 'padrao',
    'raia_maxima': 'maxima',
}


def _aplicar_filtro_preco_raia(produtos_qs, margem_valor, minimo, maximo):
    condicoes = {'grade_precificacao_raia__margem': margem_valor}
    if minimo:
        condicoes['grade_precificacao_raia__preco__gte'] = minimo
    if maximo:
        condicoes['grade_precificacao_raia__preco__lte'] = maximo
    return produtos_qs.filter(**condicoes)


@dataclass
class ItemGradeRaiaProduto:
    produto: object
    linhas_margem: list

    @classmethod
    def montar(cls, produto, agrupador, labels):
        linhas_por_margem = agrupador.linhas_de(produto.id)
        return cls(
            produto=produto,
            linhas_margem=LinhaMargemExibida.montar_bloco(linhas_por_margem, labels),
        )


class AgrupadorLinhasGradeRaia:

    def __init__(self, linhas):
        self._por_produto = {}
        for linha in linhas:
            self._por_produto.setdefault(linha.produto_id, {})[linha.margem] = linha

    def linhas_de(self, produto_id):
        return self._por_produto.get(produto_id, {})


def view_grade_precificacao_raia(request):
    from precificacao.models import GradePrecificacaoRaia

    filtros, pagina, querystring_sem_pagina = _filtrar_paginar_produtos_grade(
        request, 'grade_precificacao_raia', FAIXAS_PRECO_GRADE_RAIA, _aplicar_filtro_preco_raia
    )

    produtos_ids = [p.id for p in pagina.object_list]
    linhas = GradePrecificacaoRaia.objects.filter(produto_id__in=produtos_ids)
    agrupador = AgrupadorLinhasGradeRaia(linhas)

    labels_raia = [m.label_padrao for m in MARGENS]

    produtos_com_grade = [
        ItemGradeRaiaProduto.montar(produto, agrupador, labels_raia)
        for produto in pagina.object_list
    ]

    return render(request, 'precificacao/estrutura_grade_precificacao_raia.html', {
        'pagina': pagina,
        'busca': filtros.busca,
        'por_pagina': filtros.por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina,
        'produtos_com_grade': produtos_com_grade,
        'filtros_selecionados': {
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        'get_params': request.GET,
        'filtros_preco_raia': FiltroPrecoExibido.montar_bloco(request, 'raia'),
        **_opcoes_filtro_produto(),
    })


@dataclass
class DetalheFormulaExibidaRaia:
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
    # Explicação em detalhe: mais simples que ML/Magalu — sem tipo_label, sem rebate,
    # sem taxa unidade, dimensão sempre "Embalagem ERP", frete sempre fixo (sem peso/faixa
    # nenhuma — passo 7 mostra só o valor configurado).
    @classmethod
    def montar(cls, linha, margem_label):
        det = linha.detalhamento or {}
        e = det.get('entrada', {})
        i = det.get('intermediarios', {})
        s = det.get('saida', {})

        def dec(valor):
            return Decimal(str(valor)) if valor is not None else None

        passo_1, passo_2, passo_3, passo_4, passo_5, passo_6 = montar_passos_1_a_6(
            e, i, dec, label_comissao='Comissão Raia'
        )

        # * [EXPLICAÇÃO] → peso/faixa_min/faixa_max ficam None de propósito —
        #                  a Raia não busca faixa nenhuma, o frete já vem
        #                  fixo da config. O template detecta isso e
        #                  mostra a versão simplificada.
        passo_7 = PassoFaixaFrete(
            peso=None, faixa_min=None, faixa_max=None, resultado=dec(s.get('frete_usado')),
        )
        passo_8 = PassoPrecoExato(
            frete=dec(s.get('frete_usado')), fixo=dec(i.get('fixo')), rebate=Decimal('0'),
            denominador=dec(i.get('denominador')), resultado=dec(i.get('preco_exato_antes_arredondar')),
        )

        return cls(
            margem_label=margem_label,
            tabela_percentuais=montar_tabela_percentuais(e, i, dec, label_comissao='Comissão Raia'),
            pis_cofins=montar_pis_cofins(e, i, dec),
            valores_soltos=montar_valores_soltos(e, dec),
            dimensao=montar_dimensao(e, dec, origem_label='Embalagem ERP'),
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=montar_saida(i, s, dec),
        )


def view_grade_detalhe_raia(request, produto_id, margem):
    from precificacao.models import GradePrecificacaoRaia

    linha = None
    if margem in MARGENS_POR_CHAVE:
        linha = GradePrecificacaoRaia.objects.filter(
            produto_id=produto_id, margem=margem,
        ).select_related('produto').first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_raia.html', {
            'sem_detalhamento': True,
        })

    margem_label = MARGENS_POR_CHAVE[margem].label_base
    det = DetalheFormulaExibidaRaia.montar(linha, margem_label)

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_raia.html', {
        'det': det,
        'produto_id': produto_id,
        'produto_titulo': linha.produto.titulo,
        'margem': margem,
    })


def subquery_grade_raia_campo(campo, margem_geral):
    from django.db.models import Subquery, OuterRef, DecimalField
    from precificacao.models import GradePrecificacaoRaia

    return Subquery(
        GradePrecificacaoRaia.objects.filter(
            produto=OuterRef('pk'), margem=margem_geral,
        ).values(campo)[:1],
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )