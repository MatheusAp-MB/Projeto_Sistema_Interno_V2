# gestao_full/urls.py

from django.urls import path
from . import views_full
from . import views_full_planejamento

urlpatterns = [
    # * [EXPLICAÇÃO] → Tela FINAL "Full — Planejamento de envios" (a versão organizada, para apresentar). É a tela
    #                  principal do módulo (/gestao-full/). Só lê o banco e o detalhes_mlbs.json; o botão
    #                  "Consultar no Mercado Livre" dela usa a mesma view da ficha de debug (consultar/).
    path('', views_full_planejamento.view_full_planejamento, name='gestao_full_planejamento'),

    # * [EXPLICAÇÃO] → Tela "Full — ficha do código" (debug). Só lê do banco; a API do ML é chamada apenas
    #                  pelo botão "Consultar no Mercado Livre" (consultar/). Salvar nome interno, situação e
    #                  observação (campo/salvar/) grava só no banco.
    path('debug/', views_full.view_full_ficha, name='gestao_full_debug'),
    path('consultar/', views_full.view_full_consultar, name='gestao_full_consultar'),
    path('campo/salvar/', views_full.view_full_salvar_campo, name='gestao_full_salvar_campo'),
]
