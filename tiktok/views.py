from django.shortcuts import render


def view_configuracoes_tiktok(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect
    from tiktok.models import ConfiguracaoTiktok
    from precificacao.models import TabelaComissaoTiktok

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    config = ConfiguracaoTiktok.obter()

    if request.method == 'POST':
        config.margem_afiliado_percentual = _dec(
            request.POST.get('margem_afiliado_percentual'), config.margem_afiliado_percentual
        )
        config.save()
        return redirect(f"{reverse('tiktok_configuracoes')}?salvo=1")

    return render(request, 'tiktok/estrutura_configuracoes_tiktok.html', {
        'config': config,
        'faixas_comissao': TabelaComissaoTiktok.objects.all().order_by('preco_min'),
        'salvo': request.GET.get('salvo') == '1',
    })


def view_tabela_frete_tiktok(request):
    from tiktok.models import FreteTiktok

    faixas = FreteTiktok.objects.all().order_by('peso_min')
    return render(request, 'tiktok/estrutura_tabela_frete_tiktok.html', {'faixas': faixas})


def view_calcular_frete_tiktok(request):
    from decimal import Decimal, InvalidOperation
    from django.db.models import Q
    from tiktok.models import FreteTiktok

    try:
        peso = Decimal(request.POST.get('peso', '0'))

        faixa = FreteTiktok.objects.filter(
            peso_min__lte=peso,
        ).filter(
            Q(peso_max__gte=peso) | Q(peso_max__isnull=True)
        ).order_by('peso_min').last()

        if faixa:
            return render(request, 'tiktok/parciais/estrutura_parcial_resultado_frete_tiktok.html', {
                'valor': faixa.valor, 'peso_min': faixa.peso_min,
            })

        return render(request, 'tiktok/parciais/estrutura_parcial_resultado_frete_tiktok.html', {
            'valor': None,
        })

    except (InvalidOperation, ValueError) as e:
        return render(request, 'tiktok/parciais/estrutura_parcial_resultado_frete_tiktok.html', {
            'valor': None, 'erro': str(e),
        })