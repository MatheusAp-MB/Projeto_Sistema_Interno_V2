import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from mercado_livre.models import VariacaoAnuncioMercadoLivre
from django.db.models import Count

print('Total de linhas de Variação no banco:', VariacaoAnuncioMercadoLivre.objects.count())
print('Total de MLBs distintos:', VariacaoAnuncioMercadoLivre.objects.values('anuncio_id').distinct().count())

mlbs_com_mais_de_1 = (
    VariacaoAnuncioMercadoLivre.objects.values('anuncio_id')
    .annotate(qtd=Count('id'))
    .filter(qtd__gt=1)
)
print('MLBs com mais de 1 variação:', mlbs_com_mais_de_1.count())
print('Total de variações "extras" nesses MLBs:', sum(m['qtd'] - 1 for m in mlbs_com_mais_de_1))