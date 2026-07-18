from django.urls import path
from . import views

urlpatterns = [
    path('grade-mercado-livre/', views.view_grade_precificacao_ml, name='precificacao_grade_mercado_livre'),
    path(
        'grade-mercado-livre/detalhe/<int:produto_id>/<str:tipo>/<str:margem>/',
        views.view_grade_detalhe, name='precificacao_grade_detalhe',
    ),
    path('resumo-marketplaces/', views.view_resumo_marketplaces, name='precificacao_resumo_marketplaces'),
    path('configuracoes-operacionais/', views.view_configuracoes_operacionais, name='precificacao_configuracoes_operacionais'),
    path(
        'resumo-marketplaces/linha/<int:produto_id>/',
        views.view_resumo_linha, name='precificacao_resumo_linha',
    ),
]