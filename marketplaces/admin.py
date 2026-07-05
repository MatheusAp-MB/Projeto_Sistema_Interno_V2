from django.contrib import admin
from .models import Marketplace


@admin.register(Marketplace)
class MarketplaceAdmin(admin.ModelAdmin):
    list_display = ['nome', 'sigla', 'ordem', 'ativo']