# core/constantes_marketplaces.py

# Função Objetivo: Lista canônica dos 6 marketplaces reais, pra uso em campo de choices.
# Explicação em detalhe: usado por qualquer model que precise de um campo "marketplace"
# como FK simplificada (ex: CodigoAssociadoProduto, ProdutoAnuncioMarketplace) — nasce
# aqui em core porque já tem 2 usos reais simultâneos desde o primeiro dia.
from django.db import models


class Marketplace(models.TextChoices):
    MERCADO_LIVRE = 'mercado_livre', 'Mercado Livre'
    MAGALU = 'magalu', 'Magalu'
    RAIA = 'raia', 'Raia'
    SHOPEE = 'shopee', 'Shopee'
    TIKTOK = 'tiktok', 'TikTok Shop'
    AMAZON = 'amazon', 'Amazon'