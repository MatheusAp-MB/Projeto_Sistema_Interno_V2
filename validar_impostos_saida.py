# validar_impostos_saida.py
#
# Função Objetivo: Valida, sem gravar nada, se os 4 campos fiscais de saída
# vindos de tabela (icms_saida_sp, icms_saida_media, pis_percentual,
# cofins_percentual) em Produto batem com o que IcmsNcmUf/PisCofinsNcmCst
# diriam agora — e, pros produtos que ficaram sem dado validado, classifica
# o motivo exato usando o ÚNICO classificador de motivo do sistema
# (ClassificadorMotivoFiscal, Camada B da auditoria fiscal — ver Descoberta
# no vault, 13/09/2026). Roda pras 2 empresas, 1 execução só. Reaproveita a
# mesma lógica de busca do ImportadorImpostosSaida — não reimplementa nada.
#
# Correção de 13/09/2026: antes, este script relia a planilha Excel de novo
# (agrupar_icms_por_ncm/agrupar_pis_cofins_por_ncm_cst) só pra descobrir
# quais NCMs estavam rejeitados — 2 leituras de arquivo redundantes, e a
# lógica de classificação vivia só aqui, duplicada se outra tela um dia
# precisasse do mesmo motivo. Agora consulta só o banco (IcmsNcmRejeitado/
# PisCofinsNcmCstRejeitado, gravados pela última importação real) através
# do classificador — mesma fonte que a tela de produto (Camada C) e a tela
# de Auditoria Fiscal (Camada D) usam, nunca 2 versões da mesma lógica.

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.core.exceptions import ObjectDoesNotExist

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from impostos.funcoes_auxiliares.motivo_impostos_saida import (
    ClassificadorMotivoFiscal, MOTIVO_ICMS_MEDIA_SEM_COBERTURA_UFS, MOTIVO_SEM_CST, MOTIVO_SEM_NCM,
)
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import (
    CAMINHOS_IMPOSTOS_SAIDA_POR_EMPRESA, ImportadorImpostosSaida,
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

    # 1 instância só, carregada 1 vez — classifica quantos produtos
    # precisar sem repetir query nem reler a planilha (ver motivo_impostos_saida.py).
    classificador = ClassificadorMotivoFiscal()

    mismatches = {'icms_saida_sp': [], 'icms_saida_media': [], 'pis_percentual': [], 'cofins_percentual': []}
    motivos_sem_dado = {
        'sem_ncm': [], 'ncm_rejeitado_icms': [], 'ncm_nunca_importado_icms': [],
        'icms_media_sem_cobertura_ufs': [],
        'sem_cst': [], 'ncm_cst_rejeitado_pis_cofins': [], 'ncm_cst_nunca_importado_pis_cofins': [],
    }

    produtos = Produto.objects.select_related('impostos_entrada').only(
        'id', 'ean', 'ncm', 'cst_saida',
        'icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual',
        'impostos_entrada__origem_mercadoria_cadastro',
    )

    total = 0
    for produto in produtos:
        total += 1

        try:
            origem_produto = produto.impostos_entrada.origem_mercadoria_cadastro
        except ObjectDoesNotExist:
            origem_produto = None

        campos_esperados = importador._calcular_campos_por_tabela(produto, produto.cst_saida, origem_produto)

        for campo in ('icms_saida_sp', 'icms_saida_media', 'pis_percentual', 'cofins_percentual'):
            if campo in campos_esperados and campos_esperados[campo] != getattr(produto, campo):
                mismatches[campo].append((produto.ean, getattr(produto, campo), campos_esperados[campo]))

        if 'icms_saida_sp' not in campos_esperados:
            motivo = classificador.classificar_icms_sp(produto.ncm, produto.cst_saida, origem_produto)
            if motivo is not None:
                # sem_ncm/sem_cst mantêm o formato antigo (só o EAN — não
                # tem NCM nenhum a mais pra mostrar); os outros 2 motivos
                # mostram o NCM junto, igual ao script original.
                if motivo.motivo in (MOTIVO_SEM_NCM, MOTIVO_SEM_CST):
                    motivos_sem_dado[motivo.motivo].append(produto.ean)
                else:
                    motivos_sem_dado[motivo.motivo].append((produto.ean, produto.ncm))

        if 'icms_saida_media' not in campos_esperados:
            motivo = classificador.classificar_icms_media(produto.ncm, produto.cst_saida, origem_produto)
            if motivo is not None and motivo.motivo == MOTIVO_ICMS_MEDIA_SEM_COBERTURA_UFS:
                # Só reporta aqui quando o motivo é ESPECÍFICO da Média
                # (SP presente, cobertura insuficiente nas outras UFs) —
                # os outros motivos (sem NCM/sem CST/rejeitado/nunca
                # importado) já foram contados acima, junto com
                # icms_saida_sp, pra não duplicar o mesmo produto nos 2
                # buckets.
                motivos_sem_dado[motivo.motivo].append((produto.ean, produto.ncm))

        if 'pis_percentual' not in campos_esperados:
            motivo = classificador.classificar_pis_cofins(produto.ncm, produto.cst_saida)
            if motivo is not None:
                # sem_cst mantém o formato antigo (só o EAN); os outros 2
                # motivos mostram NCM + CST junto, igual ao script original.
                if motivo.motivo == MOTIVO_SEM_CST:
                    motivos_sem_dado[motivo.motivo].append(produto.ean)
                else:
                    motivos_sem_dado[motivo.motivo].append((produto.ean, produto.ncm, produto.cst_saida))

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