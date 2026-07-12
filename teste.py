"""
Teste.py — Script de diagnóstico (SÓ LEITURA, não altera nada no banco).

Roda de dentro da pasta raiz do projeto (onde fica o manage.py):
    python Teste.py

Objetivo:
1. Investigar por que 'conflito_multiplas_ativas' deu 10 (não múltiplo de 3).
2. Levantar dados reais de PromocaoMercadoLivre pra decidir como expor
   'promocao_ativa' no card do Hub (estado atual vs ação recomendada).
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from collections import Counter
from mercado_livre.models import RecomendacaoPrecificacao, PromocaoMercadoLivre


def secao(titulo):
    print('\n' + '=' * 70)
    print(titulo)
    print('=' * 70)


# ------------------------------------------------------------------
# 1) INVESTIGAR O BUG: conflito deveria vir em múltiplos de 3
#    (3 linhas por variação — Padrão/Busca-Lucro/Disputa — já que
#    promocoes_ativas é calculado 1x por variação, fora do loop de
#    comportamentos, então as 3 linhas SEMPRE deveriam concordar)
# ------------------------------------------------------------------
secao('1) CONFLITO — quantas das 3 linhas por variação vieram marcadas?')

conflitos = (
    RecomendacaoPrecificacao.objects
    .filter(categoria_estado='conflito_multiplas_ativas')
    .values_list('variacao_id', flat=True)
)

contagem_por_variacao = Counter(conflitos)
print(f'Total de linhas com conflito: {sum(contagem_por_variacao.values())}')
print(f'Total de variações distintas envolvidas: {len(contagem_por_variacao)}')
print('Distribuição (qtd de linhas marcadas por variação -> quantas variações têm esse padrão):')
print(Counter(contagem_por_variacao.values()))

print('\nDetalhe variação por variação:')
for variacao_id, qtd in contagem_por_variacao.items():
    print(f'  variacao_id={variacao_id} -> {qtd} linha(s) marcada(s) de 3 possíveis')

    linhas = RecomendacaoPrecificacao.objects.filter(variacao_id=variacao_id).order_by('comportamento')
    for linha in linhas:
        print(
            f'      comportamento={linha.comportamento:<12} '
            f'categoria_estado={linha.categoria_estado!r:<28} '
            f'tem_escolha={linha.tem_escolha} '
            f'cenario_tipo={linha.cenario_tipo}'
        )

    promos = PromocaoMercadoLivre.objects.filter(variacao_id=variacao_id)
    print(f'      Promoções dessa variação ({promos.count()}):')
    for p in promos:
        print(f'        status={p.status:<10} tipo={p.tipo:<15} chave_externa={p.chave_externa}')


# ------------------------------------------------------------------
# 2) DADOS DISPONÍVEIS EM PromocaoMercadoLivre PRA EXPOR "promocao_ativa"
# ------------------------------------------------------------------
secao('2) Variações com EXATAMENTE 1 promoção started (caso normal, sem conflito)')

from django.db.models import Count

variacoes_com_1_ativa = (
    PromocaoMercadoLivre.objects
    .filter(status='started')
    .values('variacao_id')
    .annotate(qtd=Count('id'))
    .filter(qtd=1)
)
print(f'Total de variações com exatamente 1 promoção started: {variacoes_com_1_ativa.count()}')

print('\nAmostra de até 5 exemplos reais (nome, preco_avaliado, meli_percentage, chave_externa):')
amostra_ids = [v['variacao_id'] for v in variacoes_com_1_ativa[:5]]
for p in PromocaoMercadoLivre.objects.filter(variacao_id__in=amostra_ids, status='started'):
    print(
        f'  variacao_id={p.variacao_id} | nome={p.nome!r} | tipo={p.tipo} | '
        f'preco_original={p.preco_original} | preco_avaliado={p.preco_avaliado} | '
        f'meli_percentage={p.meli_percentage} | chave_externa={p.chave_externa}'
    )


# ------------------------------------------------------------------
# 3) None (sem escolha) — confirmar se está concentrado em algum
#    comportamento específico (esperado: mais em busca_lucro)
# ------------------------------------------------------------------
secao('3) categoria_estado = None — distribuição por comportamento')

nulos_por_comportamento = (
    RecomendacaoPrecificacao.objects
    .filter(categoria_estado__isnull=True)
    .values('comportamento')
    .annotate(qtd=Count('id'))
    .order_by('-qtd')
)
for row in nulos_por_comportamento:
    print(f"  {row['comportamento']:<15} {row['qtd']}")

print('\nFIM DO DIAGNÓSTICO.')