from django.urls import path
from . import views

urlpatterns = [
    path('tabela-frete/', views.view_tabela_frete_magalu, name='magalu_tabela_frete'),
    path('tabela-frete/calcular/', views.view_calcular_frete_magalu, name='magalu_calcular_frete'),
]