from django.db import models


class FreteMagalu(models.Model):
    # * [EXPLICAÇÃO] → Frete do Magalu é peso × faixa de reputação — NUNCA
    #                  peso × preço como o ML. Confirmado na planilha (aba
    #                  "Magalu"): 3 colunas de valor (baixa/média/alta
    #                  reputação), sem nenhuma faixa de preço. peso_max
    #                  nullable = última faixa aberta ("Acima de 200kg").

    peso_min = models.DecimalField(max_digits=8, decimal_places=3)
    peso_max = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)

    valor_baixa = models.DecimalField(max_digits=8, decimal_places=2)
    valor_media = models.DecimalField(max_digits=8, decimal_places=2)
    valor_alta = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = 'Faixa de Frete Magalu'
        verbose_name_plural = 'Faixas de Frete Magalu'
        ordering = ['peso_min']

    def __str__(self):
        teto = self.peso_max if self.peso_max is not None else 'sem teto'
        return f'{self.peso_min}-{teto}kg'

    # Função Objetivo: Devolve o valor de frete certo pra faixa de reputação atual.
    def valor_para_reputacao(self, faixa_reputacao):
        from magalu.models import ConfiguracaoMagalu
        mapa = {
            ConfiguracaoMagalu.FaixaReputacao.BAIXA: self.valor_baixa,
            ConfiguracaoMagalu.FaixaReputacao.MEDIA: self.valor_media,
            ConfiguracaoMagalu.FaixaReputacao.ALTA: self.valor_alta,
        }
        return mapa[faixa_reputacao]