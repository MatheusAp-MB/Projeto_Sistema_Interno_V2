# core/management/commands/importar_agenda_legada.py

from django.core.management.base import BaseCommand
from agenda_videos.funcoes_auxiliares.importar_agenda_legada import importar_agenda_legada


class Command(BaseCommand):
    help = (
        'Importa o estado atual da Agenda (fase, ocorrência, status manual, '
        'vencimento) a partir da planilha legada do Google Sheets, aba '
        '"Base de Produtos" (ex: MAGAZINE.xlsx). Casa por EAN com Produto '
        'já existente — nunca cria Produto novo.'
    )

    def add_arguments(self, parser):
        parser.add_argument('caminho_arquivo', type=str, help='Caminho do arquivo .xlsx a importar.')

    def handle(self, *args, **options):
        importar_agenda_legada(options['caminho_arquivo'], self.stdout, self.style)