# arquivos_referencia/urls.py

from django.urls import path
from . import views_arquivos_referencia

urlpatterns = [
    # * [EXPLICAÇÃO] → Painel com os cartões dos 6 arquivos de referência (abrir não lê nenhum arquivo).
    path('', views_arquivos_referencia.view_arquivos_referencia, name='arquivos_referencia_painel'),

    # * [EXPLICAÇÃO] → Confere UM arquivo escolhido (POST, com CSRF). Devolve o cartão novo, já com o relatório da auditoria.
    #                  Não grava nada: o arquivo só existe na memória durante a conferência.
    path('auditar/<slug:arquivo_id>/', views_arquivos_referencia.view_auditar_arquivo, name='arquivos_referencia_auditar'),

    # * [EXPLICAÇÃO] → O card de configuração no topo da tela: o MODO da planilha Busca Legal da empresa selecionada (Expandir ou Substituir). GET devolve o card;
    #                  POST (com CSRF) grava o modo no banco da empresa e devolve o card novo. Vale para o envio ao Drive e para o "Atualizar o sistema".
    path('modo/', views_arquivos_referencia.view_modo_da_importacao, name='arquivos_referencia_modo'),

    # * [EXPLICAÇÃO] → Envia UM arquivo ao Drive (POST, com CSRF). Confere o arquivo DE NOVO no servidor e só então troca o
    #                  que está no Drive. Devolve o cartão novo, já marcado como "Enviado ao Drive".
    path('enviar/<slug:arquivo_id>/', views_arquivos_referencia.view_enviar_arquivo, name='arquivos_referencia_enviar'),

    # * [EXPLICAÇÃO] → A linha "No Drive agora" de 1 cartão (GET, só leitura): o que existe hoje no Drive para esse arquivo.
    path('drive/<slug:arquivo_id>/', views_arquivos_referencia.view_situacao_no_drive, name='arquivos_referencia_drive'),

    # * [EXPLICAÇÃO] → Passo 2 (POST, com CSRF): atualiza o SISTEMA da empresa selecionada com UM arquivo que está no Drive (lê, confere e
    #                  grava nas tabelas só dessa empresa, tudo ou nada). Devolve a linha de resultado desse arquivo.
    path('atualizar/<slug:arquivo_id>/', views_arquivos_referencia.view_atualizar_arquivo, name='arquivos_referencia_atualizar'),

    # * [EXPLICAÇÃO] → Passo 3 (POST, com CSRF): recalcula UMA grade de preço local (Magalu, TikTok Shop, Amazon, Raia ou Shopee) da empresa selecionada, depois de
    #                  o passo 2 gravar algo que ela usa. Roda a mesma calculadora do terminal, tudo ou nada. Devolve a linha de resultado dessa grade.
    path('recalcular-grade/<slug:grade_id>/', views_arquivos_referencia.view_recalcular_grade, name='arquivos_referencia_recalcular_grade'),

    # * [EXPLICAÇÃO] → Prévia do modo Substituir da planilha Busca Legal (POST, com CSRF; NADA é gravado: a atualização roda e é desfeita no fim).
    #                  Devolve a lista exata do que o Substituir apagaria, para a pessoa ler e confirmar antes de gravar de verdade.
    path('previa/<slug:arquivo_id>/', views_arquivos_referencia.view_previa_do_substituir, name='arquivos_referencia_previa'),

    # * [EXPLICAÇÃO] → "Ver arquivo" (só leitura, nada é gravado): mostra o .xlsx como o Excel mostraria, numa janela.
    #                  GET = o arquivo que está no Drive agora (lido na hora). POST = o arquivo que a pessoa acabou de escolher no computador.
    path('ver/<slug:arquivo_id>/', views_arquivos_referencia.view_ver_arquivo_do_drive, name='arquivos_referencia_ver_drive'),
    path('ver-escolhido/<slug:arquivo_id>/', views_arquivos_referencia.view_ver_arquivo_escolhido, name='arquivos_referencia_ver_escolhido'),

    # * [EXPLICAÇÃO] → "Baixar" (GET, só leitura): entrega ao navegador uma CÓPIA do arquivo que está no Drive agora (útil como backup antes de
    #                  trocar o arquivo ou de atualizar o sistema). O servidor lê do Drive só na memória e repassa; nada é gravado nele.
    path('baixar/<slug:arquivo_id>/', views_arquivos_referencia.view_baixar_arquivo_do_drive, name='arquivos_referencia_baixar'),

    # * [EXPLICAÇÃO] → "Modelo" (GET, só leitura): uma planilha vazia no formato EXATO que o sistema lê para este arquivo, com as regras de cada coluna nas notas do cabeçalho.
    #                  Montada na hora, sem Drive e sem banco (ver modelo_do_arquivo.py).
    path('modelo/<slug:arquivo_id>/', views_arquivos_referencia.view_baixar_modelo, name='arquivos_referencia_modelo'),
]
