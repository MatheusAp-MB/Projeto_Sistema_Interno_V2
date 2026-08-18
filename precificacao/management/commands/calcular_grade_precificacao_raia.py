from core.management.commands._base_empresa import ComandoComEmpresa
from precificacao.funcoes_auxiliares.raia.calcular_grade_precificacao_raia import calcular_grade_precificacao_raia


class Command(ComandoComEmpresa):
    help = 'Calcula a Grade de Precificação Raia em lote (4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_raia(self.stdout, self.style)