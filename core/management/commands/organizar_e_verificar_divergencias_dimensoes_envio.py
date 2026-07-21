# core/management/commands/organizar_e_verificar_divergencias_dimensoes_envio.py

# Função Objetivo: Comando fino — permite rodar a organização/comparação de dimensão de envio
# sozinha, sem precisar do popular_banco inteiro.
# Explicação em detalhe: mesma filosofia de popular_banco.py/iniciar_banco.py (comando real,
# fino, delegando a lógica pra popular_banco_suporte/). Sempre recalcula do zero — idempotente,
# seguro rodar quantas vezes quiser.

from django.core.management.base import BaseCommand
from core.management.commands.popular_banco_suporte.organizar_e_verificar_divergencias_dimensoes_envio import (
    organizar_e_verificar_divergencias_dimensoes_envio,
)


class Command(BaseCommand):
    help = (
        'Organiza as dimensões de envio (ERP + ML) em ordem consistente, persiste nos 2 '
        'models, e compara os 2 lados pra detectar divergência de dimensão de envio por '
        'MLB. Roda sozinho, fora do popular_banco — sempre recalcula do zero.'
    )

    def handle(self, *args, **options):
        organizar_e_verificar_divergencias_dimensoes_envio(self.stdout, self.style)