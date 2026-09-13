# impostos/models/entrada/imposto_com_aliquota.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto


class ImpostoComAliquota(models.Model):
    # Função Objetivo: Base abstrata com os 3 campos comuns a 5 dos 6
    # impostos (todos menos ICMS Retido, que não tem alíquota).

    base_calculo = models.DecimalField(max_digits=12, decimal_places=2)
    aliquota = models.DecimalField(max_digits=7, decimal_places=4)
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        abstract = True
