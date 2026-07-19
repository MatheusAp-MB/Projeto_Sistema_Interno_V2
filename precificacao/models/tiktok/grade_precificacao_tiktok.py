from django.db import models
from django.core.serializers.json import DjangoJSONEncoder


class GradePrecificacaoTiktok(models.Model):
    # * [EXPLICAÇÃO] → Único marketplace fora do ML com "tipo" — Com Afiliado /
    #                  Sem Afiliado, mesmo papel que Clássico/Premium tem no ML
    #                  (2 cenários por produto, não um só). Sem variação (não
    #                  existe MLB no TikTok Shop ainda) — 8 linhas por produto
    #                  (2 tipos × 4 margens), não 4.

    produto = models.ForeignKey(
        'produtos.Produto', on_delete=models.CASCADE, related_name='grade_precificacao_tiktok'
    )

    class TipoAfiliado(models.TextChoices):
        SEM_AFILIADO = 'sem_afiliado', 'Sem Afiliado'
        COM_AFILIADO = 'com_afiliado', 'Com Afiliado'

    tipo = models.CharField(max_length=15, choices=TipoAfiliado.choices)

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
        verbose_name = 'Grade de Precificação TikTok Shop'
        verbose_name_plural = 'Grade de Precificação TikTok Shop'

    def __str__(self):
        return f'{self.produto} — {self.get_tipo_display()} — {self.get_margem_display()}'