from core.management.commands._base_empresa import ComandoComEmpresa
from precificacao.funcoes_auxiliares.tiktok.calcular_grade_precificacao_tiktok import calcular_grade_precificacao_tiktok


class Command(ComandoComEmpresa):
    help = 'Calcula a Grade de Precificação TikTok Shop em lote (2 tipos × 4 margens, por produto)'

    def handle(self, *args, **options):
        calcular_grade_precificacao_tiktok(self.stdout, self.style)