# * [RESUMO] → Seed da tabela de comissão Shopee (5 faixas, confirmadas por print
#              oficial da Shopee, 18/07). Dado fixo de referência — mesmo padrão de
#              FaixaArmazenagem, não vem de arquivo externo do popular_banco.

from decimal import Decimal
from precificacao.models import TabelaComissaoShopee
from core.management.commands.iniciar_banco_suporte.formatacao_faixa_preco import formatar_teto


def popular_tabela_comissao_shopee(stdout, style):
    stdout.write('  [TABELA COMISSÃO SHOPEE] Faixas de comissão CNPJ...')

    faixas = [
        (Decimal('0.00'), Decimal('79.99'), Decimal('20'), Decimal('4')),
        (Decimal('80.00'), Decimal('99.99'), Decimal('14'), Decimal('16')),
        (Decimal('100.00'), Decimal('199.99'), Decimal('14'), Decimal('20')),
        (Decimal('200.00'), Decimal('499.99'), Decimal('14'), Decimal('26')),
        (Decimal('500.00'), None, Decimal('14'), Decimal('26')),
    ]

    for preco_min, preco_max, comissao_percentual, adicional_fixo in faixas:
        _, criado = TabelaComissaoShopee.objects.get_or_create(
            preco_min=preco_min,
            defaults={
                'preco_max': preco_max,
                'comissao_percentual': comissao_percentual,
                'adicional_fixo': adicional_fixo,
            }
        )
        stdout.write(f'       R$ {preco_min}-{formatar_teto(preco_max)}: {"criada" if criado else "já existe"}')