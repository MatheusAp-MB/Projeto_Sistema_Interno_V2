# * [RESUMO] → Comando de seed do sistema. Popula dados iniciais necessários
#              para o sistema funcionar. Cresce incrementalmente — cada
#              função de apoio vive em iniciar_banco_suporte/, agrupada
#              por ser exclusiva deste comando.

from django.core.management.base import BaseCommand
from core.management.commands.iniciar_banco_suporte.popular_marketplaces import popular_marketplaces
from core.management.commands.iniciar_banco_suporte.popular_criterios_qualidade import popular_criterios_qualidade
from core.management.commands.iniciar_banco_suporte.popular_configuracao_operacional import popular_configuracao_operacional
from core.management.commands.iniciar_banco_suporte.popular_configuracao_mercado_livre import popular_configuracao_mercado_livre
from core.management.commands.iniciar_banco_suporte.popular_tabela_comissao_shopee import popular_tabela_comissao_shopee

class Command(BaseCommand):
    help = 'Popula dados iniciais do sistema (seed)'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando seed do banco...\n')
        popular_marketplaces(self.stdout, self.style)
        self.stdout.write('')
        popular_criterios_qualidade(self.stdout, self.style)
        self.stdout.write('')
        popular_configuracao_operacional(self.stdout, self.style)
        self.stdout.write('')
        popular_configuracao_mercado_livre(self.stdout, self.style)
        self.stdout.write('')
        popular_tabela_comissao_shopee(self.stdout, self.style)
        self.stdout.write(self.style.SUCCESS('\nSeed concluído!'))