# precificacao/views/configuracoes.py

def view_configuracoes_operacionais(request):
    from decimal import Decimal, InvalidOperation
    from django.urls import reverse
    from django.shortcuts import redirect, render
    from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem

    def _dec(valor, atual):
        try:
            return Decimal(str(valor).replace(',', '.'))
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            return atual

    if request.method == 'POST':
        acao = request.POST.get('acao')

        if acao == 'salvar_geral':
            config_geral = ConfiguracaoOperacional.obter()
            config_geral.fator_coleta = _dec(request.POST.get('fator_coleta'), config_geral.fator_coleta)
            try:
                config_geral.periodo_armazenagem = int(request.POST.get('periodo_armazenagem'))
            except (TypeError, ValueError):
                pass
            config_geral.save()

        elif acao == 'salvar_faixas':
            for faixa in FaixaArmazenagem.objects.filter(ativo=True):
                valor = request.POST.get(f'faixa_{faixa.id}_valor_diario')
                if valor is not None:
                    faixa.valor_diario = _dec(valor, faixa.valor_diario)
                    faixa.save()

        return redirect(f"{reverse('precificacao_configuracoes_operacionais')}?salvo=1")

    config_geral = ConfiguracaoOperacional.obter()
    faixas = FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem')

    return render(request, 'precificacao/estrutura_configuracoes_operacionais.html', {
        'config_geral': config_geral,
        'faixas': faixas,
        'salvo': request.GET.get('salvo') == '1',
    })