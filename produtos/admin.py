# produtos/admin.py

# Função Objetivo: Configuração do Django Admin pro model Produto — permite editar
# todos os campos de custo/impostos/dimensão diretamente, sem precisar de tela própria.

from django.contrib import admin
from .models import Produto, CodigoAssociadoProduto, ProdutoAnuncioMarketplace


# Função Objetivo: Edita os Códigos Associados direto na tela do Produto, sem precisar
# procurar o produto de novo numa tela separada.
class CodigoAssociadoProdutoInline(admin.TabularInline):
    model = CodigoAssociadoProduto
    extra = 1


# Função Objetivo: Edita os Marketplaces Anunciados direto na tela do Produto.
class ProdutoAnuncioMarketplaceInline(admin.TabularInline):
    model = ProdutoAnuncioMarketplace
    extra = 1


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    inlines = [CodigoAssociadoProdutoInline, ProdutoAnuncioMarketplaceInline]
    list_display = [
        'ean', 'sku', 'cod_fabricante', 'ncm', 'titulo', 'marca', 'categoria', 'curva',
        'imagem_url', 'estoque', 'custo', 'custo_com_boni',
        'peso_produto_sem_embalar', 'altura_produto_sem_embalar',
        'largura_produto_sem_embalar', 'comprimento_produto_sem_embalar',
        'peso_produto_apos_embalado', 'altura_produto_apos_embalado',
        'largura_produto_apos_embalado', 'comprimento_produto_apos_embalado',
        'peso_cubado', 'icms_saida_sp',
        'icms_saida_media', 'pis_percentual', 'cofins_percentual', 'frete_cif_fob',
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
                'icms_saida_sp', 'icms_saida_media',
                'pis_percentual', 'cofins_percentual', 'frete_cif_fob',
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

