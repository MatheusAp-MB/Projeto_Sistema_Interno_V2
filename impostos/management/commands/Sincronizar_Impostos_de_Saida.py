# impostos/management/commands/Sincronizar_Impostos_de_Saida.py

# Função Objetivo: Roda os 4 comandos de impostos de saída em sequência,
# pra 1 empresa só — evita ter que rodar 1 por 1 na mão. Não substitui os
# comandos individuais (continuam existindo e podem ser rodados sozinhos,
# ex: reimportar só o ICMS depois de um ajuste pontual na planilha) — este
# é só um atalho de conveniência por cima deles, mesmo padrão já usado em
# calcular_todas_as_grades_precificacao.py (precificacao).
#
# Ordem fixa, não paralelizável: a única dependência real do fluxo é o
# passo 4 (preencher_impostos_saida) precisar do cst_saida já gravado pelo
# passo 1 (preencher_CST_produtos) — ver Decisão no vault de 13/09, 18:20.

from django.core.management import call_command

from core.management.commands._base_empresa import ComandoComEmpresa

COMANDOS_DE_IMPOSTOS_SAIDA_EM_ORDEM = (
    'preencher_CST_produtos',
    'importar_icms_por_ncm',
    'importar_pis_cofins_por_ncm_cst',
    'preencher_impostos_saida',
)


class Command(ComandoComEmpresa):
    help = (
        'Roda os 4 comandos de impostos de saída em sequência (CST → ICMS → PIS/COFINS → '
        'Preencher), pra 1 empresa (--empresa=MAGAZINE ou --empresa=SAMVALE).'
    )

    def handle(self, *args, **options):
        empresa = options['empresa']

        for nome_comando in COMANDOS_DE_IMPOSTOS_SAIDA_EM_ORDEM:
            self.stdout.write(self.style.WARNING(f'\n=== {nome_comando} ==='))
            call_command(nome_comando, empresa=empresa)

        self.stdout.write(self.style.SUCCESS(
            f'\nOs 4 comandos de impostos de saída rodados em sequência — {empresa}.'
        ))