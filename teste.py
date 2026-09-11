# teste.py
#
# Rodar da raiz do projeto (mesma pasta do manage.py), com:
#   python -u "teste.py"
#
# Objetivo: dentro do grupo de produtos "SEM CALCULO por dimensao zerada"
# (GradePrecificacaoML.resolvida=False), separa quem tem pelo menos 1
# VariacaoAnuncioMercadoLivre vinculada (provavel erro real de cadastro
# de embalagem no ERP) de quem nao tem nenhuma (nao e bug — produto
# ainda nao foi anunciado no Mercado Livre, entao organizar_e_verificar_
# divergencias_dimensoes_envio nunca calculou altura_ordenada_cm/etc pra
# ele). So leitura — nenhum write no banco.

import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')

import django
django.setup()

from django.db.models import Q
from precificacao.models import GradePrecificacaoML
from produtos.models import Produto
from mercado_livre.models import VariacaoAnuncioMercadoLivre


def investigar(alias):
    print(f"\n===== {alias.upper()} =====")

    sem_calculo = GradePrecificacaoML.objects.using(alias).filter(resolvida=False)
    produtos_ids = set(sem_calculo.values_list('produto_id', flat=True).distinct())

    dimensao_zerada_qs = Produto.objects.using(alias).filter(id__in=produtos_ids).filter(
        Q(altura_ordenada_cm__isnull=True) | Q(altura_ordenada_cm=0)
        | Q(largura_ordenada_cm__isnull=True) | Q(largura_ordenada_cm=0)
        | Q(comprimento_ordenada_cm__isnull=True) | Q(comprimento_ordenada_cm=0)
    )
    dim_ids = set(dimensao_zerada_qs.values_list('id', flat=True))

    tem_mlb_ids = set(
        VariacaoAnuncioMercadoLivre.objects.using(alias)
        .filter(produto_id__in=dim_ids)
        .values_list('produto_id', flat=True)
        .distinct()
    )
    sem_mlb_ids = dim_ids - tem_mlb_ids

    print(f"Produtos SEM CALCULO (ML), total: {len(produtos_ids)}")
    print(f"Dimensao zerada, total: {len(dim_ids)}")
    print(f"  ...COM MLB vinculado (provavel erro real de cadastro no ERP): {len(tem_mlb_ids)}")
    print(f"  ...SEM nenhum MLB vinculado (nao e bug, produto nao anunciado ainda): {len(sem_mlb_ids)}")

    if tem_mlb_ids:
        print("\n  Amostra (ate 15) dos 'COM MLB vinculado, ainda assim zerado':")
        amostra = Produto.objects.using(alias).filter(id__in=list(tem_mlb_ids)[:15]).values(
            'id', 'sku', 'ean', 'titulo',
            'altura_ordenada_cm', 'largura_ordenada_cm', 'comprimento_ordenada_cm',
            'altura_produto_apos_embalado', 'largura_produto_apos_embalado',
            'comprimento_produto_apos_embalado',
        )
        for p in amostra:
            print(f"    id={p['id']} sku={p['sku']} ean={p['ean']} titulo={p['titulo']!r}")
            print(
                f"      ordenada(a/l/c)={p['altura_ordenada_cm']}/{p['largura_ordenada_cm']}/{p['comprimento_ordenada_cm']}"
                f"   apos_embalado(a/l/c)={p['altura_produto_apos_embalado']}/{p['largura_produto_apos_embalado']}/{p['comprimento_produto_apos_embalado']}"
            )


if __name__ == '__main__':
    for empresa_alias in ("magazine", "samvale"):
        try:
            investigar(empresa_alias)
        except Exception as exc:
            print(f"\n[ERRO ao investigar {empresa_alias.upper()}] {exc!r}", file=sys.stderr)