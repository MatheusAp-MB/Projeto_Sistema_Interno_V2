from django.shortcuts import render, get_object_or_404
from .models import Produto


def view_produtos(request):
    produtos = Produto.objects.all()
    return render(request, 'produtos/estrutura_produtos.html', {'produtos': produtos})


def view_painel_produto(request, produto_id):
    produto = get_object_or_404(Produto, pk=produto_id)
    return render(request, 'produtos/parciais/estrutura_parcial_painel_produto.html', {
        'produto': produto,
    })