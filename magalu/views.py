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
    

def view_configuracoes_magalu(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect
    from magalu.models import ConfiguracaoMagalu

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    config = ConfiguracaoMagalu.obter()

    if request.method == 'POST':
        config.comissao_percentual = _dec(request.POST.get('comissao_percentual'), config.comissao_percentual)
        config.taxa_unidade_fixa = _dec(request.POST.get('taxa_unidade_fixa'), config.taxa_unidade_fixa)

        faixa = request.POST.get('faixa_reputacao_atual')
        if faixa in ConfiguracaoMagalu.FaixaReputacao.values:
            config.faixa_reputacao_atual = faixa

        config.save()
        return redirect(f"{reverse('magalu_configuracoes')}?salvo=1")

    return render(request, 'magalu/estrutura_configuracoes_magalu.html', {
        'config': config,
        'faixas_reputacao': ConfiguracaoMagalu.FaixaReputacao.choices,
        'salvo': request.GET.get('salvo') == '1',
    })