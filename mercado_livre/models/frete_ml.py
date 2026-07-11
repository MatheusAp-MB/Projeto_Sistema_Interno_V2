from django.db import models


# ================================================
# FRETE ML
# ================================================

# * [EXPLICAÇÃO] → Cada linha dessa tabela representa UMA célula da matriz
#                  de frete do Mercado Livre. A matriz tem faixas de peso
#                  nas linhas e faixas de preço nas colunas.
#                  Exemplo: peso_min=0.000, peso_max=0.300,
#                  preco_min=0.00, preco_max=79.99, valor=12.50
#                  → produto até 300g vendido até R$79,99 → frete R$12,50

class FreteML(models.Model):

    # Faixa de peso (em kg)
    # * [EXPLICAÇÃO] → peso_max é null na última faixa — significa "acima de X kg"
    peso_min = models.DecimalField(max_digits=8, decimal_places=3)
    peso_max = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)

    # Faixa de preço (em R$)
    # * [EXPLICAÇÃO] → preco_max é null na última faixa — significa "acima de R$ X"
    preco_min = models.DecimalField(max_digits=10, decimal_places=2)
    preco_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Valor do frete para essa combinação de peso + preço
    valor = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'Frete ML'
        verbose_name_plural = 'Fretes ML'
        # * [EXPLICAÇÃO] → Ordena primeiro por peso, depois por preço —
        #                  garante que a tabela sempre apareça na ordem certa.
        ordering = ['peso_min', 'preco_min']

    def __str__(self):
        return f'Peso {self.peso_min}-{self.peso_max}kg | Preço {self.preco_min}-{self.preco_max} → R${self.valor}'