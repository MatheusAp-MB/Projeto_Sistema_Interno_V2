import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from mercado_livre.models import FreteML
from django.db.models import Q

faixa = FreteML.objects.filter(
    peso_min__lte=0.19, peso_max__gte=0.19,
    preco_min__lte=108.67,
).filter(
    Q(preco_max__gte=108.67) | Q(preco_max__isnull=True)
).first()
print(faixa)
