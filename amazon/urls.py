from django.urls import path
from . import views

urlpatterns = [
    path('configuracoes/', views.view_configuracoes_amazon, name='amazon_configuracoes'),
    path('tabela-frete/', views.view_tabela_frete_amazon, name='amazon_tabela_frete'),
    path('tabela-frete/calcular/', views.view_calcular_frete_amazon, name='amazon_calcular_frete'),
]