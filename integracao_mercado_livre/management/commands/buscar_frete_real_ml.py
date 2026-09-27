# integracao_mercado_livre/management/commands/buscar_frete_real_ml.py

from core.management.commands._base_empresa import ComandoComEmpresa
from integracao_mercado_livre.servicos.buscar_frete_real_ml import buscar_frete_real_ml


class Command(ComandoComEmpresa):
    help = (
        'Busca o frete real de cada MLB (via API do Mercado Livre) e grava em '
        'VariacaoAnuncioMercadoLivre.frete_real, pra cada variação que aparece '
        'em pelo menos 1 linha de GradePrecificacaoML. Não mexe em GradePrecificacaoML. '
        'Roda 1 empresa por vez (--empresa=magazine ou --empresa=samvale, obrigatório).'
    )

    def handle(self, *args, **options):
        self.stdout.write(f'\nBuscando frete real — {self.empresa_ativa}...')
        buscar_frete_real_ml(self.empresa_ativa)