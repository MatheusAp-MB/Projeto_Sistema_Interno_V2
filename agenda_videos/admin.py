# agenda_videos/admin.py

# Função Objetivo: Registro simples no admin — suficiente pra inspecionar/editar
# dado manualmente enquanto as telas de verdade não existem (Frente 3).

from django.contrib import admin
from .models import (
    ConfiguracaoFase, CicloVideo, ParticipacaoAgenda,
    HistoricoStatusManualAgenda, IndicadoresAgendaProduto,
)


@admin.register(ConfiguracaoFase)
class ConfiguracaoFaseAdmin(admin.ModelAdmin):
    list_display = ['fase', 'periodo_continuo', 'periodo', 'distancia_dias_corridos', 'distancia_dias_ao_entrar_na_fase', 'proxima_fase']


@admin.register(CicloVideo)
class CicloVideoAdmin(admin.ModelAdmin):
    list_display = ['produto', 'fase', 'numero_ocorrencia', 'data_devida', 'status', 'criado_em']
    list_filter = ['fase', 'status']
    search_fields = ['produto__sku', 'produto__ean']


@admin.register(ParticipacaoAgenda)
class ParticipacaoAgendaAdmin(admin.ModelAdmin):
    list_display = ['produto', 'urgente', 'agendado_em']
    search_fields = ['produto__sku', 'produto__ean']


@admin.register(HistoricoStatusManualAgenda)
class HistoricoStatusManualAgendaAdmin(admin.ModelAdmin):
    list_display = ['produto', 'status', 'alterado_em']
    list_filter = ['status']
    search_fields = ['produto__sku', 'produto__ean']


@admin.register(IndicadoresAgendaProduto)
class IndicadoresAgendaProdutoAdmin(admin.ModelAdmin):
    list_display = ['produto', 'etapa_atual', 'ciclo_atual_atrasado', 'status_manual', 'atualizado_em']
    list_filter = ['etapa_atual', 'status_manual']
    search_fields = ['produto__sku', 'produto__ean']