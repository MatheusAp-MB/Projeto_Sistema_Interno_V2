# * [RESUMO] → Comando standalone — chama a mesma função que o
#              popular_banco também chama agora. Continua útil pra
#              recalcular só a Grade, sem rodar o pipeline inteiro.

from django.core.management.base import BaseCommand
from precificacao.funcoes_auxiliares.mercado_livre.calcular_grade_precificacao_ml import (
    calcular_grade_precificacao_ml,
)


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação ML pra todos os produtos (Goal Seek)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_ml(self.stdout, self.style)