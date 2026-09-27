# integracao_mercado_livre/management/commands/buscar_comissao_real_ml.py

from django.core.management.base import CommandError

from core.management.commands._base_empresa import ComandoComEmpresa
from integracao_mercado_livre.servicos.buscar_comissao_real_ml import buscar_comissao_real_ml


class Command(ComandoComEmpresa):
    help = (
        'Busca a Comissão Real de cada MLB (via API do Mercado Livre — listing_prices) e '
        'grava em VariacaoAnuncioMercadoLivre.comissao_real_*. Granularidade em 3 níveis: '
        'universal (default, só variações relevantes pra precificação hoje), por produto '
        '(--produto <sku>) ou por MLB (--mlb <mlb>). Não mexe em GradePrecificacaoML. '
        'Roda 1 empresa por vez (--empresa=magazine ou --empresa=samvale, obrigatório).'
    )

    def adicionar_argumentos(self, parser):
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
        produto_sku = options.get('produto')
        mlb = options.get('mlb')

        if produto_sku and mlb:
            raise CommandError('Use --produto OU --mlb, não os dois juntos.')

        self.stdout.write(f'\nBuscando Comissão Real — {self.empresa_ativa}...')
        buscar_comissao_real_ml(self.empresa_ativa, produto_sku=produto_sku, mlb=mlb)