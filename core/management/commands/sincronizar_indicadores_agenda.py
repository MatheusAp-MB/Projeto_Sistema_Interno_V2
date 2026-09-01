# core/management/commands/sincronizar_indicadores_agenda.py

from core.management.commands._base_empresa import ComandoComEmpresa
from core.management.commands.popular_banco_suporte.sincronizar_indicadores_agenda_em_lote import sincronizar_indicadores_agenda_em_lote


class Command(ComandoComEmpresa):
    help = 'Garante que todo Produto tenha um IndicadoresAgendaProduto — roda sozinho, fora do popular_banco. Exige --empresa (MAGAZINE ou SAMVALE).'

    def handle(self, *args, **options):
        sincronizar_indicadores_agenda_em_lote(self.stdout, self.style)