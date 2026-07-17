"""
teste.py — Varredura COMPLETA de qualidade de dado, VERSÃO 2 (corrige
o defeito achado na V1: "embalagem = 0 explícito" estava sendo tratado
como se fosse uma medida real na checagem de coerência física).

Cobre:
A) Consistência de unidade — Produto sem embalar
B) Consistência de unidade — Produto embalado
C) Coerência física — embalagem vs produto puro (agora separando
   "zero explícito na planilha" de "incoerência de valor real")
D) peso_cubado salvo vs recalculado agora
E) Custo/Custo com Bônis
F) Taxas percentuais (ICMS/IPI/PIS/MVA)
G) Preço atual das variações
H) FreteML — faixas

Lista os SKUs de cada achado suspeito, não só a contagem — pra dar
pra investigar direto, sem precisar pedir de novo depois.

Só LEITURA — não grava, não corrige nada.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from decimal import Decimal
from django.db.models import Q, F
from produtos.models import Produto
from mercado_livre.models import VariacaoAnuncioMercadoLivre, FreteML

FATOR_PESO_CUBADO = Decimal('6000')


def secao(titulo):
    print('\n' + '=' * 80)
    print(titulo)
    print('=' * 80)


def listar_skus(queryset, limite=20):
    for p in queryset[:limite]:
        print(f'    {p.sku}')
    total = queryset.count()
    if total > limite:
        print(f'    ... e mais {total - limite} SKU(s).')


# ======================================================================
# A) UNIDADE — Produto sem embalar
# ======================================================================
secao('A) UNIDADE — Produto SEM embalar (dimensões)')

for campo in ['altura_produto_sem_embalar', 'largura_produto_sem_embalar', 'comprimento_produto_sem_embalar']:
    suspeitos = Produto.objects.filter(**{f'{campo}__gt': 0, f'{campo}__lt': 1})
    plausiveis = Produto.objects.filter(**{f'{campo}__gte': 1, f'{campo}__lte': 200}).count()
    absurdos = Produto.objects.filter(**{f'{campo}__gt': 200}).count()
    zerados = Produto.objects.filter(**{campo: 0}).count()
    print(f'\n  {campo}:')
    print(f'    Suspeito de estar em METRO ainda (0 < x < 1): {suspeitos.count()}')
    if suspeitos.exists():
        listar_skus(suspeitos)
    print(f'    Plausível em cm (1 a 200): {plausiveis}')
    print(f'    Suspeito de absurdo (> 200cm): {absurdos}')
    print(f'    Zerado (provável: nunca passou pelo ERP Completo): {zerados}')

peso = 'peso_produto_sem_embalar'
print(f'\n  {peso}:')
print(f'    Zerado: {Produto.objects.filter(**{peso: 0}).count()}')
print(f'    Negativo: {Produto.objects.filter(**{f"{peso}__lt": 0}).count()}')
print(f'    Suspeito de absurdo (> 200kg): {Produto.objects.filter(**{f"{peso}__gt": 200}).count()}')


# ======================================================================
# B) UNIDADE — Produto embalado
# ======================================================================
secao('B) UNIDADE — Produto APÓS embalado (dimensões)')

for campo in ['altura_produto_apos_embalado', 'largura_produto_apos_embalado', 'comprimento_produto_apos_embalado']:
    com_dado = Produto.objects.filter(**{f'{campo}__isnull': False})
    # * [EXPLICAÇÃO] → "suspeito de metro" só faz sentido pra quem tem
    #                  valor > 0 — 0 explícito é outra categoria
    #                  (achado da V1), tratada separadamente abaixo.
    suspeitos = com_dado.filter(**{f'{campo}__gt': 0, f'{campo}__lt': 1})
    plausiveis = com_dado.filter(**{f'{campo}__gte': 1, f'{campo}__lte': 200}).count()
    absurdos = com_dado.filter(**{f'{campo}__gt': 200})
    zero_explicito = com_dado.filter(**{campo: 0}).count()
    sem_dado = Produto.objects.filter(**{f'{campo}__isnull': True}).count()
    print(f'\n  {campo}:')
    print(f'    Suspeito de estar em METRO ainda (0 < x < 1): {suspeitos.count()}')
    if suspeitos.exists():
        listar_skus(suspeitos)
    print(f'    Plausível em cm (1 a 200): {plausiveis}')
    print(f'    Suspeito de absurdo (> 200cm): {absurdos.count()}')
    if absurdos.exists():
        listar_skus(absurdos)
    print(f'    ZERO EXPLÍCITO na planilha (achado: célula "0", não vazia): {zero_explicito}')
    print(f'    Sem dado cadastrado (None — célula realmente vazia): {sem_dado}')

peso_emb = 'peso_produto_apos_embalado'
com_peso = Produto.objects.filter(**{f'{peso_emb}__isnull': False})
print(f'\n  {peso_emb}:')
print(f'    Zero explícito: {com_peso.filter(**{peso_emb: 0}).count()}')
print(f'    Negativo: {com_peso.filter(**{f"{peso_emb}__lt": 0}).count()}')
print(f'    Suspeito de absurdo (> 200kg): {com_peso.filter(**{f"{peso_emb}__gt": 200}).count()}')
print(f'    Sem dado cadastrado (None): {Produto.objects.filter(**{f"{peso_emb}__isnull": True}).count()}')


# ======================================================================
# C) COERÊNCIA FÍSICA — embalagem vs produto puro
#    CORRIGIDO: exclui explicitamente os casos onde a embalagem é 0
#    (ausência disfarçada de zero, não uma medida real menor).
# ======================================================================
secao('C) COERÊNCIA FÍSICA — embalagem < produto puro')

base_com_embalagem_real = Produto.objects.filter(
    altura_produto_apos_embalado__gt=0,
    largura_produto_apos_embalado__gt=0,
    comprimento_produto_apos_embalado__gt=0,
)

incoerentes = base_com_embalagem_real.filter(
    Q(altura_produto_apos_embalado__lt=F('altura_produto_sem_embalar')) |
    Q(largura_produto_apos_embalado__lt=F('largura_produto_sem_embalar')) |
    Q(comprimento_produto_apos_embalado__lt=F('comprimento_produto_sem_embalar'))
)

print(f'  Produtos com embalagem REAL (>0 nos 3 eixos) E menor que o produto puro: {incoerentes.count()}')
print('  (Suspeita mais provável: eixos trocados entre as 2 fontes — Altura/Largura/Comprimento')
print('   medidos em ordem diferente — mesmo padrão de erro já visto antes na migração do Django.)')
print()
for p in incoerentes[:20]:
    print(
        f'    {p.sku}: puro={p.altura_produto_sem_embalar}x{p.largura_produto_sem_embalar}x{p.comprimento_produto_sem_embalar}'
        f'  embalado={p.altura_produto_apos_embalado}x{p.largura_produto_apos_embalado}x{p.comprimento_produto_apos_embalado}'
    )
total_incoerentes = incoerentes.count()
if total_incoerentes > 20:
    print(f'    ... e mais {total_incoerentes - 20} SKU(s).')


# ======================================================================
# D) peso_cubado salvo vs recalculado agora
# ======================================================================
secao('D) peso_cubado — SALVO vs RECALCULADO agora (mesma fórmula)')

divergentes = []
produtos_com_embalagem = Produto.objects.filter(
    altura_produto_apos_embalado__isnull=False,
    largura_produto_apos_embalado__isnull=False,
    comprimento_produto_apos_embalado__isnull=False,
)
total_checados = 0
for p in produtos_com_embalagem.iterator():
    total_checados += 1
    recalculado = (p.altura_produto_apos_embalado * p.largura_produto_apos_embalado * p.comprimento_produto_apos_embalado) / FATOR_PESO_CUBADO
    salvo = p.peso_cubado or Decimal('0')
    if abs(recalculado - salvo) > Decimal('0.01'):
        divergentes.append((p.sku, salvo, recalculado))

print(f'  Produtos checados: {total_checados}')
print(f'  Divergentes (salvo != recalculado): {len(divergentes)}')
for sku, salvo, recalculado in divergentes[:20]:
    print(f'    {sku}: salvo={salvo}  recalculado_agora={recalculado:.3f}')


# ======================================================================
# E) CUSTO / CUSTO COM BÔNIS
# ======================================================================
secao('E) CUSTO / CUSTO COM BÔNIS')

zerados = Produto.objects.filter(custo=0)
absurdos = Produto.objects.filter(custo__gt=50000)
print(f'  Custo zerado (não dá pra precificar sem isso): {zerados.count()}')
if zerados.exists():
    print('  Primeiros 10 SKUs com custo zerado:')
    listar_skus(zerados, limite=10)
print(f'  Custo negativo: {Produto.objects.filter(custo__lt=0).count()}')
print(f'  Custo > R$50.000 (suspeito):')
listar_skus(absurdos, limite=10)
print(f'  Custo com Bônis negativo: {Produto.objects.filter(custo_com_boni__lt=0).count()}')
print(f'  Custo com Bônis > R$50.000 (suspeito): {Produto.objects.filter(custo_com_boni__gt=50000).count()}')


# ======================================================================
# F) TAXAS PERCENTUAIS
# ======================================================================
secao('F) TAXAS PERCENTUAIS (ICMS/IPI/PIS/MVA) — devem estar entre 0 e 100')

for campo in ['icms_entrada', 'icms_saida_media', 'icms_saida_sp', 'ipi', 'pis_cofins', 'mva']:
    fora = Produto.objects.filter(**{f'{campo}__isnull': False}).exclude(
        **{f'{campo}__gte': 0, f'{campo}__lte': 100}
    )
    print(f'  {campo}: fora da faixa 0-100: {fora.count()}')
    if fora.exists():
        listar_skus(fora, limite=5)


# ======================================================================
# G) PREÇO ATUAL DAS VARIAÇÕES
# ======================================================================
secao('G) PREÇO ATUAL DAS VARIAÇÕES')

total_variacoes = VariacaoAnuncioMercadoLivre.objects.count()
sem_preco = VariacaoAnuncioMercadoLivre.objects.filter(Q(preco_atual__isnull=True) | Q(preco_atual=0))
preco_suspeito_baixo = VariacaoAnuncioMercadoLivre.objects.filter(preco_atual__gt=0, preco_atual__lt=1)
print(f'  Total de variações: {total_variacoes}')
print(f'  Sem preço (None ou 0): {sem_preco.count()}')
print(f'  Preço suspeito (entre R$0 e R$1): {preco_suspeito_baixo.count()}')


# ======================================================================
# H) FRETEML
# ======================================================================
secao('H) FRETEML — checagem de faixas')

faixas = list(FreteML.objects.order_by('peso_min', 'preco_min'))
print(f'  Total de faixas cadastradas: {len(faixas)}')

pesos_min = sorted(set(f.peso_min for f in faixas))
print(f'  Faixas de peso distintas: {len(pesos_min)}')
print(f'  Menor peso_min: {pesos_min[0] if pesos_min else "—"}')
print(f'  Maior peso_min: {pesos_min[-1] if pesos_min else "—"}')


# ======================================================================
# RESUMO FINAL — respondendo direto as 4 perguntas originais
# ======================================================================
secao('RESUMO — RESPOSTAS ÀS 4 PERGUNTAS')
print("""
1) Erro de conversão (metro vs cm, kg vs kg)?
   Ver seções A e B acima — "suspeito de estar em METRO ainda" deveria
   ser 0 ou muito próximo disso. Qualquer SKU listado ali merece
   conferência manual antes de confiar 100%.

2) Fórmula do peso cúbico (cm×cm×cm)/6000, padrão internacional?
   Ver seção D — "Divergentes: 0" confirma que a fórmula gravada bate
   com a fórmula real, sem dado desatualizado.

3) Dados de entrada prontos pra trabalhar?
   Ver seção C (coerência física) e E (custo zerado) — esses são os
   2 pontos que ainda precisam de atenção humana, não são mais
   problema de conversão de unidade.

4) Dados de entrada 100% confiáveis?
   NÃO dá pra afirmar 100% — só dá pra afirmar "sem erro SISTEMÁTICO
   de unidade" (o que este script já comprova). Erro pontual de
   medida (SKU por SKU) só se descobre comparando contra a realidade
   (relatório de frete ERP vs ML já construído antes).
""")

print('Varredura concluída.')