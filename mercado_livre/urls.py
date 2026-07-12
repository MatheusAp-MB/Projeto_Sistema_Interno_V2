from django.urls import path
from . import views

urlpatterns = [
    path('anuncios/', views.view_hub_anuncios, name='mercado_livre_anuncios'),
    path('qualidade/<str:mlb>/', views.view_qualidade_anuncio, name='mercado_livre_qualidade'),
    path('competicao/<str:mlb>/', views.view_competicao_catalogo, name='mercado_livre_competicao'),
    path('resumo-criterios/', views.view_resumo_criterios, name='mercado_livre_resumo_criterios'),

    path('precificar/tabela-de-frete/', views.view_tabela_frete_ml, name='mercado_livre_tabela_frete'),
    path('precificar/tabela-de-frete/calcular/', views.view_calcular_frete_ml, name='mercado_livre_calcular_frete'),

    # * [EXPLICAÇÃO] → Recomendação de precificação por MLB — mostra
    #                  todas as opções de preço/promoção pra ganhar o
    #                  catálogo com segurança, seguindo 1 de 3
    #                  comportamentos possíveis. Tela de detalhe (1 MLB
    #                  por vez), igual Qualidade/Competição — a visão
    #                  agregada (tipo a Resumo de Critérios) é pendência
    #                  futura, não desenhada ainda.
    path('precificar/recomendacao/', views.view_recomendacao_precificacao, name='mercado_livre_recomendacao_precificacao'),
]


