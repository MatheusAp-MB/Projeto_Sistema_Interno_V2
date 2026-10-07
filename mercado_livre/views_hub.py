# mercado_livre/views_hub.py

from django.shortcuts import render


# Função Objetivo: Exibe a página inicial do Mercado Livre (2º nível de navegação): as telas do canal, agrupadas por área.
def view_mercado_livre_hub(request):
    return render(request, 'mercado_livre/estrutura_mercado_livre_hub.html')
