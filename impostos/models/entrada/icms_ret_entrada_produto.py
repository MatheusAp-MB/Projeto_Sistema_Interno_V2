# impostos/models/entrada/icms_ret_entrada_produto.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto

from .impostos_e_custos_xml_entrada_produto import ImpostosECustosXMLEntradaProduto


class IcmsRetEntradaProduto(models.Model):
    # Não herda de ImpostoComAliquota: ICMS Retido nunca teve alíquota nem
    # redução no domínio real, só base e valor.

    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms_ret',
    )
    base_calculo = models.DecimalField(max_digits=12, decimal_places=2)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'ICMS Retido de Entrada (XML) do Produto'
        verbose_name_plural = 'ICMS Retido de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'ICMS Ret — {self.impostos_e_custos}'
