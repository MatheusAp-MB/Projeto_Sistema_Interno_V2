# agenda_videos/admin.py

# Função Objetivo: Registro simples no admin — mesmo padrão usado em produtos/admin.py,
# suficiente pra inspecionar/editar dado manualmente enquanto as telas de verdade não existem.

from django.contrib import admin
from .models import ConfiguracaoFase, ProgressoProducaoVideo, AndamentoAgenda, Postagem, PreparacaoVideoFase


@admin.register(ConfiguracaoFase)
class ConfiguracaoFaseAdmin(admin.ModelAdmin):
    list_display = ['fase', 'quantidade_postagens', 'periodo']


@admin.register(ProgressoProducaoVideo)
class ProgressoProducaoVideoAdmin(admin.ModelAdmin):
    list_display = ['produto', 'video_simples_status', 'video_base_status']
    list_filter = ['video_simples_status', 'video_base_status']
    search_fields = ['produto__sku', 'produto__ean']


@admin.register(PreparacaoVideoFase)
class PreparacaoVideoFaseAdmin(admin.ModelAdmin):
    list_display = ['produto', 'fase', 'roteiros_gerados', 'completos_produzidos', 'quantidade_roteiros', 'roteiros_insuficientes']
    list_filter = ['fase', 'roteiros_gerados', 'completos_produzidos']
    search_fields = ['produto__sku', 'produto__ean']


@admin.register(AndamentoAgenda)
class AndamentoAgendaAdmin(admin.ModelAdmin):
    list_display = [
        'produto', 'fase_atual', 'ocorrencia_atual',
        'inicio_fase', 'fim_fase', 'status_manual', 'urgente',
    ]
    list_filter = ['fase_atual', 'status_manual', 'urgente']
    search_fields = ['produto__sku', 'produto__ean']


@admin.register(Postagem)
class PostagemAdmin(admin.ModelAdmin):
    list_display = ['produto', 'fase', 'numero_ocorrencia', 'status', 'inicio_ocorrencia', 'fim_ocorrencia']
    list_filter = ['fase', 'status']
    search_fields = ['produto__sku', 'produto__ean']