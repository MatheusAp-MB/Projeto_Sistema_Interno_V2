# gestao_full/urls.py

from django.urls import path
from . import views_full
from . import views_full_planejamento
from . import views_full_estoque
from . import views_full_comparativo

urlpatterns = [
    # * [EXPLICAÇÃO] → Tela FINAL "Full — Planejamento de envios" (a versão organizada, para apresentar). É a tela
    #                  principal do módulo (/gestao-full/). Só lê o banco e o detalhes_mlbs.json; o botão
    #                  "Consultar no Mercado Livre" dela usa a mesma view da ficha de debug (consultar/).
    path('', views_full_planejamento.view_full_planejamento, name='gestao_full_planejamento'),

    # * [EXPLICAÇÃO] → Tela "Full — Estoque no Full" (07/10/2026): quanto cada produto tem no Full hoje, somando os Códigos ML
    #                  dele. Só lê o banco (Códigos ML + consultas já salvas); nunca chama a API do ML sozinha.
    path('estoque/', views_full_estoque.view_full_estoque, name='gestao_full_estoque'),

    # * [EXPLICAÇÃO] → Botões de atualização da tela "Estoque no Full" (os ÚNICOS caminhos em que ela chega ao ML, sempre por clique):
    #                  "Atualizar" / "Atualizar produto" (atualizar/) e "Fazer varredura completa" (varredura/iniciar/, com o andamento
    #                  em varredura/status/ e o botão Parar em varredura/parar/). Todos usam a consulta do Planejamento (consultar_codigo).
    path('estoque/atualizar/', views_full_estoque.view_full_estoque_atualizar, name='gestao_full_estoque_atualizar'),
    path('estoque/faixa/', views_full_estoque.view_full_estoque_faixa, name='gestao_full_estoque_faixa'),
    path('estoque/varredura/iniciar/', views_full_estoque.view_full_estoque_varredura_iniciar, name='gestao_full_estoque_varredura_iniciar'),
    path('estoque/varredura/status/', views_full_estoque.view_full_estoque_varredura_status, name='gestao_full_estoque_varredura_status'),
    path('estoque/varredura/parar/', views_full_estoque.view_full_estoque_varredura_parar, name='gestao_full_estoque_varredura_parar'),

    # * [EXPLICAÇÃO] → Tela "Full — Comparativo de estoque (debug)" (10/10/2026): o estoque de cada SKU lado a lado em Arquivo do ERP | API Sysemp |
    #                  API Mercado Livre. Só lê (arquivo, coleta guardada, banco). A API Sysemp só é chamada pelo botão "Coletar do Sysemp"
    #                  (coletar/, com o andamento em coletar/status/ e o botão Parar em coletar/parar/). O botão "Exportar Excel" (exportar/) baixa a lista
    #                  inteira num .xlsx e também só lê.
    path('comparativo-estoque/', views_full_comparativo.view_full_comparativo, name='gestao_full_comparativo_estoque'),
    path('comparativo-estoque/exportar/', views_full_comparativo.view_full_comparativo_exportar, name='gestao_full_comparativo_exportar'),
    path('comparativo-estoque/coletar/', views_full_comparativo.view_full_comparativo_coletar_iniciar, name='gestao_full_comparativo_coletar'),
    path('comparativo-estoque/coletar/status/', views_full_comparativo.view_full_comparativo_coletar_status, name='gestao_full_comparativo_coletar_status'),
    path('comparativo-estoque/coletar/parar/', views_full_comparativo.view_full_comparativo_coletar_parar, name='gestao_full_comparativo_coletar_parar'),

    # * [EXPLICAÇÃO] → Tela "Full — ficha do código" (debug). Só lê do banco; a API do ML é chamada apenas
    #                  pelo botão "Consultar no Mercado Livre" (consultar/). Salvar nome interno, situação e
    #                  observação (campo/salvar/) grava só no banco.
    path('debug/', views_full.view_full_ficha, name='gestao_full_debug'),
    path('consultar/', views_full.view_full_consultar, name='gestao_full_consultar'),
    path('campo/salvar/', views_full.view_full_salvar_campo, name='gestao_full_salvar_campo'),
]
