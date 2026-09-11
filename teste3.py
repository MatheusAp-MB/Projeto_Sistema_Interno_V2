# teste3.py — rodar da raiz do projeto: python -u teste3.py
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
import django
django.setup()

from django.db.models import Q
from produtos.models import Produto
from precificacao.models import GradePrecificacaoML


def investigar(alias):
    print(f"\n===== {alias.upper()} =====")

    dim_nula_ids = set(Produto.objects.using(alias).filter(
        Q(altura_ordenada_cm__isnull=True) | Q(altura_ordenada_cm=0)
        | Q(largura_ordenada_cm__isnull=True) | Q(largura_ordenada_cm=0)
        | Q(comprimento_ordenada_cm__isnull=True) | Q(comprimento_ordenada_cm=0)
    ).values_list('id', flat=True))

    quebradas = GradePrecificacaoML.objects.using(alias).filter(
        produto_id__in=dim_nula_ids, resolvida=True, origem_dimensao='produto_erp',
    )
    print(f"Linhas resolvidas=True usando o fallback quebrado (peso=0): {quebradas.count()}")
    print(f"Produtos distintos afetados: {quebradas.values_list('produto_id', flat=True).distinct().count()}")

    from django.db.models import Min, Max, Avg
    agg = quebradas.aggregate(min_frete=Min('frete_usado'), max_frete=Max('frete_usado'), avg_frete=Avg('frete_usado'))
    print(f"frete_usado nessas linhas: min={agg['min_frete']} max={agg['max_frete']} media={agg['avg_frete']}")


if __name__ == '__main__':
    for empresa_alias in ("magazine", "samvale"):
        investigar(empresa_alias)