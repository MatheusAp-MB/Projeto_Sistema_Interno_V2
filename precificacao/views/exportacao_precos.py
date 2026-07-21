# precificacao/views/exportacao_precos.py

from dataclasses import dataclass
from django.shortcuts import render
from precificacao.views.comum import MARGENS, MARGENS_CHAVES
from precificacao.views.resumo_marketplaces import MARKETPLACES_RESUMO


# Função Objetivo: Representa 1 linha da exportação — só os 4 campos que o ERP espera.
@dataclass
class LinhaExportacaoPrecos:
    ean: str
    titulo: str
    custo: object
    preco: object


def view_exportar_precificacao(request):
    from produtos.models import Produto

    canais_exportaveis = [m for m in MARKETPLACES_RESUMO if m.eh_real]
    marcas_disponiveis = Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True).distinct().order_by('marca')

    if request.method != 'POST':
        return render(request, 'precificacao/estrutura_exportar_precificacao.html', {
            'canais': canais_exportaveis, 'marcas_disponiveis': marcas_disponiveis,
        })

    from precificacao.funcoes_auxiliares.exportacao.gerador_excel_exportacao_precos import gerar_excel_exportacao_precos

    canal_chave = request.POST.get('canal')
    margem = request.POST.get('margem', 'padrao')
    marcas = request.POST.getlist('marca')

    erros = []
    canal = next((c for c in canais_exportaveis if c.chave == canal_chave), None)

    # * [EXPLICAÇÃO] → NUNCA confia no que veio do POST sem checar contra
    #                  as opções reais — mesma disciplina do bug que
    #                  corrigimos antes ("Shopee_premium").
    if not canal:
        erros.append('Selecione um canal de venda válido.')
    if margem not in MARGENS_CHAVES:
        erros.append('Margem inválida.')

    marcas_reais = set(Produto.objects.exclude(marca__isnull=True).exclude(marca='').values_list('marca', flat=True))
    marcas_invalidas = set(marcas) - marcas_reais
    if marcas_invalidas:
        erros.append(f'Marca(s) inválida(s): {", ".join(sorted(marcas_invalidas))}.')
    if not marcas:
        erros.append('Selecione ao menos uma marca.')

    if erros:
        return render(request, 'precificacao/parciais/estrutura_parcial_modal_erro_exportacao.html', {'erros': erros})

    condicoes = {'produto__marca__in': marcas, 'margem': margem, **canal.filtro_extra}
    linhas_grade = canal.model.objects.filter(**condicoes, preco__isnull=False).select_related('produto')

    linhas_exportacao = [
        LinhaExportacaoPrecos(ean=g.produto.ean, titulo=g.produto.titulo, custo=g.produto.custo, preco=g.preco)
        for g in linhas_grade
    ]

    if not linhas_exportacao:
        return render(request, 'precificacao/parciais/estrutura_parcial_modal_erro_exportacao.html', {
            'erros': ['Nenhum produto encontrado para essa combinação de canal/margem/marcas — confira se a Grade foi calculada.'],
        })

    import uuid
    from django.core.cache import cache
    from django.http import HttpResponse
    from django.urls import reverse

    arquivo_bytes = gerar_excel_exportacao_precos(linhas_exportacao)
    token = str(uuid.uuid4())
    cache.set(f'exportacao_precos_{token}', {'arquivo': arquivo_bytes, 'canal_chave': canal.chave}, timeout=300)

    resposta = HttpResponse(status=200)
    resposta['HX-Redirect'] = reverse('precificacao_baixar_exportacao', args=[token])
    return resposta


# Função Objetivo: Serve o arquivo gerado — SEMPRE via GET, pra nunca disparar o
# aviso de "reenviar formulário" do navegador ao apertar F5.
def view_baixar_exportacao(request, token):
    from datetime import date
    from django.core.cache import cache
    from django.http import HttpResponse

    dados = cache.get(f'exportacao_precos_{token}')
    if dados is None:
        return HttpResponse('Arquivo expirado — gere a exportação de novo.', status=404)

    data_hoje = date.today().strftime('%d_%m_%y')
    nome_arquivo = f'Precificacao_{dados["canal_chave"]}_{data_hoje}.xlsx'

    response = HttpResponse(
        dados['arquivo'],
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return response