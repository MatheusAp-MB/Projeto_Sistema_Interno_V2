# mercado_livre/urls.py (a criar)
urlpatterns = [
    path('anuncios/', views.view_produtos, name='mercado_livre_produtos'),
    path('precificacao/', views.view_precificacao, name='mercado_livre_precificacao'),
    # etc.
]