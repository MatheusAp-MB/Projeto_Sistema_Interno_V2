# core/management/commands/sincronizar_indicadores_agenda.py

from django.core.management.base import BaseCommand
from core.management.commands.popular_banco_suporte.sincronizar_indicadores_agenda_em_lote import sincronizar_indicadores_agenda_em_lote


class Command(BaseCommand):
    help = 'Garante que todo Produto tenha um IndicadoresAgendaProduto — roda sozinho, fora do popular_banco.'

    def handle(self, *args, **options):
        sincronizar_indicadores_agenda_em_lote(self.stdout, self.style)