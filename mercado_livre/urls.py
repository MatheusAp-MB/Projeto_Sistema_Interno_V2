from django.urls import path
from . import views

urlpatterns = [
    path('anuncios/', views.view_hub_anuncios, name='mercado_livre_anuncios'),
    path('qualidade/<str:mlb>/', views.view_qualidade_anuncio, name='mercado_livre_qualidade'),
    path('competicao/<str:mlb>/', views.view_competicao_catalogo, name='mercado_livre_competicao'),
    path('resumo-criterios/', views.view_resumo_criterios, name='mercado_livre_resumo_criterios'),

    path('precificar/tabela-de-frete/', views.view_tabela_frete_ml, name='mercado_livre_tabela_frete'),
    path('precificar/tabela-de-frete/calcular/', views.view_calcular_frete_ml, name='mercado_livre_calcular_frete'),
]


