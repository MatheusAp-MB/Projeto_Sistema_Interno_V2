# gestao_apis/urls.py

from django.urls import path
from . import views_gestao_apis

urlpatterns = [
    # * [EXPLICAÇÃO] → Painel com os cartões de cada conexão (abrir não chama API externa).
    path('', views_gestao_apis.view_gestao_apis, name='gestao_apis_painel'),

    # * [EXPLICAÇÃO] → Testa UMA conexão (POST, com CSRF). Devolve o cartão novo + faixa de
    #                  urgência + tabela de eventos, tudo já atualizado.
    path('testar/<slug:conexao_id>/', views_gestao_apis.view_testar_conexao, name='gestao_apis_testar'),
]
