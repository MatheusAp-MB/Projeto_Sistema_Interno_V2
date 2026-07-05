# * [RESUMO] → Model Marketplace — tabela de suporte para roteamento.
#              Não contém regra de negócio nenhuma — isso vive dentro de
#              cada app específico (mercado_livre, shopee, etc.).
#              Serve só para: existir na grid de seleção, e no futuro,
#              habilitar/desabilitar o acesso a um marketplace sem
#              remover código.

from django.db import models


class Marketplace(models.Model):
    nome  = models.CharField(max_length=100)
    sigla = models.CharField(max_length=20, unique=True)
    logo  = models.CharField(max_length=255, blank=True, null=True)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name        = 'Marketplace'
        verbose_name_plural = 'Marketplaces'
        ordering            = ['ordem', 'nome']

    def __str__(self):
        return f'{self.nome} ({self.sigla})'