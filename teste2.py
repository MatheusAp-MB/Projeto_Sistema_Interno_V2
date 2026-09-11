# teste2.py — rodar da raiz do projeto: python -u teste2.py
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
import django
django.setup()

from django.db.models import Q
from produtos.models import Produto
from precificacao.models import GradePrecificacaoML


def investigar(alias):
    print(f"\n===== {alias.upper()} =====")

    dim_nula_qs = Produto.objects.using(alias).filter(
        Q(altura_ordenada_cm__isnull=True) | Q(altura_ordenada_cm=0)
        | Q(largura_ordenada_cm__isnull=True) | Q(largura_ordenada_cm=0)
        | Q(comprimento_ordenada_cm__isnull=True) | Q(comprimento_ordenada_cm=0)
    )
    dim_nula_ids = list(dim_nula_qs.values_list('id', flat=True))
    print(f"Produtos com dimensao ordenada nula/zero (TODOS, sem filtrar por SEM CALCULO): {len(dim_nula_ids)}")

    grades = GradePrecificacaoML.objects.using(alias).filter(produto_id__in=dim_nula_ids)
    print(f"  Linhas GradePrecificacaoML total: {grades.count()}")
    print(f"    resolvida=True : {grades.filter(resolvida=True).count()}")
    print(f"    resolvida=False: {grades.filter(resolvida=False).count()}")

    amostra = grades.filter(resolvida=True).select_related('produto').order_by('produto_id')[:10]
    if amostra:
        print("\n  Amostra (ate 10) de LINHAS RESOLVIDAS=True com dimensao nula/zero no produto:")
        for g in amostra:
            p = g.produto
            print(
                f"    produto_id={p.id} sku={p.sku} "
                f"ordenada(a/l/c)={p.altura_ordenada_cm}/{p.largura_ordenada_cm}/{p.comprimento_ordenada_cm} | "
                f"tipo={g.tipo_anuncio} margem={g.margem} variacao_id={g.variacao_id} "
                f"preco={g.preco} frete_usado={g.frete_usado} origem_dimensao={g.origem_dimensao}"
            )
    else:
        print("\n  Nenhuma linha resolvida=True encontrada para esses produtos.")


if __name__ == '__main__':
    for empresa_alias in ("magazine", "samvale"):
        investigar(empresa_alias)