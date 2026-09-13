# impostos/models/entrada/cofins_entrada_produto.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto

from .imposto_com_aliquota import ImpostoComAliquota
from .impostos_e_custos_xml_entrada_produto import ImpostosECustosXMLEntradaProduto


class CofinsEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='cofins',
    )

    cst_xml = models.CharField(max_length=3)
    cst_cadastro = models.CharField(max_length=3, null=True, blank=True)
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'COFINS de Entrada (XML) do Produto'
        verbose_name_plural = 'COFINS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'COFINS — {self.impostos_e_custos}'
