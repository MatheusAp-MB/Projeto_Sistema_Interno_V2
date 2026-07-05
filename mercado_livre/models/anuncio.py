# mercado_livre/models/anuncio.py

from django.db import models
from produtos.models import Produto


class AnuncioMercadoLivre(models.Model):
    mlb  = models.CharField(max_length=20, unique=True)
    mlbu = models.CharField(max_length=20, blank=True, null=True)

    sku_ml = models.CharField(max_length=30, blank=True, null=True)

    produto = models.ForeignKey(
        Produto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='anuncios_mercado_livre',
        to_field='sku'
    )

    titulo_anuncio = models.CharField(max_length=255, blank=True, null=True)

    tipo_de_anuncio = models.ForeignKey(
        'mercado_livre.TipoDeAnuncioMercadoLivre',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='anuncios'
    )

    catalog_product_id = models.CharField(max_length=30, blank=True, null=True)
    catalog_listing     = models.BooleanField(null=True, blank=True)
    item_relations      = models.JSONField(blank=True, null=True)

    estoque    = models.IntegerField(default=0)
    qtd_vendas = models.IntegerField(default=0)
    permalink  = models.URLField(max_length=500, blank=True, null=True)

    data_criacao_ml       = models.DateTimeField(blank=True, null=True)
    ultima_atualizacao_ml = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name        = 'Anúncio Mercado Livre'
        verbose_name_plural = 'Anúncios Mercado Livre'
        ordering            = ['mlb']

    def __str__(self):
        return f'{self.mlb} — {self.titulo_anuncio}'