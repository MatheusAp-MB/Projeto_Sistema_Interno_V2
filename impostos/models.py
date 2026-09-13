# impostos/models.py

# Função Objetivo: Schema das tabelas de impostos — de entrada (1 produto,
# vindas do XML/Cadastro da nota fiscal via Sysemp) e, na seção do fim
# deste arquivo, de saída (ICMS por NCM/UF).
#
# Só o formato das tabelas mora aqui. O resto do domínio vive em arquivos
# próprios, por responsabilidade:
#   descritores_impostos.py                          → o "molde" de cada imposto
#   funcoes_auxiliares/conversao_valores_impostos.py  → valor da nota → valor por unidade
#   funcoes_auxiliares/sincronizacao_impostos_entrada.py → grava o XML no banco
#   funcoes_auxiliares/exibicao_impostos_entrada.py   → monta dado pro modal de Produto
#   funcoes_auxiliares/creditos_fiscais_para_precificacao.py → crédito pronto pra precificação

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


class ImpostosECustosXMLEntradaProduto(models.Model):
    # Função Objetivo: Retrato mais atual dos impostos/custos de 1 produto.
    # 1 linha por produto, sem histórico — cada sincronização sobrescreve
    # a anterior.

    produto = models.OneToOneField(Produto, on_delete=models.CASCADE, related_name='impostos_entrada')

    nr_nf = models.CharField(max_length=20)
    data_entrada_nota = models.DateField(null=True, blank=True)
    emissao = models.DateField(null=True, blank=True)

    # XML e Cadastro lado a lado: o Cadastro serve pra comparar contra o
    # XML e detectar cadastro desatualizado no Sysemp.
    ncm_xml = models.CharField(max_length=20, null=True, blank=True)
    ncm_cadastro = models.CharField(max_length=20, null=True, blank=True)
    cfop_xml = models.CharField(max_length=10, null=True, blank=True)
    cfop_cadastro = models.CharField(max_length=10, null=True, blank=True)

    origem_mercadoria_xml = models.CharField(max_length=5, null=True, blank=True)
    origem_mercadoria_cadastro = models.CharField(max_length=5, null=True, blank=True)

    # Descrição completa (não só o código) — o código sozinho não é
    # legível sem consultar tabela auxiliar à parte.
    descricao_origem_mercadoria_xml = models.CharField(max_length=255, null=True, blank=True)
    descricao_origem_mercadoria_cadastro = models.CharField(max_length=255, null=True, blank=True)

    # Só existem como Cadastro — não têm par XML no domínio real.
    natureza_operacao_cadastro = models.CharField(max_length=255, null=True, blank=True)
    tes_saida_cadastro = models.PositiveIntegerField(null=True, blank=True)

    id_produto_sysemp = models.PositiveIntegerField(null=True, blank=True)
    codigo_auxiliar = models.CharField(max_length=50, null=True, blank=True)
    fornecedor = models.CharField(max_length=255)
    empresa_fantasia = models.CharField(max_length=255, null=True, blank=True)

    custo_total = models.DecimalField(max_digits=12, decimal_places=2)
    quantidade_nota = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    custo_unitario = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = 'Impostos e Custos de Entrada (XML) do Produto'
        verbose_name_plural = 'Impostos e Custos de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'Impostos de Entrada — {self.produto} (NF {self.nr_nf})'


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


class IpiEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='ipi',
    )

    cst_xml = models.CharField(max_length=3)
    cst_cadastro = models.CharField(max_length=3, null=True, blank=True)

    class Meta:
        verbose_name = 'IPI de Entrada (XML) do Produto'
        verbose_name_plural = 'IPI de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'IPI — {self.impostos_e_custos}'


class PisEntradaProduto(ImpostoComAliquota):
    impostos_e_custos = models.OneToOneField(
        ImpostosECustosXMLEntradaProduto, on_delete=models.CASCADE, related_name='pis',
    )

    cst_xml = models.CharField(max_length=3)
    cst_cadastro = models.CharField(max_length=3, null=True, blank=True)
    reducao = models.DecimalField(max_digits=7, decimal_places=4)

    class Meta:
        verbose_name = 'PIS de Entrada (XML) do Produto'
        verbose_name_plural = 'PIS de Entrada (XML) dos Produtos'

    def __str__(self):
        return f'PIS — {self.impostos_e_custos}'


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


# ---------------------------------------------------------------------------
# Impostos de SAÍDA (a partir daqui — nada abaixo vem do XML de entrada)
# ---------------------------------------------------------------------------


class IcmsNcmUf(models.Model):
    # Função Objetivo: Alíquota de ICMS de saída de 1 NCM pra 1 UF de
    # destino — 1 linha por combinação NCM+UF. O NCM garante os mesmos 27
    # valores pra qualquer produto que o tenha (decisão no vault), por isso
    # o dado mora aqui, não em Produto. Espelha o padrão do FreteML
    # (mercado_livre/models/frete_ml.py): tabela normalizada, pivotada só
    # na tela — não guarda "Média Ponderada" nenhuma linha, ela é sempre
    # calculada em tempo real a partir das 27 linhas (SP × 50% + média das
    # outras 26 × 50%).
    #
    # aliquota guarda percentual (ex: 19.42), igual a
    # Produto.icms_saida_sp/icms_saida_media — nunca fração (0.1942).
    #
    # Sem campo de empresa: MAGAZINE e SAMVALE são bancos separados
    # (EmpresaRouter), cada import roda no banco certo sozinho.

    ncm = models.CharField(max_length=10)
    uf = models.CharField(max_length=2)
    aliquota = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = 'ICMS de Saída por NCM e UF'
        verbose_name_plural = 'ICMS de Saída por NCM e UF'
        unique_together = ['ncm', 'uf']
        ordering = ['ncm', 'uf']

    def __str__(self):
        return f'NCM {self.ncm} — {self.uf}: {self.aliquota}%'


class PisCofinsNcmCst(models.Model):
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
    # Diferente de IcmsNcmUf: aqui pis/cofins PODEM ser null — um NCM+CST
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
# IcmsNcmUf/PisCofinsNcmCst (que só criam/atualizam, nunca apagam um NCM(+CST)
# já aceito antes). Aqui, a cada execução de importar_icms_por_ncm /
# importar_pis_cofins_por_ncm_cst, a tabela inteira é apagada e recriada do
# zero com os rejeitados de AGORA. Isso é proposital e obrigatório (garantia
# exigida por Matheus, 13/09/2026): um NCM que deixou de ser rejeitado (a
# planilha foi corrigida) precisa DESAPARECER daqui no exato instante em que
# a próxima rodada roda — senão viraria um "fantasma" contradizendo um NCM
# que já foi corrigido, exatamente o tipo de dado sujo/desatualizado que
# essa camada existe pra impedir.
class IcmsNcmRejeitado(models.Model):
    # Função Objetivo: 1 linha por NCM rejeitado na ÚLTIMA importação de
    # ICMS por NCM — com TODAS as UFs divergentes (não só a 1ª encontrada,
    # corrigido em 13/09/2026 junto com esta camada — ver
    # AgrupadorIcmsPorNcm._validar_ncm em importacao_icms_ncm.py).

    ncm = models.CharField(max_length=10, unique=True)

    # Quantidade de UFs (das 27) que divergem entre os EANs deste NCM —
    # sempre >= 1 (um NCM só aparece aqui se pelo menos 1 UF divergiu).
    qtd_ufs_divergentes = models.PositiveSmallIntegerField()

    # Quantidade de EANs da planilha agrupados sob este NCM nesta rodada —
    # é uma contagem sobre a PLANILHA, não uma nova consulta ao catálogo de
    # Produto (mantém a gravação em 1 única query em lote, sem N+1 por NCM
    # rejeitado — guarantee de eficiência do vault). Nem todo EAN da
    # planilha necessariamente tem Produto correspondente no banco (ver
    # sem_produto_correspondente em ImportadorImpostosSaida) — o nome não
    # afirma "produtos", só o que é literalmente contável aqui.
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
        ordering = ['-qtd_eans_no_grupo', 'ncm']

    def __str__(self):
        return (
            f'NCM {self.ncm} — rejeitado em {self.qtd_ufs_divergentes} UF(s), '
            f'{self.qtd_eans_no_grupo} EAN(s) no grupo'
        )


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