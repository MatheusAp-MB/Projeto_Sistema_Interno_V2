from django.urls import path
from . import views

urlpatterns = [
    path('anuncios/', views.view_hub_anuncios, name='mercado_livre_anuncios'),
    path('qualidade/<str:mlb>/', views.view_qualidade_anuncio, name='mercado_livre_qualidade'),
]