from django.db import models


class PromocaoMercadoLivre(models.Model):
    # * [EXPLICAÇÃO] → 1 linha por promoção/oferta disponível pra uma
    #                  variação — um MLB pode ter várias ao mesmo tempo
    #                  (já confirmado com dado real: até 10 numa amostra
    #                  só). Fonte: API de Promoções do ML, importada via
    #                  importar_promocoes_ml.py — nunca lida ao vivo de
    #                  arquivo por nenhuma tela.

    variacao = models.ForeignKey(
        'mercado_livre.VariacaoAnuncioMercadoLivre',
        on_delete=models.CASCADE,
        related_name='promocoes'
    )

    # * [EXPLICAÇÃO] → Chave pra saber "é a mesma promoção de antes, ou
    #                  nova" ao reimportar. SMART/LIGHTNING/DEAL têm 'id'
    #                  ou 'ref_id' na API — PRICE_DISCOUNT não tem
    #                  nenhum dos dois (confirmado com dado real), então
    #                  usa 'PRICE_DISCOUNT' fixo como fallback (só existe
    #                  1 por variação de qualquer forma).
    chave_externa = models.CharField(max_length=100)

    class Tipo(models.TextChoices):
        SMART = 'SMART', 'Smart'
        LIGHTNING = 'LIGHTNING', 'Lightning'
        PRICE_DISCOUNT = 'PRICE_DISCOUNT', 'Price Discount'
        DEAL = 'DEAL', 'Deal'

    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    nome = models.CharField(max_length=200, blank=True, null=True)

    class Status(models.TextChoices):
        ATIVA = 'started', 'Ativa'
        CANDIDATA = 'candidate', 'Candidata'

    status = models.CharField(max_length=20, choices=Status.choices)

    preco_original = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    preco_avaliado = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    meli_percentage = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    seller_percentage = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)

    inicio_vigencia = models.DateTimeField(blank=True, null=True)
    fim_vigencia = models.DateTimeField(blank=True, null=True)

    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['variacao', 'chave_externa']
        verbose_name = 'Promoção Mercado Livre'
        verbose_name_plural = 'Promoções Mercado Livre'

    def __str__(self):
        return f'{self.variacao.anuncio.mlb} — {self.nome or self.tipo}'