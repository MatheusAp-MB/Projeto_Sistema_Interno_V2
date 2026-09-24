# integracao_mercado_livre/management/commands/sincronizar_categorias_ml.py

from django.core.management.base import BaseCommand

from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE, definir_empresa_ativa
from integracao_mercado_livre.servicos.sincronizar_categorias_ml import sincronizar_categorias_ml

EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO = {
    'magazine': EMPRESA_MAGAZINE,
    'samvale': EMPRESA_SAMVALE,
}


class Command(BaseCommand):
    help = (
        'Baixa o dump de categorias do Mercado Livre (GET /sites/MLB/categories/all) e '
        'popula/atualiza CategoriaMercadoLivre. Roda por empresa porque cada empresa tem '
        'seu próprio banco (mesma árvore de categorias, gravada nos 2 bancos).'
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
            '--forcar',
            action='store_true',
            help='Reprocessa mesmo se o MD5 do dump não mudou desde a última carga.',
        )

    def handle(self, *args, **options):
        argumento = options.get('empresa')
        forcar = options.get('forcar', False)

        if argumento is None:
            empresas_a_rodar = [EMPRESA_MAGAZINE, EMPRESA_SAMVALE]
        else:
            empresas_a_rodar = [EMPRESAS_EXECUTAVEIS_POR_ARGUMENTO[argumento]]

        for empresa in empresas_a_rodar:
            definir_empresa_ativa(empresa)
            self.stdout.write(f'\nSincronizando categorias ML — {empresa}...')
            sincronizar_categorias_ml(empresa, forcar=forcar)