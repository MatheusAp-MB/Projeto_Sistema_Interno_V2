from django.shortcuts import render


def view_configuracoes_raia(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect
    from raia.models import ConfiguracaoRaia

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    config = ConfiguracaoRaia.obter()

    if request.method == 'POST':
        config.comissao_percentual = _dec(request.POST.get('comissao_percentual'), config.comissao_percentual)
        config.frete_fixo = _dec(request.POST.get('frete_fixo'), config.frete_fixo)
        config.save()
        return redirect(f"{reverse('raia_configuracoes')}?salvo=1")

    return render(request, 'raia/estrutura_configuracoes_raia.html', {
        'config': config,
        'salvo': request.GET.get('salvo') == '1',
    })