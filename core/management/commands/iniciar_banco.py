# * [RESUMO] → Comando de seed do sistema. Popula dados iniciais necessários
#              para o sistema funcionar. Cresce incrementalmente — cada
#              função de apoio vive em iniciar_banco_suporte/, agrupada por
#              ser exclusiva deste comando. Mesmo padrão de lista de etapas
#              usado em popular_banco.py — os 2 comandos resolvem o mesmo
#              tipo de problema (rodar N passos nomeados em sequência, com
#              log de progresso), então usam a mesma estrutura.

import time
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

        etapas = [
            ('MARKETPLACES', popular_marketplaces),
            ('CRITÉRIOS QUALIDADE', popular_criterios_qualidade),
            ('CONFIGURAÇÃO OPERACIONAL', popular_configuracao_operacional),
            ('CONFIGURAÇÃO ML', popular_configuracao_mercado_livre),
            ('TABELA COMISSÃO SHOPEE', popular_tabela_comissao_shopee),
            ('TABELA COMISSÃO TIKTOK', popular_tabela_comissao_tiktok),
            ('TAXA KG ADICIONAL AMAZON', popular_taxa_kg_adicional_amazon),
            ('RÉGUA DE FASES AGENDA VÍDEOS', popular_regua_fases_agenda_videos),
        ]

        for nome, funcao in etapas:
            inicio = time.time()
            funcao(self.stdout, self.style)
            duracao = time.time() - inicio
            self.stdout.write(self.style.WARNING(f'  ⏱ {nome}: {duracao:.1f}s\n'))

        self.stdout.write(self.style.SUCCESS('Seed concluído!'))