# impostos/views/saida.py

from django.shortcuts import render
from impostos.funcoes_auxiliares.saida.exibicao_auditoria_fiscal import montar_contexto_auditoria_fiscal
from impostos.funcoes_auxiliares.saida.exibicao_icms_por_ncm import (
    consultar_icms_por_ncm, montar_matriz_icms_por_ncm,
)
from impostos.funcoes_auxiliares.saida.exibicao_pis_cofins_por_ncm_cst import (
    consultar_pis_cofins_por_ncm_cst, listar_csts_disponiveis_para_ncm, montar_tabela_pis_cofins_por_ncm_cst,
)
from impostos.funcoes_auxiliares.saida.importacao_icms_ncm import UFS_ORDENADAS


def view_auditoria_fiscal(request):
    contexto = montar_contexto_auditoria_fiscal()
    return render(request, 'impostos/estrutura_auditoria_fiscal.html', contexto)


def view_tabela_icms_por_ncm(request):
    linhas = montar_matriz_icms_por_ncm()

    return render(request, 'impostos/estrutura_tabela_icms_por_ncm.html', {
        'ufs': UFS_ORDENADAS,
        'linhas': linhas,
        'ncms_disponiveis': [linha['ncm'] for linha in linhas],
    })


def view_calcular_icms_por_ncm(request):
    ncm = request.POST.get('ncm', '').strip()
    uf = request.POST.get('uf', '').strip()

    try:
        aliquota, ncm_encontrado, e_media_ponderada = consultar_icms_por_ncm(ncm, uf)

        return render(request, 'impostos/parciais/estrutura_parcial_resultado_icms_por_ncm.html', {
            'aliquota': aliquota,
            'ncm': ncm,
            'uf': uf,
            'ncm_encontrado': ncm_encontrado,
            'e_media_ponderada': e_media_ponderada,
        })

    except Exception as e:
        return render(request, 'impostos/parciais/estrutura_parcial_resultado_icms_por_ncm.html', {
            'aliquota': None,
            'ncm_encontrado': False,
            'erro': str(e),
        })


def view_tabela_pis_cofins_por_ncm_cst(request):
    linhas = montar_tabela_pis_cofins_por_ncm_cst()

    return render(request, 'impostos/estrutura_tabela_pis_cofins_por_ncm_cst.html', {
        'linhas': linhas,
        'ncms_disponiveis': sorted({linha['ncm'] for linha in linhas}),
    })


def view_csts_disponiveis_pis_cofins_ncm_cst(request):
    ncm = request.GET.get('ncm', '').strip()
    csts = listar_csts_disponiveis_para_ncm(ncm) if ncm else []

    return render(request, 'impostos/parciais/estrutura_parcial_select_cst_pis_cofins_por_ncm_cst.html', {
        'csts': csts,
        'ncm': ncm,
    })


def view_calcular_pis_cofins_por_ncm_cst(request):
    ncm = request.POST.get('ncm', '').strip()
    cst = request.POST.get('cst', '').strip()

    try:
        if not ncm or not cst:
            return render(request, 'impostos/parciais/estrutura_parcial_resultado_pis_cofins_por_ncm_cst.html', {
                'ncm': ncm,
                'cst': cst,
                'encontrado': False,
                'ncm_ou_cst_em_branco': True,
            })

        pis, cofins, encontrado = consultar_pis_cofins_por_ncm_cst(ncm, cst)

        return render(request, 'impostos/parciais/estrutura_parcial_resultado_pis_cofins_por_ncm_cst.html', {
            'ncm': ncm,
            'cst': cst,
            'pis': pis,
            'cofins': cofins,
            'encontrado': encontrado,
        })

    except Exception as e:
        return render(request, 'impostos/parciais/estrutura_parcial_resultado_pis_cofins_por_ncm_cst.html', {
            'ncm': ncm,
            'cst': cst,
            'encontrado': False,
            'erro': str(e),
        })