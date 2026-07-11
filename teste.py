import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from mercado_livre.models import QualidadeAnuncio
from django.db.models import Count

duplicados = (
    QualidadeAnuncio.objects.values('variacao_id')
    .annotate(qtd=Count('id'))
    .filter(qtd__gt=1)
)
print('Variações com mais de 1 QualidadeAnuncio:', duplicados.count())