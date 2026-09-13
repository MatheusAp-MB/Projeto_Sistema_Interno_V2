# validar_impostos_saida.py
#
# Função Objetivo: Valida, sem gravar nada, se os 4 campos fiscais de saída
# vindos de tabela (icms_saida_sp, icms_saida_media, pis_percentual,
# cofins_percentual) em Produto batem com o que IcmsNcmUf/PisCofinsNcmCst
# diriam agora — e, pros produtos que ficaram sem dado validado, classifica
# o motivo exato (sem NCM / NCM rejeitado na validação / NCM nunca
# importado / sem CST / NCM+CST rejeitado ou nunca importado). Roda pras 2
# empresas, 1 execução só. Reaproveita a mesma lógica de busca do
# ImportadorImpostosSaida — não reimplementa nada.

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from impostos.funcoes_auxiliares.importacao_icms_ncm import agrupar_icms_por_ncm
from impostos.funcoes_auxiliares.importacao_pis_cofins_ncm_cst import agrupar_pis_cofins_por_ncm_cst
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA, ImportadorImpostosSaida, _normalizar_chave_para_busca,
)
from produtos.models import Produto

MAXIMO_EXEMPLOS = 15


def validar_empresa(empresa):
    definir_empresa_ativa(empresa)
    print(f'\n{"=" * 70}\n[VALIDAÇÃO — {empresa}]\n{"=" * 70}')

    caminho_planilha = CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA[empresa]

    # Mesmas tabelas normalizadas que a rodada real usou.
    importador = ImportadorImpostosSaida(caminho_planilha=caminho_planilha)
    importador.carregar_tabelas_normalizadas()

    # NCMs/NCM+CST rejeitados na validação da planilha atual — pra
    # classificar exatamente por que 1 produto ficou sem dado.
    ncms_rejeitados_icms = {r.ncm for r in agrupar_icms_por_ncm(caminho_planilha).rejeitados}
    ncms_cst_rejeitados_pis_cofins = {
        (r.ncm, r.cst) for r in agrupar_pis_cofins_por_ncm_cst(caminho_planilha).rejeitados
    }

    mismatches = {'icms_saida_sp': [], 'icms_saida_media': [], 'pis_percentual': [], 'cofins_percentual': []}
    motivos_sem_dado = {
        'sem_ncm': [], 'ncm_rejeitado_icms': [], 'ncm_nunca_importado_icms': [],
        'sem_cst': [], 'ncm_cst_rejeitado_pis_cofins': [], 'ncm_cst_nunca_importado_pis_cofins': [],
    }

    produtos = Produto.objects.only(
        'id', 'ean', 'ncm', 'cst_saida',
        'icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual',
    )

    total = 0
    for produto in produtos:
        total += 1
        campos_esperados = importador._calcular_campos_por_tabela(produto, produto.cst_saida)

        for campo in ('icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual'):
            if campo in campos_esperados and campos_esperados[campo] != getattr(produto, campo):
                mismatches[campo].append((produto.ean, getattr(produto, campo), campos_esperados[campo]))

        ncm_norm = _normalizar_chave_para_busca(produto.ncm)
        if 'icms_saida_sp' not in campos_esperados:
            if ncm_norm is None:
                motivos_sem_dado['sem_ncm'].append(produto.ean)
            elif ncm_norm in ncms_rejeitados_icms:
                motivos_sem_dado['ncm_rejeitado_icms'].append((produto.ean, produto.ncm))
            elif ncm_norm not in importador.icms_por_ncm:
                motivos_sem_dado['ncm_nunca_importado_icms'].append((produto.ean, produto.ncm))

        if 'pis_percentual' not in campos_esperados:
            cst_norm = _normalizar_chave_para_busca(produto.cst_saida)
            if cst_norm is None:
                motivos_sem_dado['sem_cst'].append(produto.ean)
            elif ncm_norm and (ncm_norm, cst_norm) in ncms_cst_rejeitados_pis_cofins:
                motivos_sem_dado['ncm_cst_rejeitado_pis_cofins'].append((produto.ean, produto.ncm, produto.cst_saida))
            elif ncm_norm:
                motivos_sem_dado['ncm_cst_nunca_importado_pis_cofins'].append(
                    (produto.ean, produto.ncm, produto.cst_saida)
                )

    print(f'\nProdutos verificados: {total}')

    print('\n--- DIVERGÊNCIAS (valor gravado != valor que a tabela diria agora) ---')
    algum_mismatch = False
    for campo, lista in mismatches.items():
        if lista:
            algum_mismatch = True
            print(f'\n{campo}: {len(lista)} divergência(s)')
            for ean, gravado, esperado in lista[:MAXIMO_EXEMPLOS]:
                print(f'    EAN {ean}: gravado={gravado}  tabela diria={esperado}')
    if not algum_mismatch:
        print('Nenhuma — tudo que está gravado bate com o que as tabelas diriam agora.')

    print('\n--- MOTIVO DE QUEM FICOU SEM DADO VALIDADO ---')
    for motivo, lista in motivos_sem_dado.items():
        if not lista:
            continue
        print(f'\n{motivo}: {len(lista)}')
        for item in lista[:MAXIMO_EXEMPLOS]:
            print(f'    {item}')
        if len(lista) > MAXIMO_EXEMPLOS:
            print(f'    ... e mais {len(lista) - MAXIMO_EXEMPLOS}')


for empresa_atual in (EMPRESA_MAGAZINE, EMPRESA_SAMVALE):
    validar_empresa(empresa_atual)