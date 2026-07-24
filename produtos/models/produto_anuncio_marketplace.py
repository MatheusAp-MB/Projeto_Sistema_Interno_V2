# produtos/models/produto_anuncio_marketplace.py

# Função Objetivo: Marca manualmente se um Produto está anunciado em cada marketplace.
# Explicação em detalhe: "manualmente" de propósito — hoje só o Mercado Livre tem
# rastreamento real de anúncio (AnuncioMercadoLivre); os outros 5 marketplaces só têm
# Grade de Precificação calculada, que é diferente de "está anunciado de verdade".
# Enquanto não existe uma automação melhor, o usuário marca esse checkbox manualmente
# por marketplace — registrado como intenção futura evoluir isso.
from django.db import models
from core.constantes_marketplaces import Marketplace
from .produto import Produto


class ProdutoAnuncioMarketplace(models.Model):
    produto = models.ForeignKey(
        Produto, on_delete=models.CASCADE, related_name='anuncios_marketplace')

    marketplace = models.CharField(max_length=20, choices=Marketplace.choices)

    anunciado = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Produto Anunciado em Marketplace'
        verbose_name_plural = 'Produtos Anunciados em Marketplace'
        unique_together = ['produto', 'marketplace']

    def __str__(self):
        situacao = 'Anunciado' if self.anunciado else 'Não anunciado'
        return f'{self.produto.sku} — {self.get_marketplace_display()}: {situacao}'