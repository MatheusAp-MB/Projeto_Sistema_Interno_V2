from decimal import Decimal
from precificacao.models import TaxaKgAdicionalAmazon

# * [EXPLICAÇÃO] → Só 5 faixas de preço × 2 tipos — pequeno e fixo o bastante pra
#                  ser seed (mesmo critério já usado pra TabelaComissaoShopee/Tiktok),
#                  não precisa de arquivo separado.
FAIXAS_DBA = [
    (Decimal('79.00'), Decimal('99.99'), Decimal('3.05')),
    (Decimal('100.00'), Decimal('119.99'), Decimal('3.05')),
    (Decimal('120.00'), Decimal('149.99'), Decimal('3.05')),
    (Decimal('150.00'), Decimal('199.99'), Decimal('3.50')),
    (Decimal('200.00'), None, Decimal('4.00')),
]
FAIXAS_FBA = FAIXAS_DBA  # mesmos valores encontrados nas 2 tabelas (Frete_AMZ_2/4)


def popular_taxa_kg_adicional_amazon(stdout, style):
    stdout.write('  [TAXA KG ADICIONAL AMAZON] Faixas por tipo...')

    for tipo, faixas in [('dba', FAIXAS_DBA), ('fba', FAIXAS_FBA)]:
        for preco_min, preco_max, valor_por_kg in faixas:
            _, criado = TaxaKgAdicionalAmazon.objects.get_or_create(
                tipo=tipo, preco_min=preco_min,
                defaults={'preco_max': preco_max, 'valor_por_kg': valor_por_kg},
            )
            teto = preco_max if preco_max is not None else 'sem teto'
            stdout.write(f'       {tipo} R$ {preco_min}-{teto}: {"criada" if criado else "já existe"}')