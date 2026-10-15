# arquivos_referencia/urls.py

from django.urls import path
from . import views_arquivos_referencia

urlpatterns = [
    # * [EXPLICAÇÃO] → Painel com os cartões dos 6 arquivos de referência (abrir não lê nenhum arquivo).
    path('', views_arquivos_referencia.view_arquivos_referencia, name='arquivos_referencia_painel'),

    # * [EXPLICAÇÃO] → Confere UM arquivo enviado (POST, com CSRF). Devolve o cartão novo, já com o relatório da auditoria.
    #                  Não grava nada: o arquivo só existe na memória durante a conferência.
    path('auditar/<slug:arquivo_id>/', views_arquivos_referencia.view_auditar_arquivo, name='arquivos_referencia_auditar'),
]
