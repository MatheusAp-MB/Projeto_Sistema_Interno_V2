# impostos/management/commands/preencher_impostos_saida.py

from core.management.commands._base_empresa import ComandoComEmpresa
from impostos.funcoes_auxiliares.saida.preenchimento_impostos_saida import preencher_impostos_saida


class Command(ComandoComEmpresa):
    help = (
        'Preenche os 5 campos fiscais de saída do Produto: cst_saida vem direto da planilha '
        'Busca Legal (por EAN); icms_saida_sp vem de IcmsNcmUf, icms_saida_media vem de '
        'IcmsSaidaMediaPorNcmCstOrigem (lido direto, nunca recalculado), e pis_percentual/'
        'cofins_percentual vêm de PisCofinsNcmCst (todos por NCM/CST) — fonte única de '
        'verdade, nunca mais direto da planilha.'
    )

    def handle(self, *args, **options):
        preencher_impostos_saida(self.stdout, self.style)