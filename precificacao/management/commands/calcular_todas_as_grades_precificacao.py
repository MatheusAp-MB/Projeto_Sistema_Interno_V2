# precificacao/management/commands/calcular_todas_as_grades_precificacao.py

# Função Objetivo: Roda os 6 comandos de grade de precificação em
# sequência, pra 1 empresa só — evita ter que rodar 1 por 1 na mão.
# Não substitui os comandos individuais (continuam existindo e podem ser
# rodados sozinhos, ex: recalcular só a grade da Shopee depois de um
# ajuste pontual) — este é só um atalho de conveniência por cima deles.

from django.core.management import call_command

from core.management.commands._base_empresa import ComandoComEmpresa

COMANDOS_DE_GRADE_EM_ORDEM = (
    'calcular_grade_precificacao_ml',
    'calcular_grade_precificacao_tiktok',
    'calcular_grade_precificacao_raia',
    'calcular_grade_precificacao_amazon',
    'calcular_grade_precificacao_magalu',
    'calcular_grade_precificacao_shopee',
)


class Command(ComandoComEmpresa):
    help = 'Recalcula as 6 grades de precificação em sequência, pra 1 empresa (--empresa=MAGAZINE ou --empresa=SAMVALE).'

    def handle(self, *args, **options):
        empresa = options['empresa']

        for nome_comando in COMANDOS_DE_GRADE_EM_ORDEM:
            self.stdout.write(self.style.WARNING(f'\n=== {nome_comando} ==='))
            call_command(nome_comando, empresa=empresa)

        self.stdout.write(self.style.SUCCESS(f'\nTodas as 6 grades de precificação recalculadas — {empresa}.'))