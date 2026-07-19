from django.db import models
from django.core.serializers.json import DjangoJSONEncoder


class GradePrecificacaoAmazon(models.Model):
    # * [EXPLICAÇÃO] → Mesmo padrão do TikTok — "tipo" (DBA/FBA) faz o papel de
    #                  Clássico/Premium do ML. 8 linhas por produto (2 tipos × 4
    #                  margens), sem variação (sem MLB na Amazon ainda).

    produto = models.ForeignKey(
        'produtos.Produto', on_delete=models.CASCADE, related_name='grade_precificacao_amazon'
    )

    tipo = models.CharField(max_length=3, choices=[('dba', 'DBA'), ('fba', 'FBA')])

    class MargemGrade(models.TextChoices):
        MINIMA = 'minima', 'Mínima'
        PADRAO = 'padrao', 'Padrão'
        MAXIMA = 'maxima', 'Máxima'
        COMPETICAO = 'competicao', 'Competição'

    margem = models.CharField(max_length=12, choices=MargemGrade.choices)

    preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    margem_percentual_obtida = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    frete_usado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    detalhamento = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    calculado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['produto', 'tipo', 'margem']
        verbose_name = 'Grade de Precificação Amazon'
        verbose_name_plural = 'Grade de Precificação Amazon'

    def __str__(self):
        return f'{self.produto} — {self.get_tipo_display()} — {self.get_margem_display()}'