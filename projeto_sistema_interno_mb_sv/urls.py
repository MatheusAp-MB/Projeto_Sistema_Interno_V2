from django.contrib import admin
from django.urls import path, include

# projeto_sistema_interno_mb_sv/urls.py
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('produtos/', include('produtos.urls')),
    path('marketplaces/', include('marketplaces.urls')),
    path('mercado-livre/', include('mercado_livre.urls')),
    path('magalu/', include('magalu.urls')),
    path('raia/', include('raia.urls')),
    path('shopee/', include('shopee.urls')),
    path('precificacao/', include('precificacao.urls')),
]