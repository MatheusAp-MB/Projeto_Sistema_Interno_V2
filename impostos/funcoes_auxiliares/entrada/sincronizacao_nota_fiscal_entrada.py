# impostos/funcoes_auxiliares/entrada/sincronizacao_nota_fiscal_entrada.py

# Função Objetivo: Grava no banco o espelho de 1 nota fiscal de entrada
# INTEIRA (cabeçalho + todos os itens dela), a partir da nota já parseada
# (NotaCompletaXml).
#
# Único ponto de escrita do espelho — sempre sobrescreve o anterior (sem
# histórico), mesma filosofia do retrato por produto
# (sincronizacao_impostos_entrada.py). Independente dele de propósito: o
# retrato guarda só a parte da nota que interessa a 1 produto (e alimenta o
# cálculo); o espelho guarda a nota toda só pra ser mostrada ao usuário.

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from django.db import router, transaction

from impostos.models import ItemNotaFiscalEntrada, NotaFiscalEntrada

if TYPE_CHECKING:
    from integracao_sysemp.servicos.dados_xml_nf import NotaCompletaXml


def gravar_nota_fiscal_completa(nota: 'NotaCompletaXml') -> NotaFiscalEntrada:
    identificacao = nota.identificacao_nf

    emissao = date.fromisoformat(identificacao.data_emissao_nf) if identificacao.data_emissao_nf else None
    data_entrada = date.fromisoformat(identificacao.data_entrada_nf) if identificacao.data_entrada_nf else None

    # * [EXPLICAÇÃO] → Mesmo motivo do retrato por produto (sincronizacao_impostos_entrada.py):
    #                  a transação abre no banco da empresa ativa, não no 'default' —
    #                  senão uma falha no meio dos itens deixaria o cabeçalho da nota
    #                  gravado sem os itens dela.
    banco_da_empresa = router.db_for_write(NotaFiscalEntrada)

    with transaction.atomic(using=banco_da_empresa):
        cabecalho, _ = NotaFiscalEntrada.objects.update_or_create(
            chave_acesso=identificacao.chave_acesso_nf,
            defaults={
                'numero_nf': identificacao.numero_nf,
                'fornecedor': identificacao.fornecedor,
                'empresa_fantasia': identificacao.empresa_fantasia,
                'emissao': emissao,
                'data_entrada_nota': data_entrada,
            },
        )

        for item in nota.itens:
            ItemNotaFiscalEntrada.objects.update_or_create(
                nota=cabecalho,
                numero_item=item.numero_item,
                defaults={
                    'id_produto_sysemp': item.id_produto_sysemp,
                    'nome_produto': item.nome_produto,
                    'codigo_barras': item.codigo_barras,
                    'codigo_auxiliar': item.codigo_auxiliar,
                    'codigo_fabricante': item.codigo_fabricante,
                    'dados_brutos': item.registro_bruto,
                },
            )

        # * [EXPLICAÇÃO] → Espelho é cópia fiel do que a API devolveu agora: se
        #                  a nota veio com menos itens do que já estava
        #                  gravado (reemissão/correção no Sysemp), o item que
        #                  sumiu sai também — senão o espelho mostraria um
        #                  item que a nota atual não tem mais.
        cabecalho.itens.exclude(numero_item__in=[item.numero_item for item in nota.itens]).delete()

    return cabecalho
