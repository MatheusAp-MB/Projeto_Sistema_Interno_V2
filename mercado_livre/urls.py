from django.urls import path
from . import views
from . import views_caracteristicas
from . import views_full

urlpatterns = [
    path('anuncios/', views.view_hub_anuncios, name='mercado_livre_anuncios'),
    path('categorias/', views.view_categorias_ml, name='mercado_livre_categorias'),
    path('categorias/selecionar/<str:category_id>/', views.view_categorias_selecionar, name='mercado_livre_categorias_selecionar'),
    path('categorias/buscar/', views.view_categorias_buscar, name='mercado_livre_categorias_buscar'),
    path('fotos/', views.view_hub_fotos, name='mercado_livre_hub_fotos'),

    # * [EXPLICAÇÃO] → Tela "Características dos anúncios". Só lê do banco;
    #                  a API do ML é chamada apenas pelos 3 botões da tela
    #                  (varredura completa, "Atualizar" e "Confirmar envio"
    #                  de 1 produto), via as rotas de POST abaixo. A rota
    #                  "revisar-envio/" só confere e mostra a prévia: não
    #                  chama a API. O SKU usa <path:> e as rotas com sufixo
    #                  (atualizar/, revisar-envio/, enviar/) vêm antes da
    #                  rota da ficha de propósito.
    path('caracteristicas/', views_caracteristicas.view_caracteristicas_anuncios, name='mercado_livre_caracteristicas'),
    path('caracteristicas/varredura/iniciar/', views_caracteristicas.view_caracteristicas_varredura_iniciar, name='mercado_livre_caracteristicas_varredura_iniciar'),
    path('caracteristicas/varredura/status/', views_caracteristicas.view_caracteristicas_varredura_status, name='mercado_livre_caracteristicas_varredura_status'),
    path('caracteristicas/produto/<path:sku>/atualizar/', views_caracteristicas.view_caracteristicas_atualizar_produto, name='mercado_livre_caracteristicas_atualizar'),
    path('caracteristicas/produto/<path:sku>/revisar-envio/', views_caracteristicas.view_caracteristicas_revisar_envio, name='mercado_livre_caracteristicas_revisar_envio'),
    path('caracteristicas/produto/<path:sku>/enviar/', views_caracteristicas.view_caracteristicas_enviar_produto, name='mercado_livre_caracteristicas_enviar'),
    path('caracteristicas/produto/<path:sku>/', views_caracteristicas.view_caracteristicas_ficha, name='mercado_livre_caracteristicas_ficha'),

    # * [EXPLICAÇÃO] → Tela "Full — ficha do código". Só lê do banco; a API do ML é
    #                  chamada apenas pelo botão "Consultar no Mercado Livre"
    #                  (full/consultar/). Salvar nome interno, situação e
    #                  observação (full/campo/salvar/) grava só no banco.
    path('full/', views_full.view_full_ficha, name='mercado_livre_full'),
    path('full/consultar/', views_full.view_full_consultar, name='mercado_livre_full_consultar'),
    path('full/campo/salvar/', views_full.view_full_salvar_campo, name='mercado_livre_full_salvar_campo'),

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
