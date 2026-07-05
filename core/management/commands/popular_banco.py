# * [RESUMO] → Comando de importação de dados reais e variáveis do sistema.
#              Diferente de iniciar_banco (seed fixo), este importa dado
#              que muda com o tempo — vem de arquivos gerados pela API.
#              Cresce incrementalmente, mesma filosofia do iniciar_banco:
#              cada import vive em popular_banco_suporte/, agrupado por
#              ser exclusivo deste comando.

from pathlib import Path
from django.core.management.base import BaseCommand
from core.management.commands.popular_banco_suporte.importar_produtos_ml import importar_produtos_ml
from core.management.commands.popular_banco_suporte.importar_anuncios_ml import importar_anuncios_ml

CAMINHO_DETALHES_MLBS = Path('Arquivos_API/detalhes_mlbs.json')


class Command(BaseCommand):
    help = 'Popula o banco com dados reais vindos da API (via arquivos)'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando importação de dados reais...\n')
        importar_produtos_ml(self.stdout, self.style, CAMINHO_DETALHES_MLBS)
        self.stdout.write('')
        importar_anuncios_ml(self.stdout, self.style, CAMINHO_DETALHES_MLBS)
        self.stdout.write(self.style.SUCCESS('\nImportação concluída!'))


CAMINHO_DETALHES_MLBS = Path('Arquivos_API/detalhes_mlbs.json')
