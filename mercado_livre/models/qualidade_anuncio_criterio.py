from django.db import models
from .qualidade_anuncio import QualidadeAnuncio
from .criterio_qualidade import CriterioQualidade


class QualidadeAnuncioCriterio(models.Model):
    class Status(models.TextChoices):
        APROVADO      = 'aprovado', 'Aprovado'
        NAO_APROVADO  = 'nao_aprovado', 'Não aprovado'
        NAO_APLICAVEL = 'nao_aplicavel', 'Não aplicável'

    qualidade = models.ForeignKey(
        QualidadeAnuncio,
        on_delete=models.CASCADE,
        related_name='criterios'
    )
    criterio = models.ForeignKey(
        CriterioQualidade,
        on_delete=models.CASCADE,
        related_name='avaliacoes'
    )

    status        = models.CharField(max_length=20, choices=Status.choices)
    score         = models.IntegerField(blank=True, null=True)
    calculado_em  = models.DateTimeField(blank=True, null=True)
    link_correcao = models.URLField(max_length=500, blank=True, null=True)

    class Meta:
        unique_together = ['qualidade', 'criterio']
        verbose_name        = 'Avaliação de Critério'
        verbose_name_plural  = 'Avaliações de Critério'

    def __str__(self):
        return f'{self.qualidade.anuncio.mlb} — {self.criterio.rule_key}: {self.status}'