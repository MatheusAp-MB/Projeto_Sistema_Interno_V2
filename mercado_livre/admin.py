from django.contrib import admin
from .models import (
    TipoDeAnuncioMercadoLivre, AnuncioMercadoLivre, VariacaoAnuncioMercadoLivre,
    ConfiguracaoMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre, FaixaArmazenagemMercadoLivre,
)

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

@admin.register(ConfiguracaoMercadoLivre)
class ConfiguracaoMercadoLivreAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'fator_coleta', 'periodo_armazenagem', 'atualizado_em']

    def has_add_permission(self, request):
        # * [EXPLICAÇÃO] → Singleton — nunca deve existir mais de 1 linha.
        return not ConfiguracaoMercadoLivre.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfiguracaoTipoAnuncioMercadoLivre)
class ConfiguracaoTipoAnuncioMercadoLivreAdmin(admin.ModelAdmin):
    list_display = [
        '__str__', 'comissao', 'acrescimo_preco',
        'margem_minima', 'margem_padrao', 'margem_maxima', 'margem_competicao',
    ]
    list_filter = ['tipo_anuncio', 'tipo_logistico', 'catalogo']


@admin.register(FaixaArmazenagemMercadoLivre)
class FaixaArmazenagemMercadoLivreAdmin(admin.ModelAdmin):
    list_display = ['ordem', 'nome', 'valor_diario', 'max_altura', 'max_largura', 'max_profundidade', 'ativo']
    list_editable = ['ativo']
    ordering = ['ordem']