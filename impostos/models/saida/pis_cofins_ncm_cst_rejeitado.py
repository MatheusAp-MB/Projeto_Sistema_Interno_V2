# impostos/models/saida/pis_cofins_ncm_cst_rejeitado.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto


class PisCofinsNcmCstRejeitado(models.Model):
    # Função Objetivo: 1 linha por grupo NCM+CST rejeitado na ÚLTIMA
    # importação de PIS/COFINS por NCM+CST — com TODOS os campos
    # divergentes (PIS e/ou COFINS, não só o 1º encontrado, corrigido em
    # 13/09/2026 — ver AgrupadorPisCofinsPorNcmCst._validar_grupo em
    # importacao_pis_cofins_ncm_cst.py). Mesma semântica de substituição
    # total do IcmsNcmRejeitado, ver comentário acima da seção.

    ncm = models.CharField(max_length=10)
    cst = models.CharField(max_length=4)

    qtd_eans_no_grupo = models.PositiveIntegerField()

    # {"PIS": [{"valor": "1.65", "qtd_eans": 10, "eans": [...]}, ...],
    #  "COFINS": [...]} — só as chaves que de fato divergiram (1 ou 2).
    campos_divergentes = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    constatado_em = models.DateTimeField()

    class Meta:
        verbose_name = 'PIS/COFINS de Saída — NCM+CST Rejeitado (Auditoria)'
        verbose_name_plural = 'PIS/COFINS de Saída — NCM+CST Rejeitados (Auditoria)'
        unique_together = ['ncm', 'cst']
        ordering = ['-qtd_eans_no_grupo', 'ncm', 'cst']

    def __str__(self):
        campos = ', '.join(sorted(self.campos_divergentes.keys()))
        return f'NCM {self.ncm} + CST {self.cst} — diverge em {campos}, {self.qtd_eans_no_grupo} EAN(s) no grupo'
