# impostos/views/entrada.py

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from impostos.funcoes_auxiliares.entrada.espelho_nota_fiscal import montar_espelho_nota_fiscal
from impostos.funcoes_auxiliares.entrada.exibicao_impostos_entrada import montar_detalhes_para_exibicao
from impostos.funcoes_auxiliares.entrada.exportacao_resumo_entrada import gerar_excel_resumo_impostos_entrada
from impostos.funcoes_auxiliares.entrada.resumo_entrada import (
    ler_busca_resumo_entrada, listar_produtos_resumo_entrada_filtrados,
)

# * [EXPLICAÇÃO] → Título do espelho conforme QUEM pediu pra abrir — a grade de
#                  precificação manda `?papel=` pra o usuário saber se está
#                  vendo a nota que foi usada no cálculo ou a nota que o
#                  produto usa hoje (podem ser notas diferentes).
TITULO_DO_ESPELHO_POR_PAPEL = {
    'calculo': 'Nota usada neste cálculo',
    'atual': 'Nota mais recente deste produto hoje',
}


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


# Função Objetivo: Espelho de 1 nota fiscal de entrada (todos os itens, com impostos), carregado
# sob demanda dentro da janela "Ver NF" da grade de precificação. Parcial HTML (não uma página
# inteira) — quem abre a janela é o script_grade_detalhe.js, via HTMX. `?ean=` destaca o item do
# produto que está sendo auditado; `?papel=` só escolhe o título (ver TITULO_DO_ESPELHO_POR_PAPEL).
def view_espelho_nota_fiscal_entrada(request, chave):
    ean_destaque = request.GET.get('ean') or None
    espelho = montar_espelho_nota_fiscal(chave, ean_destaque=ean_destaque)

    return render(request, 'impostos/parciais/estrutura_parcial_espelho_nota_entrada.html', {
        'espelho': espelho,
        'ean_destaque': ean_destaque,
        'titulo_do_espelho': TITULO_DO_ESPELHO_POR_PAPEL.get(request.GET.get('papel'), 'Espelho da nota fiscal'),
    })
