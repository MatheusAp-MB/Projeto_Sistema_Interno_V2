from django.db import models


class CriterioQualidade(models.Model):
    class Grupo(models.TextChoices):
        SHORTS       = 'UP_SHORTS', 'Clipes'
        PICTURES     = 'UP_PICTURES', 'Imagens'
        TITLE        = 'UP_TITLE', 'Título'
        GTIN         = 'UP_GTIN', 'Código Universal'
        TECH_SPECS   = 'UP_TECHNICAL_SPECIFICATIONS_MAIN', 'Ficha Técnica'
        STOCK        = 'UP_STOCK_DEPOSITO', 'Estoque'
        AVAILABILITY = 'UP_STOCK_AVAILABILITY_TIME', 'Prazo'
        FREE_SHIP    = 'UP_FREE_SHIPPING', 'Frete Grátis'
        FINANCING    = 'UP_FINANCING', 'Parcelamento'
        PROMOTIONS   = 'UP_PROMOTIONS', 'Promoções'
        PRICE        = 'UP_PRICE', 'Preço'
        FLEX         = 'UP_ME_FLEX_ITEM_OPTIN', 'Flex'
        SIZE_CHART   = 'UP_SIZE_CHART', 'Tabela de Medidas'
        CATALOG      = 'UP_CATALOG', 'Catálogo'
        DESCONHECIDO = 'DESCONHECIDO', 'Desconhecido — critério novo da API'

    rule_key      = models.CharField(max_length=60, unique=True)
    grupo         = models.CharField(max_length=40, choices=Grupo.choices)
    nome          = models.CharField(max_length=150)
    pergunta      = models.CharField(max_length=150)
    como_aprovar  = models.TextField(blank=True, null=True)

    catalogado = models.BooleanField(default=True)

    class Meta:
        verbose_name        = 'Critério de Qualidade'
        verbose_name_plural  = 'Critérios de Qualidade'
        ordering             = ['grupo', 'rule_key']

    def __str__(self):
        return f'{self.rule_key} — {self.nome}'