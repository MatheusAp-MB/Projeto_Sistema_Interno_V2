from django.db import models


class QualidadeAnuncio(models.Model):
    variacao = models.OneToOneField(
        'mercado_livre.VariacaoAnuncioMercadoLivre',
        on_delete=models.CASCADE,
        related_name='qualidade'
    )

    score        = models.IntegerField(blank=True, null=True)
    nivel        = models.CharField(max_length=30, blank=True, null=True)
    calculado_em = models.DateTimeField(blank=True, null=True)

    http_status = models.IntegerField(blank=True, null=True)
    erro        = models.TextField(blank=True, null=True)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Qualidade do Anúncio'
        verbose_name_plural  = 'Qualidade dos Anúncios'

    def __str__(self):
        return f'{self.variacao.anuncio.mlb} — score {self.score}'