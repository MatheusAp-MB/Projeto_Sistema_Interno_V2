from django.urls import path
from . import views

urlpatterns = [
    path('configuracoes/', views.view_configuracoes_raia, name='raia_configuracoes'),
]