from django.core.management.base import BaseCommand
from core.empresa import definir_empresa_ativa, EMPRESAS_VALIDAS


class ComandoComEmpresa(BaseCommand):
    """
    Base pra comandos que operam no banco de uma empresa específica.
    Exige --empresa explícito, sem valor padrão — esquecer ou digitar
    errado já é erro na hora, comando nem chega a rodar.
    """

    def add_arguments(self, parser):
        parser.add_argument(
            '--empresa',
            required=True,
            choices=EMPRESAS_VALIDAS,
            help='Empresa cujo banco este comando vai usar (obrigatório).',
        )
        self.adicionar_argumentos(parser)

    def adicionar_argumentos(self, parser):
        # Hook pra subclasses que precisam de argumento extra, sem
        # sobrescrever add_arguments direto (e esquecer de chamar super()).
        pass

    def execute(self, *args, **options):
        definir_empresa_ativa(options['empresa'])
        return super().execute(*args, **options)