from django.core.management.base import BaseCommand
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import calcular_grade_precificacao_ml


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação ML em lote (todas as combinações Clássico/Premium × margens, por produto e por MLB real)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_ml(self.stdout, self.style)