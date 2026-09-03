from django.urls import path
from . import views

urlpatterns = [
    path('configuracoes/', views.view_configuracoes_shopee, name='shopee_configuracoes'),
    path('promocao/', views.view_gerar_promocao, name='shopee_gerar_promocao'),
    path('promocao/processar/', views.view_processar_promocao, name='shopee_processar_promocao'),
    path('promocao/resultado/<str:token>/', views.view_resultado_promocao, name='shopee_resultado_promocao'),
    path('promocao/baixar/<str:token>/<path:marca>/<str:tipo>/', views.view_baixar_promocao, name='shopee_baixar_promocao'),
    path('promocao/baixar-todas/<str:token>/<str:categoria>/', views.view_baixar_todas_promocao, name='shopee_baixar_todas_promocao'),
    path('promocao/baixar-orfas/<str:token>/', views.view_baixar_linhas_orfas, name='shopee_baixar_linhas_orfas'),
]
