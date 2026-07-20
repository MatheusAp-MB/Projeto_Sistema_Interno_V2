from django.urls import path
from . import views

urlpatterns = [
    path('configuracoes/', views.view_configuracoes_tiktok, name='tiktok_configuracoes'),
    path('tabela-frete/', views.view_tabela_frete_tiktok, name='tiktok_tabela_frete'),
    path('tabela-frete/calcular/', views.view_calcular_frete_tiktok, name='tiktok_calcular_frete'),
    path('promocao/', views.view_gerar_promocao, name='tiktok_gerar_promocao'),
    path('promocao/processar/', views.view_processar_promocao, name='tiktok_processar_promocao'),
    path('promocao/resultado/<str:token>/', views.view_resultado_promocao, name='tiktok_resultado_promocao'),
    path('promocao/baixar/<str:token>/<str:marca>/<str:tipo>/', views.view_baixar_promocao, name='tiktok_baixar_promocao'),
    path('promocao/baixar-todas/<str:token>/<str:categoria>/', views.view_baixar_todas_promocao, name='tiktok_baixar_todas_promocao'),
]