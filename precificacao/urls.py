from django.urls import path
from . import views

urlpatterns = [
    path('', views.view_precificacao_hub, name='precificacao_hub'),
    path('exportar-precos/', views.view_exportar_precificacao, name='precificacao_exportar_precos'),
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
    path('grade-tiktok/', views.view_grade_precificacao_tiktok, name='precificacao_grade_tiktok'),
    path(
        'grade-tiktok/detalhe/<int:produto_id>/<str:tipo>/<str:margem>/',
        views.view_grade_detalhe_tiktok, name='precificacao_grade_detalhe_tiktok',
    ),
    path('grade-amazon/', views.view_grade_precificacao_amazon, name='precificacao_grade_amazon'),
    path(
        'grade-amazon/detalhe/<int:produto_id>/<str:tipo>/<str:margem>/',
        views.view_grade_detalhe_amazon, name='precificacao_grade_detalhe_amazon',
    ),
    path(
        'resumo-marketplaces/linha/<int:produto_id>/',
        views.view_resumo_linha, name='precificacao_resumo_linha',
    ),
]