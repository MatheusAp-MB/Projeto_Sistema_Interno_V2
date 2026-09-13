# truncar_icms_ncm.py
#
# Função Objetivo: Esvazia IcmsNcmUf e IcmsNcmRejeitado nas 2 empresas —
# passo único, manual, antes do 1º import real depois da mudança de chave
# (NCM+CST+Origem). Necessário porque as linhas que já existiam antes da
# migration ficaram com cst='' (valor de preenchimento da própria
# migration, nunca um CST real) — com a chave nova, essas linhas nunca
# seriam encontradas nem sobrescritas pelo import, e virariam registros
# "fantasma" ao lado dos novos, corretos. Rodar 1 única vez, à mão, nunca
# como parte de um comando de rotina.

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from core.empresa import definir_empresa_ativa, EMPRESA_MAGAZINE, EMPRESA_SAMVALE
from impostos.models import IcmsNcmRejeitado, IcmsNcmUf


def truncar_empresa(empresa):
    definir_empresa_ativa(empresa)

    qtd_uf = IcmsNcmUf.objects.count()
    qtd_rejeitado = IcmsNcmRejeitado.objects.count()

    IcmsNcmUf.objects.all().delete()
    IcmsNcmRejeitado.objects.all().delete()

    print(f'[{empresa}] IcmsNcmUf: {qtd_uf} linha(s) apagada(s). IcmsNcmRejeitado: {qtd_rejeitado} linha(s) apagada(s).')


for empresa_atual in (EMPRESA_MAGAZINE, EMPRESA_SAMVALE):
    truncar_empresa(empresa_atual)

print('\nPronto — as 2 tabelas estão vazias nas 2 empresas.')