# impostos/models/entrada/impostos_e_custos_xml_entrada_produto.py

from __future__ import annotations

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from produtos.models import Produto


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
