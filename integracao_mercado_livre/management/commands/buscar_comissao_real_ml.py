# integracao_mercado_livre/management/commands/buscar_comissao_real_ml.py

from django.core.management.base import BaseCommand, CommandError

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from integracao_mercado_livre.servicos.buscar_comissao_real_ml import buscar_comissao_real_ml

EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO = {
    'magazine': EMPRESA_MAGAZINE,
    'samvale': EMPRESA_SAMVALE,
}


class Command(BaseCommand):
    help = (
        'Busca a Comissão Real de cada MLB (via API do Mercado Livre — listing_prices) e '
        'grava em VariacaoAnuncioMercadoLivre.comissao_real_*. Granularidade em 3 níveis: '
        'universal (default, só variações relevantes pra precificação hoje), por produto '
        '(--produto <sku>) ou por MLB (--mlb <mlb>). Não mexe em GradePrecificacaoML.'
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
            '--produto',
            type=str,
            default=None,
            help='SKU de 1 produto específico — atualiza todos os MLBs (Clássico e Premium) dele. '
                 'Não pode ser usado junto com --mlb.',
        )
        parser.add_argument(
            '--mlb',
            type=str,
            default=None,
            help='1 MLB específico — atualiza só as variações daquele anúncio. '
                 'Não pode ser usado junto com --produto.',
        )

    def handle(self, *args, **options):
        argumento_empresa = options.get('empresa')
        produto_sku = options.get('produto')
        mlb = options.get('mlb')

        if produto_sku and mlb:
            raise CommandError('Use --produto OU --mlb, não os dois juntos.')

        if argumento_empresa is None:
            empresas_a_rodar = [EMPRESA_MAGAZINE, EMPRESA_SAMVALE]
        else:
            empresas_a_rodar = [EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO[argumento_empresa]]

        for empresa in empresas_a_rodar:
            definir_empresa_ativa(empresa)
            self.stdout.write(f'\nBuscando Comissão Real — {empresa}...')
            buscar_comissao_real_ml(empresa, produto_sku=produto_sku, mlb=mlb)