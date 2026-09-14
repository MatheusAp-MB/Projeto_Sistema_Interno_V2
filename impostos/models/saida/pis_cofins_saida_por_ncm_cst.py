# impostos/models/saida/pis_cofins_ncm_cst.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto


class PisCofinsSaidaPorNcmCst(models.Model):
    # Função Objetivo: PIS e COFINS de saída de 1 NCM + CST — 1 linha por
    # combinação NCM+CST. Diferente do ICMS (que é função só de NCM), PIS e
    # COFINS só bateram 100% (0 divergência, nas 2 empresas) quando
    # agrupados por NCM + CST juntos — ver Descoberta no vault
    # ("PIS e COFINS São Função de NCM + CST..."). CST sozinho NÃO é função
    # do NCM (por isso não dá pra separar CST como uma 3ª coluna qualquer:
    # ele é parte da chave, junto com o NCM).
    #
    # pis/cofins guardam percentual (ex: 1.65), igual a
    # Produto.pis_percentual/cofins_percentual — nunca fração (0.0165).
    #
    # Diferente de IcmsSaidaPorNcmCstOrigemUf: aqui pis/cofins PODEM ser null — um NCM+CST
    # monofásico (ex: combustível) tem PIS/COFINS genuinamente em branco
    # na planilha, e não existe "outra UF" pra essa linha representar em
    # vez disso (a chave já é só 1 linha por NCM+CST). Em branco continua
    # em branco, nunca vira 0% por acidente.
    #
    # Sem campo de empresa: MAGAZINE e SAMVALE são bancos separados
    # (EmpresaRouter), cada import roda no banco certo sozinho.

    ncm = models.CharField(max_length=10)
    cst = models.CharField(max_length=4)
    pis = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    cofins = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = 'PIS/COFINS de Saída por NCM e CST'
        verbose_name_plural = 'PIS/COFINS de Saída por NCM e CST'
        unique_together = ['ncm', 'cst']
        ordering = ['ncm', 'cst']

    def __str__(self):
        pis_exibido = f'{self.pis}%' if self.pis is not None else 'em branco'
        cofins_exibido = f'{self.cofins}%' if self.cofins is not None else 'em branco'
        return f'NCM {self.ncm} + CST {self.cst}: PIS {pis_exibido}, COFINS {cofins_exibido}'
