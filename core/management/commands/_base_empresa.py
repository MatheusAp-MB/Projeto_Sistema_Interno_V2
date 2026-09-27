from django.core.management.base import BaseCommand
from core.empresa import definir_empresa_ativa, EMPRESA_POR_ALIAS_BANCO


class ComandoComEmpresa(BaseCommand):
    """
    Base pra comandos que operam no banco de uma empresa específica.
    Exige --empresa explícito, sem valor padrão — esquecer ou digitar
    errado já é erro na hora, comando nem chega a rodar.

    Valor de --empresa é sempre minúsculo ('magazine'/'samvale') — padrão
    único pra todo comando do sistema (27/09/2026), fonte de verdade em
    core.empresa.EMPRESA_POR_ALIAS_BANCO. options['empresa'] dentro de
    handle() continua cru, exatamente como foi digitado (minúsculo) — quem
    precisar da constante interna (EMPRESA_MAGAZINE/EMPRESA_SAMVALE), por
    exemplo pra repassar pra uma função de serviço que espera esse formato,
    usa self.empresa_ativa (setado abaixo, antes de handle() rodar).
    """

    def add_arguments(self, parser):
        parser.add_argument(
            '--empresa',
            required=True,
            choices=list(EMPRESA_POR_ALIAS_BANCO.keys()),
            help='Empresa cujo banco este comando vai usar (obrigatório): magazine ou samvale.',
        )
        self.adicionar_argumentos(parser)

    def adicionar_argumentos(self, parser):
        # Hook pra subclasses que precisam de argumento extra, sem
        # sobrescrever add_arguments direto (e esquecer de chamar super()).
        pass

    def execute(self, *args, **options):
        self.empresa_ativa = EMPRESA_POR_ALIAS_BANCO[options['empresa']]
        definir_empresa_ativa(self.empresa_ativa)
        return super().execute(*args, **options)