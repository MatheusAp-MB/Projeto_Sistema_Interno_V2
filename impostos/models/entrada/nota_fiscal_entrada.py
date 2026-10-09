# impostos/models/entrada/nota_fiscal_entrada.py

from __future__ import annotations

from django.db import models


class NotaFiscalEntrada(models.Model):
    # Função Objetivo: Cabeçalho de 1 nota fiscal de entrada INTEIRA, como veio
    # do manifesto do Sysemp — base do "espelho da NF" (botão "Ver NF" na grade
    # de precificação).
    #
    # Diferente de ImpostosECustosXMLEntradaProduto (1 linha por PRODUTO, só a
    # parte da nota que interessa àquele produto), aqui 1 linha = 1 NOTA, com
    # TODOS os itens dela em ItemNotaFiscalEntrada — inclusive os de produtos que
    # não usam esta nota como base. Sempre sobrescreve (sem histórico), mesma
    # filosofia do retrato por produto.

    # * [EXPLICAÇÃO] → A chave de acesso é o único identificador realmente único
    #                  da nota — o número da NF sozinho pode repetir entre
    #                  fornecedores diferentes. max_length=60 (a chave real tem
    #                  44 dígitos) deixa folga pra chave curta de teste.
    chave_acesso = models.CharField(max_length=60, unique=True)

    numero_nf = models.CharField(max_length=20)
    fornecedor = models.CharField(max_length=255)
    empresa_fantasia = models.CharField(max_length=255, null=True, blank=True)
    emissao = models.DateField(null=True, blank=True)
    data_entrada_nota = models.DateField(null=True, blank=True)

    # Quando este espelho foi gravado/atualizado pela última vez no sistema —
    # mostrado no espelho pro usuário saber quão fresco é o dado.
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Nota Fiscal de Entrada (espelho)'
        verbose_name_plural = 'Notas Fiscais de Entrada (espelho)'

    def __str__(self):
        return f'NF {self.numero_nf} — {self.fornecedor}'
