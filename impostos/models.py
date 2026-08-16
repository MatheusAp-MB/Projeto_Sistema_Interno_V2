# impostos/models.py

# Função Objetivo: Schema das tabelas de impostos e custos de entrada de 1
# produto, vindas do XML/Cadastro da nota fiscal (via Sysemp).
#
# Só o formato das tabelas mora aqui. O resto do domínio vive em arquivos
# próprios, por responsabilidade:
#   descritores_impostos.py                          → o "molde" de cada imposto
#   funcoes_auxiliares/conversao_valores_impostos.py  → valor da nota → valor por unidade
#   funcoes_auxiliares/sincronizacao_impostos_entrada.py → grava o XML no banco
#   funcoes_auxiliares/exibicao_impostos_entrada.py   → monta dado pro modal de Produto
#   funcoes_auxiliares/creditos_fiscais_para_precificacao.py → crédito pronto pra precificação

from __future__ import annotations

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