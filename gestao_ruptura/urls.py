# gestao_ruptura/urls.py

from django.urls import path
from . import views_ruptura

urlpatterns = [
    # * [EXPLICAÇÃO] → Tela "Ruptura de estoque" (12/10/2026, prova de conceito): o ritmo de vendas de um produto (SKU) contra o estoque que a pessoa digita.
    #                  Só lê o banco (vendas já coletadas); não chama a API do Mercado Livre nem a do ERP. Parâmetros: ?sku=&visao=&dias=&estoque=&lead=.
    path('', views_ruptura.view_ruptura, name='gestao_ruptura_principal'),
]
