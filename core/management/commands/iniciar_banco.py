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
from core.management.commands.iniciar_banco_suporte.popular_tabela_comissao_tiktok import popular_tabela_comissao_tiktok
from core.management.commands.iniciar_banco_suporte.popular_taxa_kg_adicional_amazon import popular_taxa_kg_adicional_amazon
from core.management.commands.iniciar_banco_suporte.popular_regua_fases_agenda_videos import popular_regua_fases_agenda_videos

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
        self.stdout.write('')
        popular_tabela_comissao_tiktok(self.stdout, self.style)
        self.stdout.write('')
        popular_taxa_kg_adicional_amazon(self.stdout, self.style)
        self.stdout.write('')
        popular_regua_fases_agenda_videos(self.stdout, self.style)
        self.stdout.write(self.style.SUCCESS('\nSeed concluído!'))