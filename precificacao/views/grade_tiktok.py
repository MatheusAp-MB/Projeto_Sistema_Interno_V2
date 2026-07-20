# precificacao/views/grade_tiktok.py

from dataclasses import dataclass
from decimal import Decimal
from django.shortcuts import render
from precificacao.views.comum import (
    MARGENS, MARGENS_POR_CHAVE, FiltroPrecoExibido, LinhaMargemExibida,
    _opcoes_filtro_produto, _filtrar_paginar_produtos_grade,
)
from precificacao.views.modal_comum import (
    PassoFaixaFrete, PassoPrecoExato, PassoTaxa, LinhaPercentualValor, LinhaSaida,
    montar_tabela_percentuais, montar_pis_cofins, montar_valores_soltos,
    montar_dimensao, montar_passos_1_a_6, montar_saida,
)
from decimal import Decimal

# * [EXPLICAÇÃO] → Único marketplace fora do ML com "tipo" — 8 faixas de preço
#                  (2 tipos × 4 margens), mesmo formato do ML.
FAIXAS_PRECO_GRADE_TIKTOK = {
    'tiktok_sem_afiliado_competicao': ('sem_afiliado', 'competicao'),
    'tiktok_sem_afiliado_minima': ('sem_afiliado', 'minima'),
    'tiktok_sem_afiliado_padrao': ('sem_afiliado', 'padrao'),
    'tiktok_sem_afiliado_maxima': ('sem_afiliado', 'maxima'),
    'tiktok_com_afiliado_competicao': ('com_afiliado', 'competicao'),
    'tiktok_com_afiliado_minima': ('com_afiliado', 'minima'),
    'tiktok_com_afiliado_padrao': ('com_afiliado', 'padrao'),
    'tiktok_com_afiliado_maxima': ('com_afiliado', 'maxima'),
}


def _aplicar_filtro_preco_tiktok(produtos_qs, dados_extra, minimo, maximo):
    tipo, margem_valor = dados_extra
    condicoes = {'grade_precificacao_tiktok__tipo': tipo, 'grade_precificacao_tiktok__margem': margem_valor}
    if minimo:
        condicoes['grade_precificacao_tiktok__preco__gte'] = minimo
    if maximo:
        condicoes['grade_precificacao_tiktok__preco__lte'] = maximo
    return produtos_qs.filter(**condicoes)


@dataclass
class ItemGradeTiktokProduto:
    produto: object
    linhas_sem_afiliado: list
    linhas_com_afiliado: list

    @classmethod
    def montar(cls, produto, agrupador, labels):
        return cls(
            produto=produto,
            linhas_sem_afiliado=LinhaMargemExibida.montar_bloco(agrupador.linhas_de(produto.id, 'sem_afiliado'), labels),
            linhas_com_afiliado=LinhaMargemExibida.montar_bloco(agrupador.linhas_de(produto.id, 'com_afiliado'), labels),
        )


class AgrupadorLinhasGradeTiktok:

    def __init__(self, linhas):
        self._por_produto_tipo = {}
        for linha in linhas:
            self._por_produto_tipo.setdefault((linha.produto_id, linha.tipo), {})[linha.margem] = linha

    def linhas_de(self, produto_id, tipo):
        return self._por_produto_tipo.get((produto_id, tipo), {})


def view_grade_precificacao_tiktok(request):
    from precificacao.models import GradePrecificacaoTiktok

    filtros, pagina, querystring_sem_pagina = _filtrar_paginar_produtos_grade(
        request, 'grade_precificacao_tiktok', FAIXAS_PRECO_GRADE_TIKTOK, _aplicar_filtro_preco_tiktok
    )

    produtos_ids = [p.id for p in pagina.object_list]
    linhas = GradePrecificacaoTiktok.objects.filter(produto_id__in=produtos_ids)
    agrupador = AgrupadorLinhasGradeTiktok(linhas)

    labels_tiktok = [m.label_padrao for m in MARGENS]

    produtos_com_grade = [
        ItemGradeTiktokProduto.montar(produto, agrupador, labels_tiktok)
        for produto in pagina.object_list
    ]

    return render(request, 'precificacao/estrutura_grade_precificacao_tiktok.html', {
        'pagina': pagina,
        'busca': filtros.busca,
        'por_pagina': filtros.por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina,
        'produtos_com_grade': produtos_com_grade,
        'filtros_selecionados': {
            'marca': filtros.marcas, 'categoria': filtros.categorias, 'curva': filtros.curvas,
        },
        'get_params': request.GET,
        'filtros_preco_sem_afiliado': FiltroPrecoExibido.montar_bloco(request, 'tiktok_sem_afiliado'),
        'filtros_preco_com_afiliado': FiltroPrecoExibido.montar_bloco(request, 'tiktok_com_afiliado'),
        **_opcoes_filtro_produto(),
    })


@dataclass
class DetalheFormulaExibidaTiktok:
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
    # Explicação em detalhe: tipo_label (Sem/Com Afiliado) igual ao ML (Clássico/Premium).
    # passo_5 (taxa) é reconstruído na mão — a margem de afiliado só aparece como item
    # quando tipo=com_afiliado, o helper compartilhado tem só 3 itens fixos.
    @classmethod
    def montar(cls, linha, tipo_label, margem_label):
        det = linha.detalhamento or {}
        e = det.get('entrada', {})
        i = det.get('intermediarios', {})
        s = det.get('saida', {})

        def dec(valor):
            return Decimal(str(valor)) if valor is not None else None

        passo_1, passo_2, passo_3, passo_4, _, passo_6 = montar_passos_1_a_6(e, i, dec, label_comissao='Comissão TikTok')

        itens_taxa = [
            LinhaPercentualValor('Comissão TikTok', dec(e.get('comissao_percentual')), dec(i.get('comissao_valor'))),
            LinhaPercentualValor('ICMS saída', dec(e.get('icms_saida_percentual')), dec(i.get('icms_saida_valor'))),
            LinhaPercentualValor('PIS/COFINS (saída)', dec(e.get('pis_cofins_percentual')), dec(i.get('pis_cofins_valor'))),
        ]
        margem_afiliado_percentual = dec(e.get('margem_afiliado_percentual'))
        if margem_afiliado_percentual:
            itens_taxa.append(LinhaPercentualValor(
                'Margem de afiliado', margem_afiliado_percentual, dec(i.get('margem_afiliado_valor'))
            ))
        passo_5 = PassoTaxa(itens=itens_taxa, resultado=dec(i.get('taxa_percentual')))

        adicional_fixo = dec(i.get('adicional_fixo'))

        passo_7 = PassoFaixaFrete(
            peso=dec(e.get('peso')), faixa_min=dec(i.get('faixa_comissao_preco_min')),
            faixa_max=dec(i.get('faixa_comissao_preco_max')), resultado=dec(e.get('comissao_percentual')),
        )
        passo_8 = PassoPrecoExato(
            frete=dec(s.get('frete_usado')), fixo=dec(i.get('fixo')), rebate=Decimal('0'),
            denominador=dec(i.get('denominador')), resultado=dec(i.get('preco_exato_antes_arredondar')),
            taxa_unidade=adicional_fixo,
        )

        tabela_percentuais = montar_tabela_percentuais(e, i, dec, label_comissao='Comissão TikTok')
        if margem_afiliado_percentual:
            tabela_percentuais.append(LinhaPercentualValor(
                'Margem de afiliado', margem_afiliado_percentual, dec(i.get('margem_afiliado_valor'))
            ))

        desconto_vitrine = dec(e.get('desconto_vitrine_percentual'))
        saida = montar_saida(i, s, dec)
        saida.append(LinhaSaida(
            f'Preço "De" (vitrine, {desconto_vitrine:.0f}% de desconto)' if desconto_vitrine else 'Preço "De" (vitrine)',
            dec(s.get('preco_de_exibicao')), 'reais',
        ))

        return cls(
            tipo_label=tipo_label,
            margem_label=margem_label,
            tabela_percentuais=tabela_percentuais,
            pis_cofins=montar_pis_cofins(e, i, dec),
            valores_soltos=valores_soltos,
            dimensao=montar_dimensao(e, dec, origem_label='Embalagem ERP'),
            passo_1=passo_1, passo_2=passo_2, passo_3=passo_3, passo_4=passo_4,
            passo_5=passo_5, passo_6=passo_6, passo_7=passo_7, passo_8=passo_8,
            saida=saida,
        )


def view_grade_detalhe_tiktok(request, produto_id, tipo, margem):
    from precificacao.models import GradePrecificacaoTiktok

    linha = None
    if margem in MARGENS_POR_CHAVE and tipo in ('sem_afiliado', 'com_afiliado'):
        linha = GradePrecificacaoTiktok.objects.filter(
            produto_id=produto_id, tipo=tipo, margem=margem,
        ).select_related('produto').first()

    if not linha or not linha.detalhamento:
        return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_tiktok.html', {
            'sem_detalhamento': True,
        })

    tipo_label = 'Sem Afiliado' if tipo == 'sem_afiliado' else 'Com Afiliado'
    margem_label = MARGENS_POR_CHAVE[margem].label_base
    det = DetalheFormulaExibidaTiktok.montar(linha, tipo_label, margem_label)

    return render(request, 'precificacao/parciais/estrutura_parcial_grade_detalhe_tiktok.html', {
        'det': det,
        'produto_id': produto_id,
        'produto_titulo': linha.produto.titulo,
        'tipo': tipo,
        'margem': margem,
    })


def subquery_grade_tiktok_campo(tipo, campo, margem_geral):
    from django.db.models import Subquery, OuterRef, DecimalField
    from precificacao.models import GradePrecificacaoTiktok

    return Subquery(
        GradePrecificacaoTiktok.objects.filter(
            produto=OuterRef('pk'), tipo=tipo, margem=margem_geral,
        ).values(campo)[:1],
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )