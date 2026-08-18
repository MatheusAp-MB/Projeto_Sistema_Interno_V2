from core.management.commands._base_empresa import ComandoComEmpresa
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import calcular_grade_precificacao_ml


class Command(ComandoComEmpresa):
    help = 'Calcula a Grade de Precificação ML em lote (todas as combinações Clássico/Premium × margens, por produto e por MLB real)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_ml(self.stdout, self.style)