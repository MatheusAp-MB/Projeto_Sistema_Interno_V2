# gestao_ruptura/views_ruptura.py
#
# View da tela "Ruptura de estoque" (Mercado Livre → Estoque → Ruptura de estoque), PROVA DE CONCEITO de 12/10/2026: projeta quantos dias o estoque dura no ritmo
# de vendas escolhido, em que dia ele acaba, até quando preparar o envio e o nível do estoque.
#
# REGRA DO MATHEUS: esta tela NUNCA chama a API do ML (nem a do ERP). Ela só LÊ o banco (as vendas que a tela de Vendas já coletou). O estoque e o lead time são
# digitados na própria tela, não são guardados e valem só para aquela consulta (ficam no endereço da página).

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from gestao_ruptura.funcoes_auxiliares.ruptura_pagina import montar_pagina


# Função Objetivo: A tela, em dois modos. SEM "sku" na URL: a LISTA por urgência, com o seletor "Ver por" (gran = produto | mlb | codigo), busca (q), filtro de nível
# (nivel), ordenação (ord), itens por página (por) e página (pag). COM "sku": o DETALHE com a curva (do próprio SKU, ou de um MLB / Código ML dele: gran = mlb | codigo + item;
# mais visao, dias, estoque). O lead time é um só (lead; vazio = padrão provisório de 7 dias). Todos os parâmetros são validados dentro de montar_pagina.
@require_GET
def view_ruptura(request):
    base = reverse('gestao_ruptura_principal')
    return render(request, 'gestao_ruptura/estrutura_ruptura.html', {'pagina': montar_pagina(request.GET, base), 'url_ruptura': base})
