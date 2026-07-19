from django.db import models


class FreteAmazon(models.Model):
    # * [EXPLICAÇÃO] → Peso × preço (matriz 2D, igual estrutura original do FreteML) —
    #                  confirmado pela fórmula real da planilha (SE($EL$2="DBA",
    #                  Frete_AMZ_2, Frete_AMZ_4)). peso_min/peso_max NULOS = faixa de
    #                  preço baixo (<R$79), onde o frete é fixo e NÃO depende do peso
    #                  — confirmado na tabela original (mesmo valor pra todo peso ali).
    #                  "Kg adicional" (acima do teto da tabela, ~10kg) fica em
    #                  TaxaKgAdicionalAmazon, é uma taxa marginal, não uma célula
    #                  desta matriz.

    class Tipo(models.TextChoices):
        DBA = 'dba', 'DBA (logística própria)'
        FBA = 'fba', 'FBA (Amazon guarda e despacha)'

    tipo = models.CharField(max_length=3, choices=Tipo.choices)

    peso_min = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    peso_max = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)

    preco_min = models.DecimalField(max_digits=10, decimal_places=2)
    preco_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    valor = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Faixa de Frete Amazon'
        verbose_name_plural = 'Faixas de Frete Amazon'
        ordering = ['tipo', 'preco_min', 'peso_min']

    def __str__(self):
        teto_peso = self.peso_max if self.peso_max is not None else ('sem peso' if self.peso_min is None else 'sem teto')
        teto_preco = self.preco_max if self.preco_max is not None else 'sem teto'
        return f'{self.get_tipo_display()} | R$ {self.preco_min}-{teto_preco} | peso {self.peso_min or "-"}-{teto_peso}'