from django.contrib import admin
from django.urls import path, include

# projeto_sistema_interno_mb_sv/urls.py
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('produtos/', include('produtos.urls')),
    # path('precificacao/', include('precificacao.urls')),
    # path('mercado-livre/', include('mercado_livre.urls')),
]