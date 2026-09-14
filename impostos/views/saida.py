# impostos/views/saida.py

from django.shortcuts import render
from impostos.funcoes_auxiliares.saida.exibicao_auditoria_fiscal import montar_contexto_auditoria_fiscal
from impostos.funcoes_auxiliares.saida.exibicao_icms_por_ncm import (
    consultar_icms_por_ncm, listar_csts_disponiveis_para_ncm_origem,
    listar_origens_disponiveis_para_ncm, montar_matriz_icms_por_ncm,
)
from impostos.funcoes_auxiliares.saida.exibicao_pis_cofins_por_ncm_cst import (
    consultar_pis_cofins_por_ncm_cst, listar_csts_disponiveis_para_ncm, montar_tabela_pis_cofins_por_ncm_cst,
)
from impostos.funcoes_auxiliares.saida.importacao_icms_ncm import UFS_ORDENADAS

# 14/09/2026 — sentinela pro <select> de Origem da Mercadoria: "" já é o
# placeholder "Selecione...", então Origem em branco (produto sem
# impostos_entrada sincronizado) precisa de um valor próprio pra não ficar
# indistinguível — mesma técnica validada no Mockup 2 aprovado no vault.
# Usado nos 2 lados (o <option> do select e o data-origem da matriz) pra
# casar sem depender de como o Django renderiza None.
SENTINELA_ORIGEM_EM_BRANCO = '__NULL__'


def view_auditoria_fiscal(request):
    contexto = montar_contexto_auditoria_fiscal()
    return render(request, 'impostos/estrutura_auditoria_fiscal.html', contexto)


def view_tabela_icms_por_ncm(request):
    linhas = montar_matriz_icms_por_ncm()

    return render(request, 'impostos/estrutura_tabela_icms_por_ncm.html', {
        'ufs': UFS_ORDENADAS,
        'linhas': linhas,
        # 14/09/2026 — sorted(set(...)) em vez de lista direta: 1 NCM pode
        # aparecer em mais de 1 linha (grupos diferentes de CST/Origem), e
        # duplicava no <select> — mesmo padrão que
        # montar_tabela_pis_cofins_por_ncm_cst() já usa.
        'ncms_disponiveis': sorted({linha['ncm'] for linha in linhas}),
        'sentinela_origem_em_branco': SENTINELA_ORIGEM_EM_BRANCO,
    })


# Função Objetivo: Popula o <select> de Origem da Mercadoria, dependente
# do NCM — 1º nível da calculadora (Etapa 6c). Chamada pelo HTMX quando o
# campo NCM muda.
def view_origens_disponiveis_icms_ncm(request):
    ncm = request.GET.get('ncm', '').strip()
    origens = listar_origens_disponiveis_para_ncm(ncm) if ncm else []

    return render(request, 'impostos/parciais/estrutura_parcial_select_origem_icms_por_ncm.html', {
        'origens': origens,
        'ncm': ncm,
        'sentinela_origem_em_branco': SENTINELA_ORIGEM_EM_BRANCO,
    })


# Função Objetivo: Popula o <select> de CST, dependente do NCM + Origem —
# 2º nível da calculadora (Etapa 6c). Chamada pelo HTMX quando o campo
# Origem muda. origem_bruta chega como veio do <select> (pode ser o
# sentinela __NULL__) — convertida pra None antes de consultar o banco,
# nunca comparada como string com o valor real da Origem.
def view_csts_disponiveis_icms_ncm_origem(request):
    ncm = request.GET.get('ncm', '').strip()
    origem_bruta = request.GET.get('origem', '').strip()
    origem = None if origem_bruta == SENTINELA_ORIGEM_EM_BRANCO else (origem_bruta or None)
    csts = listar_csts_disponiveis_para_ncm_origem(ncm, origem) if ncm and origem_bruta else []

    return render(request, 'impostos/parciais/estrutura_parcial_select_cst_icms_por_ncm.html', {
        'csts': csts,
        'ncm': ncm,
        'origem_bruta': origem_bruta,
    })


def view_calcular_icms_por_ncm(request):
    ncm = request.POST.get('ncm', '').strip()
    origem_bruta = request.POST.get('origem', '').strip()
    cst = request.POST.get('cst', '').strip()
    uf = request.POST.get('uf', '').strip()
    origem = None if origem_bruta == SENTINELA_ORIGEM_EM_BRANCO else (origem_bruta or None)

    try:
        if not ncm or not origem_bruta or not cst or not uf:
            return render(request, 'impostos/parciais/estrutura_parcial_resultado_icms_por_ncm.html', {
                'ncm': ncm,
                'origem_bruta': origem_bruta,
                'cst': cst,
                'uf': uf,
                'ncm_encontrado': False,
                'campos_em_branco': True,
            })

        aliquota, ncm_encontrado, e_media_ponderada = consultar_icms_por_ncm(ncm, origem, cst, uf)

        return render(request, 'impostos/parciais/estrutura_parcial_resultado_icms_por_ncm.html', {
            'aliquota': aliquota,
            'ncm': ncm,
            'origem_bruta': origem_bruta,
            'cst': cst,
            'uf': uf,
            'ncm_encontrado': ncm_encontrado,
            'e_media_ponderada': e_media_ponderada,
        })

    except Exception as e:
        return render(request, 'impostos/parciais/estrutura_parcial_resultado_icms_por_ncm.html', {
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