from django.db import models
from produtos.models import Produto


class VariacaoAnuncioMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → Fonte da verdade do MLB individual. Mesmo quando
    #                  um anúncio "não tem variação" na prática do ML,
    #                  ele sempre gera exatamente 1 registro aqui —
    #                  nunca existe caminho condicional "com/sem variação"
    #                  em nenhum outro lugar do sistema.

    anuncio = models.ForeignKey(
        'mercado_livre.AnuncioMercadoLivre',
        on_delete=models.CASCADE,
        related_name='variacoes'
    )

    variacao_id = models.CharField(max_length=30)

    # * [EXPLICAÇÃO] → sku_ml migra para aqui por decisão de negócio
    #                  confirmada (cada variação = produto distinto no
    #                  ERP, com EAN próprio). O JSON atual (detalhes_mlbs)
    #                  tem um bug conhecido na extração — todas as
    #                  variações aparecem com o mesmo SKU do pai. Isso
    #                  será corrigido na próxima extração da API;
    #                  reimportação será necessária quando isso ocorrer.
    sku_ml = models.CharField(max_length=30, blank=True, null=True)

    produto = models.ForeignKey(
        Produto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='variacoes_mercado_livre',
        to_field='sku'
    )

    estoque    = models.IntegerField(default=0)
    qtd_vendas = models.IntegerField(default=0)
    atributos  = models.CharField(max_length=255, blank=True, null=True)
    num_fotos  = models.IntegerField(default=0)

    class Meta:
        unique_together = ['anuncio', 'variacao_id']
        verbose_name        = 'Variação de Anúncio Mercado Livre'
        verbose_name_plural = 'Variações de Anúncio Mercado Livre'

    def __str__(self):
        return f'{self.anuncio.mlb} — {self.atributos or self.variacao_id}'