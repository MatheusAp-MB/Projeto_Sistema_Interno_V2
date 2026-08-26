# integracao_mercado_livre/management/commands/buscar_dados_sku_completo.py

from django.core.management.base import BaseCommand

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_dados_sku_completo import buscar_dados_sku_completo

EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO = {
    'magazine': EMPRESA_MAGAZINE,
    'samvale': EMPRESA_SAMVALE,
}


class Command(BaseCommand):
    help = (
        'Ponto 05. Busca performance e price_to_win por SKU (via API do Mercado '
        'Livre) e salva dados_completos_por_sku.json, isolado por empresa. '
        'Depende de detalhes_mlbs.json (rode buscar_detalhes antes). Sem --skus, '
        'roda a base inteira, com checkpoint (pode levar 1h30+). Com --skus, '
        'roda só os informados, sem apagar o resto do arquivo já gerado.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--empresa',
            type=str,
            choices=list(EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO.keys()),
            default=None,
            help='magazine ou samvale. Sem esse argumento, roda as 2 empresas.',
        )
        parser.add_argument(
            '--skus',
            type=str,
            default=None,
            help='SKUs separados por vírgula, pra teste pontual. Sem isso, roda todos os SKUs da base.',
        )

    def handle(self, *args, **options):
        argumento = options.get('empresa')
        skus_arg = options.get('skus')
        skus = [s.strip() for s in skus_arg.split(',') if s.strip()] if skus_arg else None

        if argumento is None:
            empresas_a_rodar = [EMPRESA_MAGAZINE, EMPRESA_SAMVALE]
        else:
            empresas_a_rodar = [EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO[argumento]]

        for empresa in empresas_a_rodar:
            definir_empresa_ativa(empresa)
            self.stdout.write(f'\nBuscando dados completos por SKU — {empresa}...')
            buscar_dados_sku_completo(empresa, skus=skus)