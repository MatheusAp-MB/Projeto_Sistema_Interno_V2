# mercado_livre/models/tipo_de_anuncio.py (versão corrigida)

from django.db import models
from django.core.exceptions import ValidationError
from marketplaces.models import Marketplace


class TipoDeAnuncioMercadoLivre(models.Model):
    marketplace = models.ForeignKey(Marketplace, on_delete=models.CASCADE)

    class Status(models.TextChoices):
        ATIVO               = 'active',           'Ativo'
        PAUSADO             = 'paused',            'Pausado'
        FECHADO             = 'closed',            'Encerrado'
        EM_REVISAO          = 'under_review',      'Em revisão'
        DEBITO_PENDENTE     = 'payment_required',  'Débito pendente'
        AGUARDANDO_ATIVACAO = 'not_yet_active',    'Aguardando ativação'

    class TipoAnuncio(models.TextChoices):
        CLASSICO = 'gold_special', 'Clássico'
        PREMIUM  = 'gold_pro',     'Premium'

    class TipoLogistico(models.TextChoices):
        FULL             = 'fulfillment',   'FULL'
        COLETA           = 'cross_docking', 'Coleta'
        AGENCIA          = 'xd_drop_off',   'Agência'
        FLEX_PURO        = 'self_service',  'Flex Puro'
        LEGADO           = 'not_specified', 'Legado'
        CORREIOS         = 'drop_off',      'Correios'
        POR_NOSSA_CONTA  = 'custom',        'Por nossa conta'

    class ClassificacaoCatalogo(models.TextChoices):
        # * [EXPLICAÇÃO] → 3 estados observáveis direto na API, sem depender
        #                  de relação com outro anúncio:
        #                  Simples  → catalog_product_id vazio
        #                  Base     → catalog_product_id preenchido + catalog_listing=False
        #                  Catálogo → catalog_listing=True (a "folha", dentro da página)
        SIMPLES  = 'simples',  'Simples'
        BASE     = 'base',     'Base de Catálogo'
        CATALOGO = 'catalogo', 'Anúncio de Catálogo'

    status                 = models.CharField(max_length=20, choices=Status.choices)
    tipo_anuncio            = models.CharField(max_length=20, choices=TipoAnuncio.choices)
    tipo_logistico          = models.CharField(max_length=20, choices=TipoLogistico.choices)
    classificacao_catalogo  = models.CharField(max_length=10, choices=ClassificacaoCatalogo.choices)
    flex                    = models.BooleanField()

    nome = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        unique_together = [
            'marketplace', 'status', 'tipo_anuncio', 'tipo_logistico',
            'classificacao_catalogo', 'flex'
        ]
        verbose_name        = 'Tipo de Anúncio Mercado Livre'
        verbose_name_plural  = 'Tipos de Anúncio Mercado Livre'

    def clean(self):
        if self.marketplace and self.marketplace.sigla != 'ML':
            raise ValidationError({
                'marketplace': 'TipoDeAnuncioMercadoLivre só pode ser vinculado ao marketplace Mercado Livre.'
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome or (
            f'{self.status} / {self.tipo_anuncio} / {self.tipo_logistico} '
            f'/ {self.classificacao_catalogo} / flex={self.flex}'
        )


    def __str__(self):
        return self.nome or (
            f'{self.status} / {self.tipo_anuncio} / {self.tipo_logistico} '
            f'/ {self.classificacao_catalogo} / flex={self.flex}'
        )