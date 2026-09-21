# integracao_mercado_livre/management/commands/buscar_frete_real_ml.py

from django.core.management.base import BaseCommand

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_frete_real_ml import buscar_frete_real_ml

EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO = {
    'magazine': EMPRESA_MAGAZINE,
    'samvale': EMPRESA_SAMVALE,
}


class Command(BaseCommand):
    help = (
        'Busca o frete real de cada MLB (via API do Mercado Livre) e grava em '
        'VariacaoAnuncioMercadoLivre.frete_real, pra cada variação que aparece '
        'em pelo menos 1 linha de GradePrecificacaoML. Não mexe em GradePrecificacaoML.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--empresa',
            type=str,
            choices=list(EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO.keys()),
            default=None,
            help='magazine ou samvale. Sem esse argumento, roda as 2 empresas.',
        )

    def handle(self, *args, **options):
        argumento = options.get('empresa')

        if argumento is None:
            empresas_a_rodar = [EMPRESA_MAGAZINE, EMPRESA_SAMVALE]
        else:
            empresas_a_rodar = [EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO[argumento]]

        for empresa in empresas_a_rodar:
            definir_empresa_ativa(empresa)
            self.stdout.write(f'\nBuscando frete real — {empresa}...')
            buscar_frete_real_ml(empresa)