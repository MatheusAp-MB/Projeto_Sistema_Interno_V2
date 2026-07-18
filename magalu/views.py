from django.shortcuts import render


def view_tabela_frete_magalu(request):
    from magalu.models import FreteMagalu, ConfiguracaoMagalu

    faixas = FreteMagalu.objects.all().order_by('peso_min')
    config = ConfiguracaoMagalu.obter()

    return render(request, 'magalu/estrutura_tabela_frete_magalu.html', {
        'faixas': faixas,
        'faixa_reputacao_atual': config.faixa_reputacao_atual,
    })


def view_calcular_frete_magalu(request):
    from decimal import Decimal, InvalidOperation
    from django.db.models import Q
    from magalu.models import FreteMagalu, ConfiguracaoMagalu

    try:
        peso = Decimal(request.POST.get('peso', '0'))
        reputacao = request.POST.get('reputacao') or ConfiguracaoMagalu.obter().faixa_reputacao_atual

        faixa = FreteMagalu.objects.filter(
            peso_min__lte=peso,
        ).filter(
            Q(peso_max__gte=peso) | Q(peso_max__isnull=True)
        ).order_by('peso_min').last()

        if faixa:
            valor = faixa.valor_para_reputacao(reputacao)
            return render(request, 'magalu/parciais/estrutura_parcial_resultado_frete_magalu.html', {
                'valor': valor,
                'peso_min': faixa.peso_min,
                'reputacao': reputacao,
            })

        return render(request, 'magalu/parciais/estrutura_parcial_resultado_frete_magalu.html', {
            'valor': None,
        })

    except (InvalidOperation, ValueError) as e:
        return render(request, 'magalu/parciais/estrutura_parcial_resultado_frete_magalu.html', {
            'valor': None,
            'erro': str(e),
        })