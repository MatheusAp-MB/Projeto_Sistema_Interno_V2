# teste_verificar_cst_pendente.py
#
# Função Objetivo: Diagnóstico read-only (não grava nada) pra fechar 2
# pontos em aberto da Decisão "Chave de Consolidação do ICMS por NCM Passa
# a Incluir CST e Origem da Mercadoria" (ver vault, 13/09/2026 06:11):
# (1) conferir se os NCMs 84137080/84243010 (MAGAZINE) têm alguma linha
# com CST 60 (ICMS-ST) escondida na planilha real; (2) conferir se os 2
# NCMs rejeitados da SAMVALE (95066200/90192020) também têm CST divergente
# entre os EANs, igual aos 4 já confirmados na MAGAZINE. Reaproveita
# ler_linhas_planilha_impostos_saida (mesma leitura usada pelo import de
# produção) — não reimplementa nada.

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from impostos.funcoes_auxiliares.importacao_icms_ncm import _normalizar_codigo_celula
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA, COLUNA_CST, COLUNA_EAN,
    ler_linhas_planilha_impostos_saida,
)

COLUNA_NCM = 'NCM'


def conferir_ncms(empresa, ncms_alvo):
    definir_empresa_ativa(empresa)
    caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]
    linhas = ler_linhas_planilha_impostos_saida(caminho_planilha)

    print(f'\n{"=" * 70}\n[{empresa}]\n{"=" * 70}')

    for ncm_alvo in ncms_alvo:
        eans_por_cst = {}
        for linha in linhas:
            ncm = _normalizar_codigo_celula(linha.get(COLUNA_NCM))
            if ncm != ncm_alvo:
                continue
            ean = _normalizar_codigo_celula(linha.get(COLUNA_EAN))
            cst = _normalizar_codigo_celula(linha.get(COLUNA_CST))
            eans_por_cst.setdefault(cst, []).append(ean)

        print(f'\nNCM {ncm_alvo}: {sum(len(v) for v in eans_por_cst.values())} EAN(s) encontrados')
        if not eans_por_cst:
            print('  NÃO ENCONTRADO na planilha desta empresa.')
            continue

        for cst, eans in sorted(eans_por_cst.items(), key=lambda item: -len(item[1])):
            cst_exibido = cst if cst is not None else 'em branco'
            print(f'  CST {cst_exibido}: {len(eans)} EAN(s) — {", ".join(eans)}')

        if len(eans_por_cst) > 1:
            print('  >>> CST DIVERGE entre os EANs deste NCM.')
        else:
            print('  >>> CST único entre os EANs deste NCM (sem divergência de CST).')


if __name__ == '__main__':
    print('Conferindo se 84137080/84243010 (MAGAZINE) têm alguma linha com CST 60 (ICMS-ST):')
    conferir_ncms(EMPRESA_MAGAZINE, ['84137080', '84243010'])

    print('\n\nConferindo se os 2 NCMs rejeitados da SAMVALE têm CST divergente entre os EANs:')
    conferir_ncms(EMPRESA_SAMVALE, ['95066200', '90192020'])