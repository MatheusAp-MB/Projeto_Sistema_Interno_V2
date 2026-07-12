from django.db import models


class RecomendacaoPrecificacao(models.Model):
    # * [EXPLICAÇÃO] → 1 linha por (variação × comportamento) — 3 linhas
    #                  por MLB, uma pra cada comportamento possível.
    #                  Calculado em lote (calcular_recomendacoes_
    #                  precificacao.py), nunca ao vivo numa tela. Guarda
    #                  o RESULTADO já pronto (preço, margem, cenário),
    #                  não uma referência à promoção escolhida — a
    #                  escolha pode ser uma promoção real OU um preço
    #                  calculado na hora (Preço Direto/Atual), que não
    #                  têm registro próprio pra apontar via FK.

    variacao = models.ForeignKey(
        'mercado_livre.VariacaoAnuncioMercadoLivre',
        on_delete=models.CASCADE,
        related_name='recomendacoes'
    )

    comportamento = models.CharField(
        max_length=20,
        choices=[('padrao', 'Padrão (equilíbrio)'),
                 ('busca_lucro', 'Busca-Lucro (maior margem)'),
                 ('disputa', 'Disputa (ganha catálogo a qualquer custo seguro)')],
    )

    tem_escolha = models.BooleanField(default=False)

    cenario_nome = models.CharField(max_length=200, blank=True, null=True)
    cenario_tipo = models.CharField(max_length=30, blank=True, null=True)

    preco_recomendado = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    margem_recomendada = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)

    bucket_nome = models.CharField(max_length=200, blank=True, null=True)
    exige_aprovacao = models.BooleanField(default=False)

    calculado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['variacao', 'comportamento']
        verbose_name = 'Recomendação de Precificação'
        verbose_name_plural = 'Recomendações de Precificação'

    def __str__(self):
        escolha = self.cenario_nome if self.tem_escolha else 'sem recomendação'
        return f'{self.variacao.anuncio.mlb} — {self.get_comportamento_display()}: {escolha}'