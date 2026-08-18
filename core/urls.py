
# * [RESUMO] → URLs do app core. Define as rotas globais do sistema — login e logout.

from django.urls import path
from . import views

urlpatterns = [
    # * [EXPLICAÇÃO] → Rota de login — acessível sem autenticação.
    #                  Definida como rota pública no middleware.
    path('login/', views.view_login, name='login'),

    # * [EXPLICAÇÃO] → Rota de logout — encerra a sessão e redireciona
    #                  para o login.
    path('logout/', views.view_logout, name='logout'),

    # * [EXPLICAÇÃO] → Tela de escolher/trocar a empresa ativa.
    path('empresa/', views.view_escolher_empresa, name='escolher_empresa'),

    # * [EXPLICAÇÃO] → Rota da homepage — raiz do sistema.
    #                  Após o login, o usuário é redirecionado para cá.
    path('', views.view_home, name='home'),
]
