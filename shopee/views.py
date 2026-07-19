from django.shortcuts import render


def view_configuracoes_shopee(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect
    from shopee.models import ConfiguracaoShopee
    from precificacao.models import TabelaComissaoShopee

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    config = ConfiguracaoShopee.obter()

    if request.method == 'POST':
        config.frete_padrao = _dec(request.POST.get('frete_padrao'), config.frete_padrao)
        config.desconto_vitrine_percentual = _dec(
            request.POST.get('desconto_vitrine_percentual'), config.desconto_vitrine_percentual
        )
        config.save()
        return redirect(f"{reverse('shopee_configuracoes')}?salvo=1")

    return render(request, 'shopee/estrutura_configuracoes_shopee.html', {
        'config': config,
        'faixas_comissao': TabelaComissaoShopee.objects.all().order_by('preco_min'),
        'salvo': request.GET.get('salvo') == '1',
    })