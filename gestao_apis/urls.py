# gestao_apis/urls.py

from django.urls import path
from . import views_gestao_apis

urlpatterns = [
    # * [EXPLICAÇÃO] → Painel com os cartões de cada conexão (abrir não chama API externa).
    path('', views_gestao_apis.view_gestao_apis, name='gestao_apis_painel'),

    # * [EXPLICAÇÃO] → Testa UMA conexão (POST, com CSRF). Devolve o cartão novo + faixa de
    #                  urgência + tabela de eventos, tudo já atualizado.
    path('testar/<slug:conexao_id>/', views_gestao_apis.view_testar_conexao, name='gestao_apis_testar'),

    # * [EXPLICAÇÃO] → Renovar a autorização do Google Drive pela tela. "autorizar" (POST com CSRF) leva o navegador
    #                  ao Google; "retorno" (GET) é o endereço para onde o Google devolve o navegador — é ESTE
    #                  caminho que vale como endereço de retorno no Google Cloud (tipo "Aplicativo da Web").
    path('google/autorizar/', views_gestao_apis.view_iniciar_autorizacao_google, name='gestao_apis_google_autorizar'),
    path('google/retorno/', views_gestao_apis.view_retorno_autorizacao_google, name='gestao_apis_google_retorno'),

    # * [EXPLICAÇÃO] → O login do Google abre numa JANELA PEQUENA; a tela principal pergunta aqui, a cada poucos
    #                  segundos, se a janela já terminou (quando termina, a tela se recarrega e mostra o aviso).
    path('google/situacao/', views_gestao_apis.view_situacao_autorizacao_google, name='gestao_apis_google_situacao'),
]
