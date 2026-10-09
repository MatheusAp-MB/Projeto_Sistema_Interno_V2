# impostos/models/entrada/item_nota_fiscal_entrada.py

from __future__ import annotations

from django.db import models

from .nota_fiscal_entrada import NotaFiscalEntrada


class ItemNotaFiscalEntrada(models.Model):
    # Função Objetivo: 1 item de uma nota fiscal de entrada, exatamente como a
    # API do Sysemp devolveu — o espelho da NF mostra todos os itens da nota,
    # não só o do produto aberto na grade.

    nota = models.ForeignKey(NotaFiscalEntrada, on_delete=models.CASCADE, related_name='itens')

    # Posição do item dentro da nota (campo "Item" da API) — junto com a nota,
    # identifica o item de forma única.
    numero_item = models.PositiveIntegerField()

    # Colunas só de identificação (pra achar/ordenar/conferir sem abrir o
    # json). Todo o resto — quantidade, custos, NCM, CFOP e os 6 impostos —
    # vem de dados_brutos.
    id_produto_sysemp = models.PositiveIntegerField(null=True, blank=True)
    nome_produto = models.CharField(max_length=500)
    codigo_barras = models.CharField(max_length=50, null=True, blank=True)
    codigo_auxiliar = models.CharField(max_length=50, null=True, blank=True)
    codigo_fabricante = models.CharField(max_length=50, null=True, blank=True)

    # * [EXPLICAÇÃO] → Registro cru do item (a linha da API sem nenhuma
    #                  alteração) — fonte única dos valores. Quem exibe lê
    #                  daqui por DadosXmlNF.a_partir_do_registro, o mesmo
    #                  parse que alimenta o retrato por produto, em vez de
    #                  duplicar ~40 colunas aqui.
    dados_brutos = models.JSONField()

    class Meta:
        ordering = ['numero_item']
        constraints = [
            models.UniqueConstraint(fields=['nota', 'numero_item'], name='item_nf_entrada_unico_por_nota'),
        ]
        verbose_name = 'Item de Nota Fiscal de Entrada (espelho)'
        verbose_name_plural = 'Itens de Nota Fiscal de Entrada (espelho)'

    def __str__(self):
        return f'NF {self.nota.numero_nf} — item {self.numero_item} — {self.nome_produto}'
