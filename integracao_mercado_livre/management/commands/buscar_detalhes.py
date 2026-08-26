# integracao_mercado_livre/management/commands/buscar_detalhes.py

from django.core.management.base import BaseCommand

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_detalhes import buscar_detalhes

EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO = {
    'magazine': EMPRESA_MAGAZINE,
    'samvale': EMPRESA_SAMVALE,
}


class Command(BaseCommand):
    help = (
        'Busca o detalhe completo de cada MLB (via API do Mercado Livre) e salva '
        'detalhes_mlbs.json, isolado por empresa. Depende de lista_mlbs.json já '
        'existir (rode buscar_mlbs antes).'
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
            self.stdout.write(f'\nBuscando detalhes — {empresa}...')
            buscar_detalhes(empresa)