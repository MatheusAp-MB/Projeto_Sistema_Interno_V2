# agenda_videos/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('diarios/', views.view_diarios, name='agenda_videos_diarios'),
    path('roadmap/<int:produto_id>/<str:chave>/confirmar/', views.view_confirmar_ponto_roadmap, name='agenda_videos_roadmap_confirmar'),
    path('roadmap/<int:produto_id>/<str:chave>/marcar/', views.view_marcar_ponto_roadmap, name='agenda_videos_roadmap_marcar'),
]