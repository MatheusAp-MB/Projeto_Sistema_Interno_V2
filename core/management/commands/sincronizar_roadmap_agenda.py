# core/management/commands/sincronizar_roadmap_agenda.py

from django.core.management.base import BaseCommand
from core.management.commands.popular_banco_suporte.sincronizar_roadmap_agenda import sincronizar_roadmap_agenda


class Command(BaseCommand):
    help = 'Garante que todo Produto tenha um RoadmapAgenda — roda sozinho, fora do popular_banco.'

    def handle(self, *args, **options):
        sincronizar_roadmap_agenda(self.stdout, self.style)