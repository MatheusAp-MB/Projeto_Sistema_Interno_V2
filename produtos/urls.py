from django.urls import path
from . import views

urlpatterns = [
    path('', views.view_produtos, name='produtos'),
    path('<int:produto_id>/', views.view_painel_produto, name='painel_produto'),
    path('<int:produto_id>/frete-fornecedor/', views.view_salvar_frete_fornecedor, name='salvar_frete_fornecedor_produto'),
]