# * [RESUMO] → Seed da Configuração Operacional (fator_coleta/período) e das
#              4 faixas de armazenagem — compartilhado por TODOS os
#              marketplaces (movido de popular_configuracao_mercado_livre.py,
#              17/07, junto da separação ConfiguracaoOperacional/FaixaArmazenagem
#              pro app precificacao). Usa get_or_create — seguro rodar mais de
#              uma vez, nunca duplica.

from decimal import Decimal
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem


def popular_configuracao_operacional(stdout, style):
    stdout.write('  [CONFIG OPERACIONAL] Configuração geral...')
    _, criado = ConfiguracaoOperacional.objects.get_or_create(
        pk=1,
        defaults={
            'fator_coleta': Decimal('72'),
            'periodo_armazenagem': 30,
        }
    )
    stdout.write(f'       {"criada" if criado else "já existe"}')

    stdout.write('  [CONFIG OPERACIONAL] Faixas de armazenagem...')
    faixas = [
        (1, 'Faixa 1 — Até 12×15×25cm',       Decimal('0.0070'), 12,   15,   25),
        (2, 'Faixa 2 — Até 28×36×51cm',       Decimal('0.0150'), 28,   36,   51),
        (3, 'Faixa 3 — Até 60×60×70cm',       Decimal('0.0500'), 60,   60,   70),
        (4, 'Faixa 4 — Maior que 60×60×70cm', Decimal('0.1070'), 9999, 9999, 9999),
    ]

    for ordem, nome, valor_diario, max_altura, max_largura, max_profundidade in faixas:
        _, criado = FaixaArmazenagem.objects.get_or_create(
            ordem=ordem,
            defaults={
                'nome': nome,
                'valor_diario': valor_diario,
                'max_altura': Decimal(str(max_altura)),
                'max_largura': Decimal(str(max_largura)),
                'max_profundidade': Decimal(str(max_profundidade)),
                'ativo': True,
            }
        )
        stdout.write(f'       {nome}: {"criada" if criado else "já existe"}')