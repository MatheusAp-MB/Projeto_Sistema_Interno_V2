from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render

from impostos.funcoes_auxiliares.exibicao_impostos_entrada import montar_detalhes_para_exibicao
from impostos.funcoes_auxiliares.exportacao_resumo_entrada import gerar_excel_resumo_impostos_entrada
from impostos.funcoes_auxiliares.resumo_entrada import (
    ler_busca_resumo_entrada, listar_produtos_resumo_entrada_filtrados,
)


def view_resumo_impostos_entrada(request):
    por_pagina = request.GET.get('por_pagina', '25')
    try:
        por_pagina = int(por_pagina)
    except ValueError:
        por_pagina = 25

    busca = ler_busca_resumo_entrada(request)
    produtos = listar_produtos_resumo_entrada_filtrados(busca=busca or None)

    paginator = Paginator(produtos, por_pagina)
    numero_pagina = request.GET.get('pagina', 1)
    pagina = paginator.get_page(numero_pagina)

    linhas = []
    for produto in pagina.object_list:
        detalhes = montar_detalhes_para_exibicao(produto.impostos_entrada)
        por_imposto = {linha.nome: linha for linha in detalhes.linhas}
        linhas.append({
            'imagem_url': produto.imagem_url,
            'produto': produto.titulo,
            'sku': produto.sku,
            'ean': produto.ean,
            'ncm': detalhes.ncm_xml,
            'nota_fiscal': detalhes.nr_nf,
            'fornecedor': detalhes.fornecedor,
            'empresa': detalhes.empresa_fantasia,
            'data_entrada': detalhes.data_entrada_nota,
            'custo_unitario': detalhes.custo_unitario,
            'icms_aliquota': por_imposto['ICMS'].aliquota,
            'icms_reducao': por_imposto['ICMS'].reducao,
            'icms_st_aliquota': por_imposto['ICMS ST'].aliquota,
            'icms_st_reducao': por_imposto['ICMS ST'].reducao,
            'icms_ret_aliquota': por_imposto['ICMS Retido'].aliquota,
            'icms_ret_reducao': por_imposto['ICMS Retido'].reducao,
            'ipi_aliquota': por_imposto['IPI'].aliquota,
            'ipi_reducao': por_imposto['IPI'].reducao,
            'pis_aliquota': por_imposto['PIS'].aliquota,
            'pis_reducao': por_imposto['PIS'].reducao,
            'cofins_aliquota': por_imposto['COFINS'].aliquota,
            'cofins_reducao': por_imposto['COFINS'].reducao,
        })

    querystring_sem_pagina = request.GET.copy()
    querystring_sem_pagina.pop('pagina', None)

    return render(request, 'impostos/estrutura_resumo_entrada.html', {
        'pagina': pagina,
        'linhas': linhas,
        'busca': busca,
        'por_pagina': por_pagina,
        'querystring_sem_pagina': querystring_sem_pagina.urlencode(),
    })


def view_exportar_resumo_impostos_entrada(request):
    busca = ler_busca_resumo_entrada(request)
    produtos = listar_produtos_resumo_entrada_filtrados(busca=busca or None)

    arquivo_bytes = gerar_excel_resumo_impostos_entrada(produtos)

    response = HttpResponse(
        arquivo_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="Relatorio_Impostos_Entrada.xlsx"'
    return response
