from django.urls import path
from . import views

urlpatterns = [
    path('', views.view_precificacao_hub, name='precificacao_hub'),
    path('grade-mercado-livre/', views.view_grade_precificacao_ml, name='precificacao_grade_mercado_livre'),
    path(
        'grade-mercado-livre/detalhe/<int:produto_id>/<str:tipo>/<str:margem>/',
        views.view_grade_detalhe, name='precificacao_grade_detalhe',
    ),
    path('resumo-marketplaces/', views.view_resumo_marketplaces, name='precificacao_resumo_marketplaces'),
    path('configuracoes-operacionais/', views.view_configuracoes_operacionais, name='precificacao_configuracoes_operacionais'),
    path('grade-magalu/', views.view_grade_precificacao_magalu, name='precificacao_grade_magalu'),
    path(
        'grade-magalu/detalhe/<int:produto_id>/<str:margem>/',
        views.view_grade_detalhe_magalu, name='precificacao_grade_detalhe_magalu',
    ),
    path('grade-raia/', views.view_grade_precificacao_raia, name='precificacao_grade_raia'),
    path(
        'grade-raia/detalhe/<int:produto_id>/<str:margem>/',
        views.view_grade_detalhe_raia, name='precificacao_grade_detalhe_raia',
    ),
    path('grade-shopee/', views.view_grade_precificacao_shopee, name='precificacao_grade_shopee'),
    path(
        'grade-shopee/detalhe/<int:produto_id>/<str:margem>/',
        views.view_grade_detalhe_shopee, name='precificacao_grade_detalhe_shopee',
    ),
    path(
        'resumo-marketplaces/linha/<int:produto_id>/',
        views.view_resumo_linha, name='precificacao_resumo_linha',
    ),
]