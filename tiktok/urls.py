from django.urls import path
from . import views

urlpatterns = [
    path('configuracoes/', views.view_configuracoes_tiktok, name='tiktok_configuracoes'),
    path('tabela-frete/', views.view_tabela_frete_tiktok, name='tiktok_tabela_frete'),
    path('tabela-frete/calcular/', views.view_calcular_frete_tiktok, name='tiktok_calcular_frete'),
]