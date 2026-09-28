# scripts_exploracao_ML/teste_assinatura_dimensao_entre_produtos.py

# Função Objetivo: Mede quantas combinações distintas de (altura,largura,comprimento,peso,
# origem) existem no catálogo inteiro — e, mais importante, quantas dessas combinações são
# compartilhadas entre PRODUTOS DIFERENTES (não só entre MLBs do mesmo produto). Isso decide
# se vale a pena um cache GLOBAL (cross-produto) de coleta/armazenagem-por-faixa/faixas-de-
# frete-candidatas, além do cache por produto que já existe. Só leitura, sem escrita, sem
# chamada de API — puro cálculo local sobre dimensões já resolvidas.
#
# Uso:
#   python scripts_exploracao_ML/teste_assinatura_dimensao_entre_produtos.py --empresa magazine

import os
import sys
import django
import argparse
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from core.empresa import definir_empresa_ativa, EMPRESA_POR_ALIAS_BANCO
from produtos.models import Produto
from mercado_livre.models import VariacaoAnuncioMercadoLivre
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas


def main():
    parser = argparse.ArgumentParser(
        description='Mede o potencial de cache de dimensão compartilhado entre produtos diferentes.'
    )
    parser.add_argument('--empresa', required=True, choices=list(EMPRESA_POR_ALIAS_BANCO.keys()))
    args = parser.parse_args()

    definir_empresa_ativa(EMPRESA_POR_ALIAS_BANCO[args.empresa])

    produtos = list(Produto.objects.all())
    print(f'{len(produtos)} produto(s) encontrados')

    variacoes_por_produto = defaultdict(list)
    for v in VariacaoAnuncioMercadoLivre.objects.filter(
        produto__isnull=False, anuncio__tipo_de_anuncio__isnull=False
    ).select_related('produto'):
        variacoes_por_produto[v.produto_id].append(v)

    assinaturas = []
    produtos_por_assinatura = defaultdict(set)

    for produto in produtos:
        # Fallback do produto (Grade Base) — mesma resolução que o loop de produção usa.
        dim_fallback = resolver_dimensoes_efetivas(produto, variacao=None)
        if dim_fallback is not None:
            chave = (
                dim_fallback.altura, dim_fallback.largura, dim_fallback.comprimento,
                dim_fallback.peso, dim_fallback.origem,
            )
            assinaturas.append(chave)
            produtos_por_assinatura[chave].add(produto.pk)

        for v in variacoes_por_produto.get(produto.pk, []):
            dim = resolver_dimensoes_efetivas(produto, variacao=v)
            if dim is None:
                continue
            chave = (dim.altura, dim.largura, dim.comprimento, dim.peso, dim.origem)
            assinaturas.append(chave)
            produtos_por_assinatura[chave].add(produto.pk)

    total = len(assinaturas)
    contagem = Counter(assinaturas)
    unicas = len(contagem)
    evitaveis = total - unicas

    print(f'\nTotal de linhas (fallback + MLBs) com dimensão resolvida: {total}')
    print(f'Combinações únicas de (altura,largura,comprimento,peso,origem): {unicas}')
    if total:
        print(f'Recálculos que um cache por dimensão evitaria (qualquer nível): '
              f'{evitaveis} ({evitaveis / total:.1%})')

    # O dado que decide se vale um cache GLOBAL (cross-produto), não só interno ao produto.
    compartilhadas_entre_produtos = {
        chave: produtos_ids for chave, produtos_ids in produtos_por_assinatura.items()
        if len(produtos_ids) > 1
    }
    print(f'\nCombinações de dimensão usadas por MAIS DE 1 PRODUTO diferente: '
          f'{len(compartilhadas_entre_produtos)} de {unicas}')

    print('\nTop 10 combinações mais compartilhadas entre produtos diferentes:')
    top = sorted(compartilhadas_entre_produtos.items(), key=lambda kv: -len(kv[1]))[:10]
    for chave, produtos_ids in top:
        print(f'  {len(produtos_ids)} produtos diferentes — altura={chave[0]} largura={chave[1]} '
              f'comprimento={chave[2]} peso={chave[3]} origem={chave[4]}')


if __name__ == '__main__':
    main()