# * [RESUMO] → Seed da taxa de kg adicional da Amazon (2 tipos — DBA e FBA —,
#              5 faixas de preço cada). Dado fixo de referência, mesmo
#              critério já usado pra TabelaComissaoShopee/Tiktok, pequeno o
#              bastante pra não precisar de arquivo externo separado.

from decimal import Decimal
from precificacao.models import TaxaKgAdicionalAmazon
from core.management.commands.iniciar_banco_suporte.formatacao_faixa_preco import formatar_teto

# * [EXPLICAÇÃO] → FBA reaproveita a mesma lista da DBA de propósito — os
#                  valores encontrados nas 2 tabelas oficiais (Frete_AMZ_2/4)
#                  são idênticos hoje. Se um dia divergirem, é só separar em
#                  2 listas — nada mais precisa mudar.
FAIXAS_DBA = [
    (Decimal('79.00'), Decimal('99.99'), Decimal('3.05')),
    (Decimal('100.00'), Decimal('119.99'), Decimal('3.05')),
    (Decimal('120.00'), Decimal('149.99'), Decimal('3.05')),
    (Decimal('150.00'), Decimal('199.99'), Decimal('3.50')),
    (Decimal('200.00'), None, Decimal('4.00')),
]
FAIXAS_FBA = FAIXAS_DBA


def popular_taxa_kg_adicional_amazon(stdout, style):
    stdout.write('  [TAXA KG ADICIONAL AMAZON] Faixas por tipo...')

    for tipo, faixas in [('dba', FAIXAS_DBA), ('fba', FAIXAS_FBA)]:
        for preco_min, preco_max, valor_por_kg in faixas:
            _, criado = TaxaKgAdicionalAmazon.objects.get_or_create(
                tipo=tipo, preco_min=preco_min,
                defaults={'preco_max': preco_max, 'valor_por_kg': valor_por_kg},
            )
            stdout.write(f'       {tipo} R$ {preco_min}-{formatar_teto(preco_max)}: {"criada" if criado else "já existe"}')