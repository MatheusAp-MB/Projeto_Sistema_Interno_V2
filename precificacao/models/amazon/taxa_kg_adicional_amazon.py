from django.db import models


class TaxaKgAdicionalAmazon(models.Model):
    # * [EXPLICAÇÃO] → Taxa MARGINAL — se aplica só quando o peso passa do teto da
    #                  matriz de FreteAmazon (~10kg): valor_da_faixa_maxima +
    #                  arredondar_pra_cima(peso - 10) × valor_por_kg. Keyed só por
    #                  faixa de preço (não por peso — é uma taxa por kg, não uma célula).

    tipo = models.CharField(max_length=3, choices=[('dba', 'DBA'), ('fba', 'FBA')])
    preco_min = models.DecimalField(max_digits=10, decimal_places=2)
    preco_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_por_kg = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Taxa de Kg Adicional Amazon'
        verbose_name_plural = 'Taxas de Kg Adicional Amazon'
        ordering = ['tipo', 'preco_min']

    def __str__(self):
        teto = self.preco_max if self.preco_max is not None else 'sem teto'
        return f'{self.tipo} | R$ {self.preco_min}-{teto} → R$ {self.valor_por_kg}/kg extra'