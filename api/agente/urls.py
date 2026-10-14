# api/agente/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('ping/', views.view_ping, name='api_agente_ping'),
]
