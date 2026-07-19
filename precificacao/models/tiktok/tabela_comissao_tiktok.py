from django.db import models


class TabelaComissaoTiktok(models.Model):
    # * [EXPLICAÇÃO] → Confirmada por comunicado oficial do TikTok Shop (12/06/2026,
    #                  vigente a partir de 15/07/2026): 2 faixas, definidas pelo preço
    #                  FINAL calculado (sem desconto de vendedor separado, confirmado
    #                  com o usuário). Estrutura idêntica à TabelaComissaoShopee
    #                  (comissão % + adicional fixo variando por faixa), mantida
    #                  como model PRÓPRIO — decisão explícita do usuário de não
    #                  generalizar ainda.

    preco_min = models.DecimalField(max_digits=10, decimal_places=2)
    preco_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    comissao_percentual = models.DecimalField(max_digits=5, decimal_places=2)
    adicional_fixo = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Faixa de Comissão TikTok Shop'
        verbose_name_plural = 'Faixas de Comissão TikTok Shop'
        ordering = ['preco_min']

    def __str__(self):
        teto = self.preco_max if self.preco_max is not None else 'sem teto'
        return f'R$ {self.preco_min}-{teto} → {self.comissao_percentual}% + R$ {self.adicional_fixo}'