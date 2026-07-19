from django.db import models


class TabelaComissaoShopee(models.Model):
    # * [EXPLICAÇÃO] → Comissão CNPJ, confirmada por print oficial da
    #                  Shopee (18/07). Comissão e adicional fixo variam
    #                  JUNTOS por faixa de preço — diferente de todos os
    #                  outros marketplaces já construídos (ML/Magalu/Raia
    #                  têm comissão flat ou por tipo, nunca por preço).
    #                  Subsídio Pix (5-8%) NÃO entra aqui — confirmado
    #                  que não afeta a margem do vendedor.

    preco_min = models.DecimalField(max_digits=10, decimal_places=2)
    preco_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    comissao_percentual = models.DecimalField(max_digits=5, decimal_places=2)
    adicional_fixo = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Faixa de Comissão Shopee'
        verbose_name_plural = 'Faixas de Comissão Shopee'
        ordering = ['preco_min']

    def __str__(self):
        teto = self.preco_max if self.preco_max is not None else 'sem teto'
        return f'R$ {self.preco_min}-{teto} → {self.comissao_percentual}% + R$ {self.adicional_fixo}'