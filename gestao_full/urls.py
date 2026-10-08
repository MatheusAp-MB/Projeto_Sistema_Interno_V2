# gestao_full/urls.py

from django.urls import path
from . import views_full
from . import views_full_planejamento
from . import views_full_estoque

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

    # * [EXPLICAÇÃO] → Tela "Full — ficha do código" (debug). Só lê do banco; a API do ML é chamada apenas
    #                  pelo botão "Consultar no Mercado Livre" (consultar/). Salvar nome interno, situação e
    #                  observação (campo/salvar/) grava só no banco.
    path('debug/', views_full.view_full_ficha, name='gestao_full_debug'),
    path('consultar/', views_full.view_full_consultar, name='gestao_full_consultar'),
    path('campo/salvar/', views_full.view_full_salvar_campo, name='gestao_full_salvar_campo'),
]
