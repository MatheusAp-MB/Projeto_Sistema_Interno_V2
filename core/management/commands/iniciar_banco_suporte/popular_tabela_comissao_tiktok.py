# * [RESUMO] → Seed da tabela de comissão Tiktok (2 faixas, confirmadas por
#              print oficial do Tiktok). Dado fixo de referência — mesmo
#              padrão de FaixaArmazenagem/TabelaComissaoShopee, não vem de
#              arquivo externo do popular_banco.

from decimal import Decimal
from precificacao.models import TabelaComissaoTiktok
from core.management.commands.iniciar_banco_suporte.formatacao_faixa_preco import formatar_teto


def popular_tabela_comissao_tiktok(stdout, style):
    stdout.write('  [TABELA COMISSÃO TIKTOK] Faixas de comissão...')

    faixas = [
        (Decimal('0.00'), Decimal('49.99'), Decimal('10'), Decimal('4')),
        (Decimal('50.00'), None, Decimal('6'), Decimal('6')),
    ]

    for preco_min, preco_max, comissao_percentual, adicional_fixo in faixas:
        _, criado = TabelaComissaoTiktok.objects.get_or_create(
            preco_min=preco_min,
            defaults={
                'preco_max': preco_max,
                'comissao_percentual': comissao_percentual,
                'adicional_fixo': adicional_fixo,
            }
        )
        stdout.write(f'       R$ {preco_min}-{formatar_teto(preco_max)}: {"criada" if criado else "já existe"}')