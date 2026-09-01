# api/verificacao_aprovacao/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('marcar-estado/', views.view_marcar_estado, name='api_verificacao_aprovacao_marcar_estado'),
]