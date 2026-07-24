# produtos/models/codigo_associado_produto.py

# Função Objetivo: Guarda o código/SKU real que um Produto tem em cada marketplace,
# quando esse código difere do SKU padrão do ERP.
# Explicação em detalhe: caso real de origem — TikTok Shop duplica cada produto em 2
# listagens (Com Afiliado = SKU original; Sem Afiliado = "1" + SKU original), e o
# banco não tinha nenhum lugar pra guardar essa associação (dependia de inferir por
# prefixo "1", frágil — já causou bug real em produção). Tabela nova em vez de campo
# JSON no Produto: permite busca reversa indexada (achar o Produto a partir do código
# da plataforma) e adicionar um marketplace/rótulo novo sem migration.
from django.db import models
from core.constantes_marketplaces import Marketplace
from .produto import Produto


class CodigoAssociadoProduto(models.Model):
    produto = models.ForeignKey(
        Produto, on_delete=models.CASCADE, related_name='codigos_associados')

    marketplace = models.CharField(max_length=20, choices=Marketplace.choices)

    # * [EXPLICAÇÃO] → Rótulo livre (ex: "Com Afiliado", "Sem Afiliado") —
    #                  não é enum fechado porque cada marketplace pode ter
    #                  um motivo diferente de duplicação no futuro.
    rotulo = models.CharField(max_length=50)

    codigo = models.CharField(max_length=50)

    class Meta:
        verbose_name = 'Código Associado de Produto'
        verbose_name_plural = 'Códigos Associados de Produto'
        unique_together = ['produto', 'marketplace', 'rotulo']

    def __str__(self):
        return f'{self.produto.sku} — {self.get_marketplace_display()} ({self.rotulo}): {self.codigo}'