# impostos/models/entrada/icms_st_entrada_produto.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto

from .imposto_com_aliquota import ImpostoComAliquota
from .impostos_e_custos_xml_entrada_produto import ImpostosECustosXMLEntradaProduto


class IcmsStEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='icms_st',
    )

    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    # FCP (Fundo de Combate à Pobreza) vem junto do ICMS ST na API, mas é
    # um adicional separado, com alíquota e valor próprios.
    aliquota_fcp = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    valor_fcp = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = 'ICMS ST de Entrada (XML) do Produto'
        verbose_name_plural = 'ICMS ST de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'ICMS ST — {self.impostos_e_custos}'
