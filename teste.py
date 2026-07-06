import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from mercado_livre.models import VariacaoAnuncioMercadoLivre
from mercado_livre.management.commands.validar_classificacao_suporte.classificacao_catalogo import (
    info_variacao,
    calcular_ponteiro_termometro,
)
import random

variacoes = VariacaoAnuncioMercadoLivre.objects.filter(produto__sku='F7908050719121.001')

print(f'Total de variações encontradas: {variacoes.count()}\n')

for v in variacoes:
    score_teste = random.randint(0, 100)
    x, y = calcular_ponteiro_termometro(score_teste)
    print(f'{v.anuncio.mlb}: score={score_teste} -> ponteiro=({x}, {y})')