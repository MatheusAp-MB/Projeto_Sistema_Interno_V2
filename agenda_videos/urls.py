# agenda_videos/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.view_agenda_videos, name='agenda_videos_principal'),
    path('configuracoes/', views.view_configuracoes_agenda_videos, name='agenda_videos_configuracoes'),
    path('roadmap/<int:produto_id>/<str:chave>/confirmar/', views.view_confirmar_ponto_roadmap, name='agenda_videos_roadmap_confirmar'),
    path('roadmap/<int:produto_id>/<str:chave>/marcar/', views.view_marcar_ponto_roadmap, name='agenda_videos_roadmap_marcar'),
    path('roadmap/<int:produto_id>/<str:chave>/acao/<str:acao>/', views.view_executar_acao_ciclica, name='agenda_videos_roadmap_acao_ciclica'),
    path('roadmap/<int:produto_id>/agendar/<str:fase_inicial>/', views.view_agendar_produto, name='agenda_videos_agendar_produto'),
    path('produto/<int:produto_id>/urgente/alternar/', views.view_alternar_urgente, name='agenda_videos_alternar_urgente'),
    path('produto/<int:produto_id>/verificar-drive/', views.view_verificar_produto_drive, name='agenda_videos_verificar_drive'),
    path('verificar-todos-drive/', views.view_verificar_todos_drive, name='agenda_videos_verificar_todos_drive'),
    path('historico/', views.view_historico_agenda_videos, name='agenda_videos_historico'),
    path('produto/<int:produto_id>/historico/', views.view_historico_produto, name='agenda_videos_historico_produto'),
]