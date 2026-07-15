from django.urls import path
from . import views

urlpatterns = [
    path('grade-mercado-livre/', views.view_grade_precificacao_ml, name='precificacao_grade_mercado_livre'),
    path(
        'grade-mercado-livre/detalhe/<int:produto_id>/<str:tipo>/<str:margem>/',
        views.view_grade_detalhe, name='precificacao_grade_detalhe',
    ),
]