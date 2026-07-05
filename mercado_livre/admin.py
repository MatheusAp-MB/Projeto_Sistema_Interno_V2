from django.contrib import admin
from .models import TipoDeAnuncioMercadoLivre, AnuncioMercadoLivre


@admin.register(TipoDeAnuncioMercadoLivre)
class TipoDeAnuncioMercadoLivreAdmin(admin.ModelAdmin):
    list_display = ['nome', 'status', 'tipo_anuncio', 'tipo_logistico', 'classificacao_catalogo', 'flex']
    list_filter  = ['status', 'tipo_anuncio', 'tipo_logistico', 'classificacao_catalogo', 'flex']


@admin.register(AnuncioMercadoLivre)
class AnuncioMercadoLivreAdmin(admin.ModelAdmin):
    list_display = ['mlb', 'titulo_anuncio', 'produto', 'tipo_de_anuncio', 'estoque']
    list_filter   = ['tipo_de_anuncio']
    search_fields = ['mlb', 'mlbu', 'sku_ml', 'titulo_anuncio']