from django.urls import path
from . import views

urlpatterns = [
    path('grade-mercado-livre/', views.view_grade_precificacao_ml, name='precificacao_grade_mercado_livre'),
]