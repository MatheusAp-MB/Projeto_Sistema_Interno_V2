from django.core.management.base import BaseCommand
from precificacao.funcoes_auxiliares.raia.calcular_grade_precificacao_raia import calcular_grade_precificacao_raia


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação Raia em lote (4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_raia(self.stdout, self.style)