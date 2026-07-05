from django.contrib import admin
from .models import TipoDeAnuncioMercadoLivre, AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre


@admin.register(TipoDeAnuncioMercadoLivre)
class TipoDeAnuncioMercadoLivreAdmin(admin.ModelAdmin):
    list_display = ['nome', 'status', 'tipo_anuncio', 'tipo_logistico', 'classificacao_catalogo', 'flex']
    list_filter  = ['status', 'tipo_anuncio', 'tipo_logistico', 'classificacao_catalogo', 'flex']


@admin.register(AnuncioMercadoLivre)
class AnuncioMercadoLivreAdmin(admin.ModelAdmin):
    list_display = ['mlb', 'titulo_anuncio', 'tipo_de_anuncio']
    list_filter   = ['tipo_de_anuncio']
    search_fields = ['mlb', 'titulo_anuncio']


@admin.register(VariacaoAnuncioMercadoLivre)
class VariacaoAnuncioMercadoLivreAdmin(admin.ModelAdmin):
    list_display  = ['anuncio', 'variacao_id', 'sku_ml', 'produto', 'estoque', 'atributos']
    search_fields  = ['variacao_id', 'sku_ml']