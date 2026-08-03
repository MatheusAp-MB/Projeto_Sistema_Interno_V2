# agenda_videos/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.view_agenda_videos, name='agenda_videos_principal'),
    path('configuracoes/', views.view_configuracoes_agenda_videos, name='agenda_videos_configuracoes'),
    path('roadmap/<int:produto_id>/<str:chave>/confirmar/', views.view_confirmar_ponto_roadmap, name='agenda_videos_roadmap_confirmar'),
    path('roadmap/<int:produto_id>/<str:chave>/marcar/', views.view_marcar_ponto_roadmap, name='agenda_videos_roadmap_marcar'),
    path('roadmap/<int:produto_id>/acao/<str:acao>/', views.view_executar_acao_ciclica, name='agenda_videos_roadmap_acao_ciclica'),
    path('roadmap/<int:produto_id>/agendar/', views.view_agendar_produto, name='agenda_videos_agendar_produto'),
    path('produto/<int:produto_id>/urgente/alternar/', views.view_alternar_urgente, name='agenda_videos_alternar_urgente'),
    path('produto/<int:produto_id>/verificar-drive/', views.view_verificar_produto_drive, name='agenda_videos_verificar_drive'),
    path('verificar-todos-drive/', views.view_verificar_todos_drive, name='agenda_videos_verificar_todos_drive'),
    path('postagem-automatica/confirmar/', views.view_confirmar_postagem_automatica, name='agenda_videos_confirmar_postagem_automatica'),
    path('postagem-automatica/iniciar/', views.view_iniciar_postagem_automatica, name='agenda_videos_iniciar_postagem_automatica'),
    path('postagem-automatica/<int:execucao_id>/progresso/', views.view_progresso_postagem_automatica, name='agenda_videos_progresso_postagem_automatica'),
    path('postagem-automatica/<int:execucao_id>/progresso/parcial/', views.view_progresso_postagem_automatica_parcial, name='agenda_videos_progresso_postagem_automatica_parcial'),
    path('postagem-automatica/<int:execucao_id>/cancelar-travada/', views.view_cancelar_execucao_travada, name='agenda_videos_cancelar_execucao_travada'),
    path('replicacao-automatica/confirmar/', views.view_confirmar_replicacao_automatica, name='agenda_videos_confirmar_replicacao_automatica'),
    path('replicacao-automatica/iniciar/', views.view_iniciar_replicacao_automatica, name='agenda_videos_iniciar_replicacao_automatica'),
    path('replicacao-automatica/<int:execucao_id>/progresso/', views.view_progresso_replicacao_automatica, name='agenda_videos_progresso_replicacao_automatica'),
    path('replicacao-automatica/<int:execucao_id>/progresso/parcial/', views.view_progresso_replicacao_automatica_parcial, name='agenda_videos_progresso_replicacao_automatica_parcial'),
    path('replicacao-automatica/<int:execucao_id>/cancelar-travada/', views.view_cancelar_execucao_replicacao_travada, name='agenda_videos_cancelar_execucao_replicacao_travada'),
    path('historico/', views.view_historico_agenda_videos, name='agenda_videos_historico'),
    path('produto/<int:produto_id>/historico/', views.view_historico_produto, name='agenda_videos_historico_produto'),
    path('produto/<int:produto_id>/status-agenda/alternar/', views.view_alternar_pausado_agenda, name='agenda_videos_alternar_pausado'),
]