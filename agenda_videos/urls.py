# agenda_videos/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('diarios/', views.view_diarios, name='agenda_videos_diarios'),
]