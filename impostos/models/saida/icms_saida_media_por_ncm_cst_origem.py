# impostos/models/saida/icms_saida_media_por_ncm_cst_origem.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto


class IcmsSaidaMediaPorNcmCstOrigem(models.Model):
    # Função Objetivo: Média Ponderada do ICMS de saída de 1 grupo
    # NCM+CST+Origem — 1 ÚNICA linha por grupo, nunca por UF (diferente de
    # IcmsNcmUf, que é 1 linha por UF). 13/09/2026 — decisão do vault
    # ("Decisao - Media Ponderada do ICMS Passa a Ser Persistida em Tabela
    # Propria"): fechada a partir da evidência do próprio mockup aprovado
    # da tela de ICMS por NCM, onde a Média aparece 1 vez por grupo, nunca
    # repetida nas colunas de UF daquele grupo.
    #
    # media_ponderada guarda percentual (ex: 19.42), mesma convenção de
    # IcmsNcmUf.aliquota — nunca fração (0.1942). Fórmula inalterada:
    # SP × 50% + média das outras 26 UFs × 50%
    # (calcular_media_ponderada(), já existente em exibicao_icms_por_ncm.py).
    #
    # Gravação SEMPRE reescrita do zero a cada rodada de
    # importar_icms_por_ncm, nunca comparada com o valor antigo — mesmo
    # padrão de sobrescrita sem comparação que IcmsNcmUf já usa (não é o
    # padrão de substituição total de IcmsNcmRejeitado, que apaga a tabela
    # inteira; aqui é update/create por grupo, igual IcmsNcmUf).
    #
    # cst / origem_mercadoria_cadastro: mesma convenção de IcmsNcmUf (cst
    # sem null/blank; origem_mercadoria_cadastro pode ficar em branco
    # quando o produto ainda não tem essa origem sincronizada no cadastro
    # — não é um "0" por acidente).
    #
    # Sem campo de empresa: MAGAZINE e SAMVALE são bancos separados
    # (EmpresaRouter), cada import roda no banco certo sozinho.

    ncm = models.CharField(max_length=10)
    cst = models.CharField(max_length=4)
    origem_mercadoria_cadastro = models.CharField(max_length=5, null=True, blank=True)
    media_ponderada = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = 'ICMS de Saída — Média Ponderada por NCM, CST e Origem'
        verbose_name_plural = 'ICMS de Saída — Média Ponderada por NCM, CST e Origem'
        unique_together = ['ncm', 'cst', 'origem_mercadoria_cadastro']
        ordering = ['ncm', 'cst', 'origem_mercadoria_cadastro']

    def __str__(self):
        return (
            f'NCM {self.ncm} + CST {self.cst} + Origem {self.origem_mercadoria_cadastro} — '
            f'Média Ponderada: {self.media_ponderada}%'
        )
