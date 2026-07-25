# agenda_videos/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.view_agenda_videos, name='agenda_videos_principal'),
    path('roadmap/<int:produto_id>/<str:chave>/confirmar/', views.view_confirmar_ponto_roadmap, name='agenda_videos_roadmap_confirmar'),
    path('roadmap/<int:produto_id>/<str:chave>/marcar/', views.view_marcar_ponto_roadmap, name='agenda_videos_roadmap_marcar'),
]