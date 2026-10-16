# arquivos_referencia/urls.py

from django.urls import path
from . import views_arquivos_referencia

urlpatterns = [
    # * [EXPLICAÇÃO] → Painel com os cartões dos 6 arquivos de referência (abrir não lê nenhum arquivo).
    path('', views_arquivos_referencia.view_arquivos_referencia, name='arquivos_referencia_painel'),

    # * [EXPLICAÇÃO] → Confere UM arquivo escolhido (POST, com CSRF). Devolve o cartão novo, já com o relatório da auditoria.
    #                  Não grava nada: o arquivo só existe na memória durante a conferência.
    path('auditar/<slug:arquivo_id>/', views_arquivos_referencia.view_auditar_arquivo, name='arquivos_referencia_auditar'),

    # * [EXPLICAÇÃO] → Envia UM arquivo ao Drive (POST, com CSRF). Confere o arquivo DE NOVO no servidor e só então troca o
    #                  que está no Drive. Devolve o cartão novo, já marcado como "Enviado ao Drive".
    path('enviar/<slug:arquivo_id>/', views_arquivos_referencia.view_enviar_arquivo, name='arquivos_referencia_enviar'),

    # * [EXPLICAÇÃO] → A linha "No Drive agora" de 1 cartão (GET, só leitura): o que existe hoje no Drive para esse arquivo.
    path('drive/<slug:arquivo_id>/', views_arquivos_referencia.view_situacao_no_drive, name='arquivos_referencia_drive'),

    # * [EXPLICAÇÃO] → Passo 2 (POST, com CSRF): atualiza o SISTEMA da empresa selecionada com UM arquivo que está no Drive (lê, confere e
    #                  grava nas tabelas só dessa empresa, tudo ou nada). Devolve a linha de resultado desse arquivo.
    path('atualizar/<slug:arquivo_id>/', views_arquivos_referencia.view_atualizar_arquivo, name='arquivos_referencia_atualizar'),

    # * [EXPLICAÇÃO] → "Ver arquivo" (só leitura, nada é gravado): mostra o .xlsx como o Excel mostraria, numa janela.
    #                  GET = o arquivo que está no Drive agora (lido na hora). POST = o arquivo que a pessoa acabou de escolher no computador.
    path('ver/<slug:arquivo_id>/', views_arquivos_referencia.view_ver_arquivo_do_drive, name='arquivos_referencia_ver_drive'),
    path('ver-escolhido/<slug:arquivo_id>/', views_arquivos_referencia.view_ver_arquivo_escolhido, name='arquivos_referencia_ver_escolhido'),
]
