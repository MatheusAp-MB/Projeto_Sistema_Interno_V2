# impostos/models/saida/icms_ncm_uf.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto


# ---------------------------------------------------------------------------
# Impostos de SAÍDA (a partir daqui — nada abaixo vem do XML de entrada)
# ---------------------------------------------------------------------------


class IcmsSaidaPorNcmCstOrigemUf(models.Model):
    # Função Objetivo: Alíquota de ICMS de saída de 1 NCM+CST+Origem pra 1
    # UF de destino — 1 linha por combinação NCM+CST+Origem+UF. Espelha o
    # padrão do FreteML (mercado_livre/models/frete_ml.py): tabela
    # normalizada, pivotada só na tela.
    #
    # 13/09/2026 — decisão do vault ("Decisao - Media Ponderada do ICMS
    # Passa a Ser Persistida em Tabela Propria"): a Média Ponderada NÃO é
    # mais calculada em tempo real a partir das 27 linhas daqui — passou a
    # ser persistida em tabela própria, IcmsSaidaMediaPorNcmCstOrigem
    # (1 linha por grupo NCM+CST+Origem, nunca por UF). Esta tabela
    # (IcmsSaidaPorNcmCstOrigemUf) continua sendo a fonte das 27 alíquotas por UF; só a
    # média deixou de ser recalculada aqui.
    #
    # aliquota guarda percentual (ex: 19.42), igual a
    # Produto.icms_saida_sp/icms_saida_media — nunca fração (0.1942).
    #
    # Sem campo de empresa: MAGAZINE e SAMVALE são bancos separados
    # (EmpresaRouter), cada import roda no banco certo sozinho.
    #
    # 13/09/2026 — decisão do vault ("Decisao - Chave de Consolidacao do
    # ICMS por NCM Passa a Incluir CST e Origem da Mercadoria"): NCM
    # sozinho NÃO garante os mesmos 27 valores — CST (regime de
    # tributação, Tabela B) e Origem da Mercadoria (nacional/importado,
    # Tabela A) também definem legitimamente a alíquota dentro de um
    # mesmo NCM (ex: NCM 84248229 tem CST 20 e CST 00 convivendo de forma
    # legítima, cada um com seus próprios 27 valores por UF — não é erro
    # de cadastro). Por isso os dois entram na chave de identidade, junto
    # com NCM e UF.
    #
    # cst: mesma convenção de PisCofinsSaidaPorNcmCst.cst (max_length=4, sem
    # null/blank) — vem preenchido direto da coluna "CST" da própria
    # planilha do Busca Legal, no momento em que a linha é lida.
    #
    # origem_mercadoria_cadastro: SEMPRE a Origem do CADASTRO DO PRODUTO,
    # nunca do XML de entrada — mesmo nome, mesmo max_length e mesma
    # convenção de null/blank de
    # ImpostosECustosXMLEntradaProduto.origem_mercadoria_cadastro. Pode
    # ficar em branco quando o produto ainda não tem essa origem
    # sincronizada no cadastro no momento do import — não é um "0" por
    # acidente.
    ncm = models.CharField(max_length=10)
    uf = models.CharField(max_length=2)
    cst = models.CharField(max_length=4)
    origem_mercadoria_cadastro = models.CharField(max_length=5, null=True, blank=True)
    aliquota = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = 'ICMS de Saída por NCM, CST, Origem e UF'
        verbose_name_plural = 'ICMS de Saída por NCM, CST, Origem e UF'
        unique_together = ['ncm', 'cst', 'origem_mercadoria_cadastro', 'uf']
        ordering = ['ncm', 'cst', 'origem_mercadoria_cadastro', 'uf']

    def __str__(self):
        return (
            f'NCM {self.ncm} + CST {self.cst} + Origem {self.origem_mercadoria_cadastro} — '
            f'{self.uf}: {self.aliquota}%'
        )
