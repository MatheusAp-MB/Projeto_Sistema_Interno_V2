# produtos/admin.py

# Função Objetivo: Configuração do Django Admin pro model Produto — permite editar
# todos os campos de custo/impostos/dimensão diretamente, sem precisar de tela própria.

from django.contrib import admin
from .models import Produto


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = [
        'ean', 'sku', 'cod_fabricante', 'ncm', 'titulo', 'marca', 'categoria', 'curva',
        'imagem_url', 'estoque', 'custo', 'custo_com_boni',
        'peso_produto_sem_embalar', 'altura_produto_sem_embalar',
        'largura_produto_sem_embalar', 'comprimento_produto_sem_embalar',
        'peso_produto_apos_embalado', 'altura_produto_apos_embalado',
        'largura_produto_apos_embalado', 'comprimento_produto_apos_embalado',
        'peso_cubado', 'mva', 'st_valor', 'icms_entrada', 'icms_saida_sp',
        'icms_saida_media', 'ipi', 'pis_cofins', 'frete_cif_fob',
        'armazenagem_planilha', 'ultima_compra', 'cadastrado_erp_em',
        'criado_em', 'atualizado_em',
    ]

    search_fields = ['ean', 'sku', 'titulo', 'cod_fabricante']
    list_filter = ['marca', 'categoria', 'curva']

    readonly_fields = ['peso_cubado', 'criado_em', 'atualizado_em']

    fieldsets = (
        ('Identificação', {
            'fields': (
                'ean', 'sku', 'cod_fabricante', 'ncm',
                'titulo', 'marca', 'categoria', 'curva',
                'imagem_url', 'estoque',
            ),
        }),
        ('Custo & Impostos', {
            'fields': (
                'custo', 'custo_com_boni',
                'mva', 'st_valor', 'icms_entrada', 'icms_saida_sp',
                'icms_saida_media', 'ipi', 'pis_cofins', 'frete_cif_fob',
            ),
        }),
        ('Dimensão — Produto sem embalar', {
            'fields': (
                'peso_produto_sem_embalar', 'altura_produto_sem_embalar',
                'largura_produto_sem_embalar', 'comprimento_produto_sem_embalar',
            ),
        }),
        ('Dimensão — Produto após embalado (usada no cálculo de frete)', {
            'fields': (
                'peso_produto_apos_embalado', 'altura_produto_apos_embalado',
                'largura_produto_apos_embalado', 'comprimento_produto_apos_embalado',
                'peso_cubado',
            ),
        }),
        ('Armazenagem & Datas', {
            'fields': (
                'armazenagem_planilha', 'ultima_compra', 'cadastrado_erp_em',
                'criado_em', 'atualizado_em',
            ),
        }),
    )