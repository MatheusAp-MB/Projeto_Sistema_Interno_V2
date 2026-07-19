from django.shortcuts import render


def view_configuracoes_amazon(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect
    from amazon.models import ConfiguracaoAmazon

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    config = ConfiguracaoAmazon.obter()

    if request.method == 'POST':
        config.comissao_percentual = _dec(request.POST.get('comissao_percentual'), config.comissao_percentual)
        config.save()
        return redirect(f"{reverse('amazon_configuracoes')}?salvo=1")

    return render(request, 'amazon/estrutura_configuracoes_amazon.html', {
        'config': config,
        'salvo': request.GET.get('salvo') == '1',
    })


def view_tabela_frete_amazon(request):
    from precificacao.models import FreteAmazon, TaxaKgAdicionalAmazon

    fretes_dba = FreteAmazon.objects.filter(tipo='dba').order_by('preco_min', 'peso_min')
    fretes_fba = FreteAmazon.objects.filter(tipo='fba').order_by('preco_min', 'peso_min')
    kg_dba = TaxaKgAdicionalAmazon.objects.filter(tipo='dba').order_by('preco_min')
    kg_fba = TaxaKgAdicionalAmazon.objects.filter(tipo='fba').order_by('preco_min')

    return render(request, 'amazon/estrutura_tabela_frete_amazon.html', {
        'fretes_dba': fretes_dba, 'fretes_fba': fretes_fba,
        'kg_dba': kg_dba, 'kg_fba': kg_fba,
    })


def view_calcular_frete_amazon(request):
    from decimal import Decimal, InvalidOperation
    import math
    from django.db.models import Q
    from precificacao.models import FreteAmazon, TaxaKgAdicionalAmazon

    try:
        tipo = request.POST.get('tipo', 'dba')
        peso = Decimal(request.POST.get('peso', '0'))
        preco = Decimal(request.POST.get('preco', '0'))

        fretes = FreteAmazon.objects.filter(tipo=tipo)
        candidata = fretes.filter(preco_min__lte=preco).filter(
            Q(preco_max__gte=preco) | Q(preco_max__isnull=True)
        ).order_by('preco_min').last()

        if not candidata:
            return render(request, 'amazon/parciais/estrutura_parcial_resultado_frete_amazon.html', {'valor': None})

        linhas_da_faixa = fretes.filter(preco_min=candidata.preco_min, preco_max=candidata.preco_max)
        linha_flat = linhas_da_faixa.filter(peso_min__isnull=True).first()

        if linha_flat:
            valor = linha_flat.valor
        else:
            linha_peso = linhas_da_faixa.filter(peso_min__lte=peso, peso_max__gte=peso).first()
            if linha_peso:
                valor = linha_peso.valor
            else:
                linha_maxima = linhas_da_faixa.order_by('-peso_max').first()
                taxa_kg = TaxaKgAdicionalAmazon.objects.filter(
                    tipo=tipo, preco_min=candidata.preco_min, preco_max=candidata.preco_max,
                ).first()
                if not linha_maxima or not taxa_kg:
                    return render(request, 'amazon/parciais/estrutura_parcial_resultado_frete_amazon.html', {'valor': None})
                kg_extra = math.ceil(peso - linha_maxima.peso_max)
                valor = linha_maxima.valor + Decimal(kg_extra) * taxa_kg.valor_por_kg

        return render(request, 'amazon/parciais/estrutura_parcial_resultado_frete_amazon.html', {'valor': valor})

    except (InvalidOperation, ValueError) as e:
        return render(request, 'amazon/parciais/estrutura_parcial_resultado_frete_amazon.html', {
            'valor': None, 'erro': str(e),
        })