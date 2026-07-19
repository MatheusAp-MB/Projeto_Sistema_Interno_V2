from django.db import models
from django.core.serializers.json import DjangoJSONEncoder


class GradePrecificacaoShopee(models.Model):
    produto = models.ForeignKey(
        'produtos.Produto', on_delete=models.CASCADE, related_name='grade_precificacao_shopee'
    )

    class MargemGrade(models.TextChoices):
        MINIMA = 'minima', 'Mínima'
        PADRAO = 'padrao', 'Padrão'
        MAXIMA = 'maxima', 'Máxima'
        COMPETICAO = 'competicao', 'Competição'

    margem = models.CharField(max_length=12, choices=MargemGrade.choices)

    preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    margem_percentual_obtida = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    frete_usado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # * [EXPLICAÇÃO] → "Preço De" — só decorativo/vitrine (preço ÷ 0,80),
    #                  usado pra montar o desconto de 20% padrão da loja.
    #                  Nunca entra em nenhuma conta de margem/FIXO.
    preco_de_exibicao = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    detalhamento = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    calculado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['produto', 'margem']
        verbose_name = 'Grade de Precificação Shopee'
        verbose_name_plural = 'Grade de Precificação Shopee'

    def __str__(self):
        return f'{self.produto} — {self.get_margem_display()}'