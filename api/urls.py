# api/urls.py

# Função Objetivo: Agrega as rotas de cada domínio da API — hoje só
# Postagem Automática, mas o padrão já nasce pronto pra crescer (cada
# domínio novo ganha sua própria pasta/urls.py, incluída aqui, sem nunca
# precisar mexer no que já existe).

from django.urls import path, include

urlpatterns = [
    path('postagem-automatica/', include('api.postagem_automatica.urls')),
    path('replicacao-automatica/', include('api.replicacao_automatica.urls')),
]