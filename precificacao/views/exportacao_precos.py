# precificacao/views/exportacao_precos.py

from dataclasses import dataclass
from django.shortcuts import render
from precificacao.funcoes_auxiliares.exportacao.config_marketplaces_exportaveis import (
    MARKETPLACES_EXPORTAVEIS, MARKETPLACES_EXPORTAVEIS_POR_CHAVE,
)
from precificacao.views.comum import MARGENS


# Função Objetivo: Representa 1 linha da exportação — só os 4 campos que o ERP espera.
@dataclass
class LinhaExportacaoPrecos:
    ean: str
    titulo: str
    custo: object
    preco: object


def view_exportar_precificacao(request):
    from produtos.models import Produto

    marcas_disponiveis = Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca')

    if request.method != 'POST':
        return render(request, 'precificacao/estrutura_exportar_precificacao.html', {
            'marketplaces': MARKETPLACES_EXPORTAVEIS, 'marcas_disponiveis': marcas_disponiveis,
        })

    from precificacao.funcoes_auxiliares.exportacao.gerador_excel_exportacao_precos import gerar_excel_exportacao_precos

    from precificacao.views.comum import MARGENS_CHAVES

    marketplace_chave = request.POST.get('marketplace')
    tipo = request.POST.get('tipo')
    margem = request.POST.get('margem', 'padrao')
    marcas = request.POST.getlist('marca')

    erros = []
    marketplace = MARKETPLACES_EXPORTAVEIS_POR_CHAVE.get(marketplace_chave)

    # * [EXPLICAÇÃO] → NUNCA confia no que veio do POST sem checar — o
    #                  navegador manda qualquer campo marcado, mesmo se
    #                  o JS deveria ter escondido/limpado. Validação real
    #                  acontece aqui, não só na tela.
    if not marketplace:
        erros.append('Selecione um marketplace válido.')
    else:
        chaves_tipo_validas = {t.chave for t in marketplace.tipos}
        if marketplace.tipos and tipo not in chaves_tipo_validas:
            erros.append(f'Selecione o tipo de {marketplace.label} (obrigatório para esse marketplace).')
        elif not marketplace.tipos:
            # * [EXPLICAÇÃO] → Marketplace sem tipo NUNCA deve carregar um
            #                  "tipo" pro resto do processamento, mesmo que
            #                  algo estranho tenha vindo no POST.
            tipo = None

    if margem not in MARGENS_CHAVES:
        erros.append('Margem inválida.')

    marcas_reais = set(Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True))
    marcas_invalidas = set(marcas) - marcas_reais
    if marcas_invalidas:
        erros.append(f'Marca(s) inválida(s): {", ".join(sorted(marcas_invalidas))}.')
    if not marcas:
        erros.append('Selecione ao menos uma marca.')

    if erros:
        return render(request, 'precificacao/estrutura_exportar_precificacao.html', {
            'marketplaces': MARKETPLACES_EXPORTAVEIS, 'marcas_disponiveis': marcas_disponiveis,
            'erros': erros, 'marcas_selecionadas': marcas,
        })

    condicoes = {'produto__marca__in': marcas, 'margem': margem, **marketplace.filtro_extra}
    if marketplace.campo_tipo:
        condicoes[marketplace.campo_tipo] = tipo

    linhas_grade = marketplace.model.objects.filter(**condicoes, preco__isnull=False).select_related('produto')

    linhas_exportacao = [
        LinhaExportacaoPrecos(ean=g.produto.ean, titulo=g.produto.titulo, custo=g.produto.custo, preco=g.preco)
        for g in linhas_grade
    ]

    if not linhas_exportacao:
        return render(request, 'precificacao/estrutura_exportar_precificacao.html', {
            'marketplaces': MARKETPLACES_EXPORTAVEIS, 'marcas_disponiveis': marcas_disponiveis,
            'erros': ['Nenhum produto encontrado para essa combinação de marketplace/tipo/margem/marcas — confira se a Grade foi calculada.'],
            'marcas_selecionadas': marcas,
        })

    from django.http import HttpResponse
    from datetime import date

    arquivo_bytes = gerar_excel_exportacao_precos(linhas_exportacao)
    data_hoje = date.today().strftime('%d_%m_%y')
    nome_tipo = f'_{tipo}' if tipo else ''
    nome_arquivo = f'Precificacao_{marketplace.label.replace(" ", "_")}{nome_tipo}_{data_hoje}.xlsx'

    response = HttpResponse(
        arquivo_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return response