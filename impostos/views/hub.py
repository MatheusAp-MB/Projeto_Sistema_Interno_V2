# impostos/views/hub.py

from django.shortcuts import render


# Função Objetivo: Exibe a página inicial do módulo Impostos (2º nível de navegação): 1 card por tela.
def view_impostos_hub(request):
    return render(request, 'impostos/estrutura_impostos_hub.html')
