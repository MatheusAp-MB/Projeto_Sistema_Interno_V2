from django.core.management.base import BaseCommand
from precificacao.funcoes_auxiliares.tiktok.calcular_grade_precificacao_tiktok import calcular_grade_precificacao_tiktok


class Command(BaseCommand):
    help = 'Calcula a Grade de Precificação TikTok Shop em lote (2 tipos × 4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_tiktok(self.stdout, self.style)