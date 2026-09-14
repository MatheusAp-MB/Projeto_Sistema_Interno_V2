# teste.py
#
# Funcao Objetivo: verifica na mao as 2 funcoes novas da Etapa 6a
# (listar_origens_disponiveis_para_ncm e listar_csts_disponiveis_para_ncm_origem)
# antes de seguir pra 6b/6c - script solto, so leitura, nada grava no banco.
# Apague depois de confirmar; nao faz parte da suite de testes formal
# (impostos/tests/), e um NCM fixo aqui e so um exemplo conhecido, nao uma
# regra geral.

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE
from impostos.funcoes_auxiliares.saida.exibicao_icms_por_ncm import (
    listar_origens_disponiveis_para_ncm, listar_csts_disponiveis_para_ncm_origem,
)

definir_empresa_ativa(EMPRESA_MAGAZINE)

NCM_DE_TESTE = '84248229'  # ja confirmado com 3 grupos: Origem None+CST 00, Origem 2+CST 20, Origem 5+CST 20

print(f'--- Origens disponiveis para NCM {NCM_DE_TESTE} ---')
origens = listar_origens_disponiveis_para_ncm(NCM_DE_TESTE)
print(origens)
if len(origens) == len(set(origens)):
    print(f'OK: {len(origens)} valores, todos distintos.')
else:
    print(f'FALHOU: {len(origens)} valores, mas so {len(set(origens))} distintos - ainda duplicando.')

print()
print(f'--- CSTs disponiveis por Origem, para NCM {NCM_DE_TESTE} ---')
for origem in origens:
    csts = listar_csts_disponiveis_para_ncm_origem(NCM_DE_TESTE, origem)
    print(f'Origem {origem!r}: {csts}')