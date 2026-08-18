from core.management.commands._base_empresa import ComandoComEmpresa
from precificacao.funcoes_auxiliares.amazon.calcular_grade_precificacao_amazon import calcular_grade_precificacao_amazon


class Command(ComandoComEmpresa):
    help = 'Calcula a Grade de Precificação Amazon em lote (2 tipos × 4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_amazon(self.stdout, self.style)