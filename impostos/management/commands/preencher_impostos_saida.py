# impostos/management/commands/preencher_impostos_saida.py

from core.management.commands._base_empresa import ComandoComEmpresa
from impostos.funcoes_auxiliares.preenchimento_impostos_saida import preencher_impostos_saida


class Command(ComandoComEmpresa):
    help = (
        'Preenche cst_saida, icms_saida_sp, icms_saida_media, pis_percentual e cofins_percentual '
        'do Produto a partir da planilha Busca Legal.'
    )

    def handle(self, *args, **options):
        preencher_impostos_saida(self.stdout, self.style)