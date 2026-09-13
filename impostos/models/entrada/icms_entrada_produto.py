# impostos/models/entrada/icms_entrada_produto.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto

from .imposto_com_aliquota import ImpostoComAliquota
from .impostos_e_custos_xml_entrada_produto import ImpostosECustosXMLEntradaProduto


class IcmsEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms',
    )

    # CharField, não inteiro: CST é código, não número (perderia zero à
    # esquerda). max_length=3 porque fornecedor do Simples Nacional usa
    # CSOSN (3 dígitos, ex: "102") em vez do CST comum (2 dígitos).
    cst_xml = models.CharField(max_length=3)
    cst_cadastro = models.CharField(max_length=3, null=True, blank=True)
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'ICMS de Entrada (XML) do Produto'
        verbose_name_plural = 'ICMS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'ICMS — {self.impostos_e_custos}'
