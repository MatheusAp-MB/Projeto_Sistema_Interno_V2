from django.db import models


class FreteTiktok(models.Model):
    # * [EXPLICAÇÃO] → Peso × faixa, sem faixa de reputação (diferente do Magalu) —
    #                  confirmado usar a MÉDIA por faixa de peso, ignorando a
    #                  variação por região do comprador (nenhum outro marketplace
    #                  nosso considera isso). 5 faixas, valores médios da aba
    #                  dedicada "Tik Tok" da planilha (9 zonas de destino
    #                  simplificadas numa média só).

    peso_min = models.DecimalField(max_digits=8, decimal_places=3)
    peso_max = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    valor = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Faixa de Frete TikTok Shop'
        verbose_name_plural = 'Faixas de Frete TikTok Shop'
        ordering = ['peso_min']

    def __str__(self):
        teto = self.peso_max if self.peso_max is not None else 'sem teto'
        return f'{self.peso_min}-{teto}kg → R$ {self.valor}'