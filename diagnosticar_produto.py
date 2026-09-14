# diagnosticar_produto.py
#
# Funcao Objetivo: diagnostico read-only de por que um produto especifico
# esta sem imposto de saida validado - reaproveita a mesma logica de
# rejeicao do importar_icms_saida_por_ncm_cst_origem, sem gravar nada em nenhum banco.

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from impostos.models import IcmsSaidaPorNcmCstOrigemUf
from impostos.funcoes_auxiliares.saida.preenchimento_impostos_saida import CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA
from impostos.funcoes_auxiliares.saida.importacao_icms_ncm import agrupar_icms_por_ncm
from core.empresa import ALIAS_BANCO_POR_EMPRESA

SKU_PROCURADO = 'F7908050719121.001'


def diagnosticar(sku):
    encontrado_em_alguma_empresa = False
    for empresa, alias in ALIAS_BANCO_POR_EMPRESA.items():
        produto = Produto.objects.using(alias).filter(sku=sku).first()
        if not produto:
            print(f'{empresa}: produto nao encontrado com esse SKU.')
            continue
        encontrado_em_alguma_empresa = True
        print(f'\n=== {empresa} - produto encontrado ===')
        print(f'EAN: {produto.ean}  SKU: {produto.sku}  NCM: {produto.ncm}  CST_saida: {produto.cst_saida}')
        print(f'icms_saida_sp: {produto.icms_saida_sp}  icms_saida_media: {produto.icms_saida_media}')
        print(f'pis_percentual: {produto.pis_percentual}  cofins_percentual: {produto.cofins_percentual}')
        linhas_icms_ncm = IcmsSaidaPorNcmCstOrigemUf.objects.using(alias).filter(ncm=produto.ncm).count()
        print(f'Linhas hoje em IcmsSaidaPorNcmCstOrigemUf pra NCM {produto.ncm}: {linhas_icms_ncm}')
        caminho = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]
        resultado = agrupar_icms_por_ncm(caminho)
        rejeicao = next((r for r in resultado.rejeitados if r.ncm == produto.ncm), None)
        if rejeicao:
            print('\n>>> NCM REJEITADO na planilha atual, motivo exato:')
            print(rejeicao)
        elif produto.ncm not in resultado.aceitos:
            print(f'\n>>> NCM {produto.ncm} nem aparece na planilha atual de ICMS por UF (nunca foi importado).')
        else:
            print(f'\n>>> NCM {produto.ncm} esta aceito na planilha atual - se o campo ta vazio mesmo assim, precisa investigar mais.')
    if not encontrado_em_alguma_empresa:
        print('SKU nao encontrado em nenhuma das 2 empresas.')


diagnosticar(SKU_PROCURADO)