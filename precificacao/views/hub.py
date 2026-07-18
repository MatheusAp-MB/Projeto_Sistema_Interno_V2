# precificacao/views/hub.py

from django.shortcuts import render


# Função Objetivo: Exibe a grid de seleção do módulo Precificação (2º nível de navegação).
def view_precificacao_hub(request):
    return render(request, 'precificacao/estrutura_precificacao_hub.html')