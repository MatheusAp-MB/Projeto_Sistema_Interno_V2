# api/replicacao_automatica/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('execucao/<int:execucao_id>/itens/', views.view_listar_itens, name='api_replicacao_listar_itens'),
    path('execucao/<int:execucao_id>/heartbeat/', views.view_heartbeat, name='api_replicacao_heartbeat'),
    path('execucao/<int:execucao_id>/finalizar/', views.view_finalizar_execucao, name='api_replicacao_finalizar_execucao'),
    path('item/<int:item_id>/concluido/', views.view_marcar_concluido, name='api_replicacao_marcar_concluido'),
    path('item/<int:item_id>/falhou/', views.view_marcar_falhou, name='api_replicacao_marcar_falhou'),
]