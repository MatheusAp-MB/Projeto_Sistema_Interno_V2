# impostos/models/saida/icms_ncm_rejeitado.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto


# ---------------------------------------------------------------------------
# AUDITORIA FISCAL — motivo de rejeição, persistido (Camada A da auditoria
# fiscal, decidida no vault em 13/09/2026 — ver Descoberta "Auditoria Fiscal
# de Impostos de Saida, Camadas A-D Planejadas").
#
# Até 13/09/2026, o motivo de um NCM (ou NCM+CST) ter sido rejeitado numa
# importação era calculado em memória e só impresso no stdout do comando —
# nunca gravado em lugar nenhum. Resultado: não existia NENHUMA tela nem
# log que explicasse, depois do fato, por que um campo fiscal de saída
# estava em branco (achado real: produto F7908050719121.001, NCM 84244100).
#
# Semântica de SUBSTITUIÇÃO TOTAL a cada rodada — o OPOSTO de
# IcmsSaidaPorNcmCstOrigemUf/PisCofinsSaidaPorNcmCst (que só criam/atualizam, nunca apagam um NCM(+CST)
# já aceito antes). Aqui, a cada execução de importar_icms_por_ncm /
# importar_pis_cofins_por_ncm_cst, a tabela inteira é apagada e recriada do
# zero com os rejeitados de AGORA. Isso é proposital e obrigatório (garantia
# exigida por Matheus, 13/09/2026): um NCM que deixou de ser rejeitado (a
# planilha foi corrigida) precisa DESAPARECER daqui no exato instante em que
# a próxima rodada roda — senão viraria um "fantasma" contradizendo um NCM
# que já foi corrigido, exatamente o tipo de dado sujo/desatualizado que
# essa camada existe pra impedir.
class IcmsSaidaPorNcmCstOrigemRejeitado(models.Model):
    # Função Objetivo: 1 linha por NCM+CST+Origem rejeitado na ÚLTIMA
    # importação de ICMS por NCM — com TODAS as UFs divergentes (não só a
    # 1ª encontrada, corrigido em 13/09/2026 junto com esta camada — ver
    # AgrupadorIcmsPorNcm._validar_ncm em importacao_icms_ncm.py).
    #
    # 13/09/2026 — mesma decisão de IcmsSaidaPorNcmCstOrigemUf: o agrupamento não é mais só
    # por NCM, é por NCM + CST + Origem da Mercadoria (Cadastro). Antes só
    # existia 1 linha de rejeitado por NCM (por isso `ncm` sozinho era
    # `unique=True`) — agora o MESMO NCM pode ter uma combinação aprovada
    # (ex: CST 20, nacional) e outra rejeitada (ex: CST 00, importado) ao
    # mesmo tempo, então a unicidade vira composta (ver unique_together).

    ncm = models.CharField(max_length=10)
    cst = models.CharField(max_length=4)
    origem_mercadoria_cadastro = models.CharField(max_length=5, null=True, blank=True)

    # Quantidade de UFs (das 27) que divergem entre os EANs deste
    # NCM+CST+Origem — sempre >= 1 (um grupo só aparece aqui se pelo menos
    # 1 UF divergiu).
    qtd_ufs_divergentes = models.PositiveSmallIntegerField()

    # Quantidade de EANs da planilha agrupados sob este NCM+CST+Origem
    # nesta rodada — é uma contagem sobre a PLANILHA, não uma nova consulta
    # ao catálogo de Produto (mantém a gravação em 1 única query em lote,
    # sem N+1 por grupo rejeitado — guarantee de eficiência do vault). Nem
    # todo EAN da planilha necessariamente tem Produto correspondente no
    # banco (ver sem_produto_correspondente em ImportadorImpostosSaida) — o
    # nome não afirma "produtos", só o que é literalmente contável aqui.
    qtd_eans_no_grupo = models.PositiveIntegerField()

    # Detalhe COMPLETO, sem truncar (diferente do __str__ de NcmRejeitado,
    # que trunca em 3 exemplos só pro stdout do terminal) — decisão do
    # vault, 13/09/2026: a auditoria não pode esconder exemplo nenhum atrás
    # de um "...". 1 chave JSON por UF divergente:
    #   {"AC": [{"valor": "5.60", "qtd_eans": 42, "eans": [...]},
    #           {"valor": "8.80", "qtd_eans": 2, "eans": [...]}], ...}
    # Um NCM com centenas de EANs por grupo produz, no pior caso realista,
    # poucos KB de JSON (EANs são strings de ~13 dígitos) — muito abaixo de
    # qualquer limite prático do tipo JSON do MySQL (max_allowed_packet,
    # tipicamente dezenas de MB) — decisão em aberto do vault, resolvida
    # aqui: não é problema de tamanho.
    divergencias_por_uf = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    # Capturado 1 ÚNICA vez por execução do comando (timezone.now() chamado
    # 1 vez em importar_icms_por_ncm, nunca por NCM) — todo NCM rejeitado
    # numa mesma rodada compartilha o MESMO instante, mesmo que a gravação
    # em si leve alguns milissegundos linha a linha (garantia do vault).
    constatado_em = models.DateTimeField()

    class Meta:
        verbose_name = 'ICMS de Saída — NCM Rejeitado (Auditoria)'
        verbose_name_plural = 'ICMS de Saída — NCMs Rejeitados (Auditoria)'
        unique_together = ['ncm', 'cst', 'origem_mercadoria_cadastro']
        ordering = ['-qtd_eans_no_grupo', 'ncm', 'cst', 'origem_mercadoria_cadastro']

    def __str__(self):
        return (
            f'NCM {self.ncm} + CST {self.cst} + Origem {self.origem_mercadoria_cadastro} — '
            f'rejeitado em {self.qtd_ufs_divergentes} UF(s), '
            f'{self.qtd_eans_no_grupo} EAN(s) no grupo'
        )
