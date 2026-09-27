# integracao_mercado_livre/management/commands/sincronizar_categorias_ml.py

from core.management.commands._base_empresa import ComandoComEmpresa
from integracao_mercado_livre.servicos.sincronizar_categorias_ml import sincronizar_categorias_ml


class Command(ComandoComEmpresa):
    help = (
        'Baixa o dump de categorias do Mercado Livre (GET /sites/MLB/categories/all) e '
        'popula/atualiza CategoriaMercadoLivre. Roda por empresa porque cada empresa tem '
        'seu próprio banco (mesma árvore de categorias, gravada nos 2 bancos). '
        'Roda 1 empresa por vez (--empresa=magazine ou --empresa=samvale, obrigatório).'
    )

    def adicionar_argumentos(self, parser):
        parser.add_argument(
            '--forcar',
            action='store_true',
            help='Reprocessa mesmo se o MD5 do dump não mudou desde a última carga.',
        )

    def handle(self, *args, **options):
        forcar = options.get('forcar', False)
        self.stdout.write(f'\nSincronizando categorias ML — {self.empresa_ativa}...')
        sincronizar_categorias_ml(self.empresa_ativa, forcar=forcar)