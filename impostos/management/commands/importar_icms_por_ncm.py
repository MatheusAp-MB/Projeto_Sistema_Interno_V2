# impostos/management/commands/importar_icms_por_ncm.py

from core.management.commands._base_empresa import ComandoComEmpresa
from impostos.funcoes_auxiliares.importacao_icms_ncm import importar_icms_por_ncm


class Command(ComandoComEmpresa):
    help = (
        'Lê a planilha Busca Legal, agrupa por NCM e grava em IcmsNcmUf — '
        'rejeita e informa (sem gravar) qualquer NCM com divergência entre seus EANs.'
    )

    def adicionar_argumentos(self, parser):
        parser.add_argument(
            '--caminho',
            default=None,
            help='Caminho da planilha, pra testar com um arquivo diferente do oficial da empresa.',
        )

    def handle(self, *args, **options):
        importar_icms_por_ncm(self.stdout, self.style, caminho_planilha=options['caminho'])