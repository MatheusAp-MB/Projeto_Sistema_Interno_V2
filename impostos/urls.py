from django.urls import path

from . import views

urlpatterns = [
    path('', views.view_resumo_impostos_entrada, name='impostos_resumo_entrada'),
    path('exportar/', views.view_exportar_resumo_impostos_entrada, name='impostos_exportar_resumo_entrada'),
]