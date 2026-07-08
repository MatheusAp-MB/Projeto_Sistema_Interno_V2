from django.urls import path
from . import views

urlpatterns = [
    path('anuncios/', views.view_hub_anuncios, name='mercado_livre_anuncios'),
    path('qualidade/<str:mlb>/', views.view_qualidade_anuncio, name='mercado_livre_qualidade'),
    path('competicao/<str:mlb>/', views.view_competicao_catalogo, name='mercado_livre_competicao'),
    path('resumo-criterios/', views.view_resumo_criterios, name='mercado_livre_resumo_criterios'),
]