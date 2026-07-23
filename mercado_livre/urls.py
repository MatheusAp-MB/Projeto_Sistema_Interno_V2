from django.urls import path
from . import views

urlpatterns = [
    path('anuncios/', views.view_hub_anuncios, name='mercado_livre_anuncios'),
    path('qualidade/<str:mlb>/', views.view_qualidade_anuncio, name='mercado_livre_qualidade'),
    path('competicao/<str:mlb>/', views.view_competicao_catalogo, name='mercado_livre_competicao'),
    path('resumo-criterios/', views.view_resumo_criterios, name='mercado_livre_resumo_criterios'),
    path('resumo-criterios/exportar/', views.view_exportar_resumo_criterios, name='mercado_livre_exportar_resumo_criterios'),
    path('resumo-criterios/exportar-agenda-videos/', views.view_exportar_agenda_videos, name='mercado_livre_exportar_agenda_videos'),

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

    path('precificar/configuracoes/', views.view_configuracoes_mercado_livre, name='mercado_livre_configuracoes'),

    # * [EXPLICAÇÃO] → Visão agregada de promoções, mesma árvore do Hub
    #                  de Anúncios — o comentário acima (Recomendação de
    #                  Precificação) que dizia "visão agregada ainda não
    #                  desenhada" já não vale mais, essa é ela.
    path('precificar/hub-promocoes/', views.view_hub_promocoes, name='mercado_livre_hub_promocoes'),
]
