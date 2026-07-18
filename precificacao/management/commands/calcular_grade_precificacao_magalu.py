from django.core.management.base import BaseCommand
from precificacao.funcoes_auxiliares.magalu.calcular_grade_precificacao_magalu import calcular_grade_precificacao_magalu


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação Magalu em lote (4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_magalu(self.stdout, self.style)