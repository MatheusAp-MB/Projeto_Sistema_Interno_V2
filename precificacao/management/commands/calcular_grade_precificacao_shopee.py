from django.core.management.base import BaseCommand
from precificacao.funcoes_auxiliares.shopee.calcular_grade_precificacao_shopee import calcular_grade_precificacao_shopee


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação Shopee em lote (4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_shopee(self.stdout, self.style)