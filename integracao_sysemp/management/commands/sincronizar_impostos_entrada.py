# integracao_sysemp/management/commands/sincronizar_impostos_entrada.py

from django.core.management.base import BaseCommand

from integracao_sysemp.servicos.orquestrador import sincronizar_impostos_entrada_xml


class Command(BaseCommand):
    help = 'Sincroniza os impostos/custos de entrada a partir do manifesto XML do Sysemp.'

    def handle(self, *args, **options):
        sincronizar_impostos_entrada_xml()
        self.stdout.write(self.style.SUCCESS('Sincronização concluída.'))