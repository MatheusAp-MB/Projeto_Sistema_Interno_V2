# precificacao/views/grade_magalu.py

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

# * [EXPLICAÇÃO] → Sem tipo_anuncio (Magalu não tem Clássico/Premium) —
#                  só 4 faixas de preço, não 8.
FAIXAS_PRECO_GRADE_MAGALU = {
    'magalu_competicao': 'competicao',
    'magalu_minima': 'minima',
    'magalu_padrao': 'padrao',
    'magalu_maxima': 'maxima',
}


# Função Objetivo: Aplica 1 faixa de preço (só margem) do Magalu — usada por _filtrar_paginar_produtos_grade.
def _aplicar_filtro_preco_magalu(produtos_qs, margem_valor, minimo, maximo):
    condicoes = {'grade_precificacao_magalu__margem': margem_valor}
    if minimo:
        condicoes['grade_precificacao_magalu__preco__gte'] = minimo
    if maximo:
        condicoes['grade_precificacao_magalu__preco__lte'] = maximo
    return produtos_qs.filter(**condicoes)


# Função Objetivo: Representa 1 produto na árvore da Grade Magalu — sem MLB, sem tipo.
@dataclass
class ItemGradeMagaluProduto:
    produto: object
    linhas_margem: list

    # Função Objetivo: Monta 1 item a partir do produto e das linhas já agrupadas.
    @classmethod
    def montar(cls, produto, agrupador, labels):
        linhas_por_margem = agrupador.linhas_de(produto.id)
        return cls(
            produto=produto,
            linhas_margem=LinhaMargemExibida.montar_bloco(linhas_por_margem, labels),
        )


# Função Objetivo: Agrupa as linhas soltas de GradePrecificacaoMagalu em memória.
class AgrupadorLinhasGradeMagalu:

    def __init__(self, linhas):
        self._por_produto = {}
        for linha in linhas:
            self._por_produto.setdefault(linha.produto_id, {})[linha.margem] = linha

    def linhas_de(self, produto_id):
        return self._por_produto.get(produto_id, {})


# Função Objetivo: Exibe a árvore de precificação do Magalu — 1 card simples por produto.
def view_grade_precificacao_magalu(request):
    from precificacao.models import GradePrecificacaoMagalu

    filtros, pagina, querystring_sem_pagina = _filtrar_paginar_produtos_grade(
        request, 'grade_precificacao_magalu', FAIXAS_PRECO_GRADE_MAGALU, _aplicar_filtro_preco_magalu
    )

    produtos_ids = [p.id for p in pagina.object_list]
    linhas = GradePrecificacaoMagalu.objects.filter(produto_id__in=produtos_ids)
    agrupador = AgrupadorLinhasGradeMagalu(linhas)

    labels_magalu = [m.label_padrao for m in MARGENS]

    produtos_com_grade = [
        ItemGradeMagaluProduto.montar(produto, agrupador, labels_magalu)
        for produto in pagina.object_list
    ]

    return render(request, 'precificacao/estrutura_grade_precificacao_magalu.html', {
        'pagina': pagina,
        'busca': filtros.busca,
        'por_pagina': filtros.por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina,
        'produtos_com_grade': produtos_com_grade,
        'filtros_selecionados': {
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        'get_params': request.GET,
        'filtros_preco_magalu': FiltroPrecoExibido.montar_bloco(request, 'magalu'),
        **_opcoes_filtro_produto(),
    })


# Função Objetivo: Representa o modal de auditoria do Magalu.
@dataclass
class DetalheFormulaExibidaMagalu:
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
    # Explicação em detalhe: sem tipo_label (Magalu não tem Clássico/Premium), sem rebate,
    # dimensão sempre "Embalagem ERP", passo 7 usa faixa de PESO (não de preço).
    @classmethod
    def montar(cls, linha, margem_label):
        det = linha.detalhamento or {}
        e = det.get('entrada', {})
        i = det.get('intermediarios', {})
        s = det.get('saida', {})

        def dec(valor):
            return Decimal(str(valor)) if valor is not None else None

        passo_1, passo_2, passo_3, passo_4, passo_5, passo_6 = montar_passos_1_a_6(
            e, i, dec, label_comissao='Comissão Magalu'
        )

        taxa_unidade = dec(e.get('taxa_unidade_fixa'))

        passo_7 = PassoFaixaFrete(
            peso=dec(e.get('peso')), faixa_min=dec(i.get('faixa_frete_peso_min')),
            faixa_max=dec(i.get('faixa_frete_peso_max')), resultado=dec(s.get('frete_usado')),
        )
        passo_8 = PassoPrecoExato(
            frete=dec(s.get('frete_usado')), fixo=dec(i.get('fixo')), rebate=Decimal('0'),
            denominador=dec(i.get('denominador')), resultado=dec(i.get('preco_exato_antes_arredondar')),
            taxa_unidade=taxa_unidade,
        )

        valores_soltos = montar_valores_soltos(e, dec)
        valores_soltos.append(LinhaValorUnico('Taxa unidade (fixa)', taxa_unidade))

        return cls(
            margem_label=margem_label,
            tabela_percentuais=montar_tabela_percentuais(e, i, dec, label_comissao='Comissão Magalu'),
            pis_cofins=montar_pis_cofins(e, i, dec),
            valores_soltos=valores_soltos,
            dimensao=montar_dimensao(e, dec, origem_label='Embalagem ERP'),
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=montar_saida(i, s, dec),
        )


# Função Objetivo: Exibe o modal "como chegamos nesse preço" do Magalu, pra 1 margem.
def view_grade_detalhe_magalu(request, produto_id, margem):
    from precificacao.models import GradePrecificacaoMagalu

    linha = None
    if margem in MARGENS_POR_CHAVE:
        linha = GradePrecificacaoMagalu.objects.filter(
            produto_id=produto_id, margem=margem,
        ).select_related('produto').first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_magalu.html', {
            'sem_detalhamento': True,
        })

    margem_label = MARGENS_POR_CHAVE[margem].label_base
    det = DetalheFormulaExibidaMagalu.montar(linha, margem_label)

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_magalu.html', {
        'det': det,
        'produto_id': produto_id,
        'produto_titulo': linha.produto.titulo,
        'margem': margem,
    })


# Função Objetivo: Monta a subquery que busca 1 campo do Magalu/margem, por produto.
def subquery_grade_magalu_campo(campo, margem_geral):
    from django.db.models import Subquery, OuterRef, DecimalField
    from precificacao.models import GradePrecificacaoMagalu

    return Subquery(
        GradePrecificacaoMagalu.objects.filter(
            produto=OuterRef('pk'), margem=margem_geral,
        ).values(campo)[:1],
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )