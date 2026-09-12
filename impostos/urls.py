from django.urls import path

from . import views

urlpatterns = [
    path('', views.view_resumo_impostos_entrada, name='impostos_resumo_entrada'),
    path('exportar/', views.view_exportar_resumo_impostos_entrada, name='impostos_exportar_resumo_entrada'),
    path('icms-por-ncm/', views.view_tabela_icms_por_ncm, name='impostos_tabela_icms_ncm'),
    path('icms-por-ncm/calcular/', views.view_calcular_icms_por_ncm, name='impostos_calcular_icms_ncm'),
]