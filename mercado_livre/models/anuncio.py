from django.db import models


class AnuncioMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Agrupador — dados confirmados como idênticos entre
    #                  todas as variações do mesmo MLB (validado com dado
    #                  real: título, status/tipo, catálogo, datas e
    #                  permalink não mudam entre variações de um MLB).
    mlb  = models.CharField(max_length=20, unique=True)

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

    permalink  = models.URLField(max_length=500, blank=True, null=True)
    data_criacao_ml       = models.DateTimeField(blank=True, null=True)
    ultima_atualizacao_ml = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name        = 'Anúncio Mercado Livre'
        verbose_name_plural = 'Anúncios Mercado Livre'
        ordering            = ['mlb']

    def __str__(self):
        return f'{self.mlb} — {self.titulo_anuncio}'