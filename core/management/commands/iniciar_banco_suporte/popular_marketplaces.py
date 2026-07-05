# * [RESUMO] → Popula os marketplaces suportados pelo sistema.
#              Usa get_or_create — seguro rodar múltiplas vezes,
#              nunca duplica dados nem sobrescreve o campo 'ativo'
#              se o marketplace já existir.

from marketplaces.models import Marketplace

MARKETPLACES = [
    {'nome': 'Mercado Livre', 'sigla': 'ML',      'ordem': 1},
    {'nome': 'Shopee',        'sigla': 'SHOPEE',  'ordem': 2},
    {'nome': 'Amazon',        'sigla': 'AMAZON',  'ordem': 3},
    {'nome': 'Magalu',        'sigla': 'MAGALU',  'ordem': 4},
    {'nome': 'Tiktok Shop',   'sigla': 'TIKTOK',  'ordem': 5},
    {'nome': 'Mais Correios', 'sigla': 'CORREIOS','ordem': 6},
    {'nome': 'Raia',          'sigla': 'RAIA',    'ordem': 7},
    {'nome': 'Tudo de Agro',  'sigla': 'TD_AGRO', 'ordem': 8},
]


def popular_marketplaces(stdout, style):
    stdout.write('[MARKETPLACES] Criando marketplaces...')
    for mp in MARKETPLACES:
        _, criado = Marketplace.objects.get_or_create(
            sigla=mp['sigla'],
            defaults={'nome': mp['nome'], 'ativo': True, 'ordem': mp['ordem']}
        )
        stdout.write(f"    {mp['nome']}: {'criado' if criado else 'já existe'}")