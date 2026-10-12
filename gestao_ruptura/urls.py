# gestao_ruptura/urls.py

from django.urls import path
from . import views_ruptura

urlpatterns = [
    # * [EXPLICAÇÃO] → Tela "Previsão de Ruptura de estoque" (12/10/2026, prova de conceito): o ritmo de vendas de um produto (SKU) contra o estoque que a pessoa digita.
    #                  Só lê o banco (vendas já coletadas e a última consulta salva de cada Código ML); não chama sozinha a API do Mercado Livre nem a do ERP. Parâmetros: ?sku=&visao=&dias=&estoque=&lead=.
    path('', views_ruptura.view_ruptura, name='gestao_ruptura_principal'),
    # * [EXPLICAÇÃO] → O botão "Consultar no Mercado Livre" da tabela de estoque do detalhe: a ÚNICA coisa desta tela que chama a API do ML, e só por clique (1 Código ML por chamada).
    path('consultar/', views_ruptura.view_ruptura_consultar, name='gestao_ruptura_consultar'),
]
