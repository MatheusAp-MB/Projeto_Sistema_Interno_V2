# precificacao/models/mercado_livre/grade_precificacao_ml.py

# * [RESUMO] → Reescrito em formato LONGO (17/07) — 1 linha por
#              (produto, variação, tipo_anuncio, margem), igual
#              RecomendacaoPrecificacao. Substitui as ~20 colunas
#              prefixadas (classico_padrao_preco, etc.) por campos
#              normais. variacao=None continua sendo o FALLBACK do
#              produto (sem MLB publicado ainda). origem_dimensao
#              guarda de onde DimensoesEfetivas resolveu o cálculo —
#              'variacao_ml' (dado declarado pelo vendedor no ML) ou
#              'produto_erp' (fallback da embalagem do ERP).

from django.db import models
from django.core.serializers.json import DjangoJSONEncoder


class GradePrecificacaoML(models.Model):

    produto = models.ForeignKey(
        'produtos.Produto', on_delete=models.CASCADE, related_name='grade_precificacao_ml'
    )
    variacao = models.ForeignKey(
        'mercado_livre.VariacaoAnuncioMercadoLivre', on_delete=models.CASCADE,
        related_name='grade_precificacao_ml', null=True, blank=True,
    )

    class TipoAnuncioGrade(models.TextChoices):
        CLASSICO = 'classico', 'Clássico'
        PREMIUM = 'premium', 'Premium'

    class MargemGrade(models.TextChoices):
        MINIMA = 'minima', 'Mínima'
        PADRAO = 'padrao', 'Padrão'
        MAXIMA = 'maxima', 'Máxima'
        COMPETICAO = 'competicao', 'Competição'

    tipo_anuncio = models.CharField(max_length=10, choices=TipoAnuncioGrade.choices)
    margem = models.CharField(max_length=12, choices=MargemGrade.choices)

    preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    margem_percentual_obtida = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    frete_usado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    origem_dimensao = models.CharField(
        max_length=15, null=True, blank=True,
        choices=[('variacao_ml', 'Variação ML'), ('produto_erp', 'Produto ERP')],
    )

    detalhamento = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    calculado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['produto', 'variacao', 'tipo_anuncio', 'margem']
        verbose_name = 'Grade de Precificação ML'
        verbose_name_plural = 'Grade de Precificação ML'

    def __str__(self):
        alvo = f'MLB {self.variacao.anuncio.mlb}' if self.variacao else 'fallback (sem MLB)'
        return f'{self.produto} — {alvo} — {self.get_tipo_anuncio_display()} — {self.get_margem_display()}'