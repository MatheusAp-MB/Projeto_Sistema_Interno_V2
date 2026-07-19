from django.core.management.base import BaseCommand
from precificacao.funcoes_auxiliares.amazon.calcular_grade_precificacao_amazon import calcular_grade_precificacao_amazon


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação Amazon em lote (2 tipos × 4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_amazon(self.stdout, self.style)