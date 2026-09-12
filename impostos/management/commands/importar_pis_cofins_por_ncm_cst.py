# impostos/management/commands/importar_pis_cofins_por_ncm_cst.py

from core.management.commands._base_empresa import ComandoComEmpresa
from impostos.funcoes_auxiliares.importacao_pis_cofins_ncm_cst import importar_pis_cofins_por_ncm_cst


class Command(ComandoComEmpresa):
    help = (
        'Lê a planilha Busca Legal, agrupa por NCM+CST e grava em PisCofinsNcmCst — '
        'rejeita e informa (sem gravar) qualquer grupo com divergência de PIS/COFINS entre seus EANs, '
        'e avisa (sem bloquear) sobre NCMs que aparecem com mais de 1 CST.'
    )

    def adicionar_argumentos(self, parser):
        parser.add_argument(
            '--caminho',
            default=None,
            help='Caminho da planilha, pra testar com um arquivo diferente do oficial da empresa.',
        )

    def handle(self, *args, **options):
        importar_pis_cofins_por_ncm_cst(self.stdout, self.style, caminho_planilha=options['caminho'])