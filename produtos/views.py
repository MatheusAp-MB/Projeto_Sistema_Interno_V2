from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import render, get_object_or_404
from .models import Produto
from produtos.funcoes_auxiliares.contexto_tela_produtos import ContextoTelaProdutos
from impostos.funcoes_auxiliares.exibicao_impostos_entrada import montar_detalhes_para_exibicao


def view_produtos(request):
    contexto = ContextoTelaProdutos(request).montar()
    return render(request, 'produtos/estrutura_produtos.html', contexto)


def view_painel_produto(request, produto_id):
    produto = get_object_or_404(Produto, pk=produto_id)

    # * [EXPLICAÇÃO] → Nem todo produto já tem impostos de entrada
    #                  sincronizados (Sysemp) — trata a ausência como caso
    #                  normal, não como erro.
    try:
        impostos_entrada = montar_detalhes_para_exibicao(produto.impostos_entrada)
    except ObjectDoesNotExist:
        impostos_entrada = None

    return render(request, 'produtos/parciais/estrutura_parcial_painel_produto.html', {
        'produto': produto,
        'impostos_entrada': impostos_entrada,
    })