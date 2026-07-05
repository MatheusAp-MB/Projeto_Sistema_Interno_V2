import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

import json as jsonlib
from mercado_livre.management.commands.validar_classificacao_suporte.classificacao_catalogo import (
    classificar_todos_os_skus, parsear_item_relations
)
from mercado_livre.models import AnuncioMercadoLivre, TipoDeAnuncioMercadoLivre

Classificacao = TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo

# ================================================
# 1. COLETA OS ÓRFÃOS ATIVOS
# ================================================
resultado = classificar_todos_os_skus()

orfaos_info = []  # (mlb, sku_da_arvore, catalog_product_id_da_pagina)
for sku, r in resultado.items():
    for pagina in r['paginas_catalogo']:
        for orfao in pagina['anuncios_catalogo_orfaos']:
            orfaos_info.append({
                'mlb': orfao['mlb'],
                'sku_arvore': sku,
                'catalog_product_id': pagina['catalog_product_id'],
            })

mlbs_orfaos = [o['mlb'] for o in orfaos_info]

anuncios_orfaos = {
    a.mlb: a for a in AnuncioMercadoLivre.objects.filter(
        mlb__in=mlbs_orfaos
    ).select_related('tipo_de_anuncio')
}

orfaos_ativos = [
    o for o in orfaos_info
    if anuncios_orfaos.get(o['mlb']) and anuncios_orfaos[o['mlb']].tipo_de_anuncio
    and anuncios_orfaos[o['mlb']].tipo_de_anuncio.status == 'active'
]

print(f'=== TOTAL DE ÓRFÃOS ATIVOS: {len(orfaos_ativos)} ===\n')

# ================================================
# 2. CARREGA TODOS OS ANÚNCIOS BASE DO BANCO (para busca ampla)
# ================================================
todos_bases = list(
    AnuncioMercadoLivre.objects.filter(
        tipo_de_anuncio__classificacao_catalogo=Classificacao.BASE
    ).select_related('tipo_de_anuncio')
)
print(f'Total de Anúncios Base no banco inteiro: {len(todos_bases)}\n')

# Monta índice: mlb_do_catalogo_referenciado -> base que o referencia
base_referencia_mlb = {}
for base in todos_bases:
    relacoes = parsear_item_relations(base.item_relations)
    for rel in relacoes:
        if isinstance(rel, dict) and rel.get('id'):
            base_referencia_mlb.setdefault(rel['id'], []).append(base)

# ================================================
# 3. PARA CADA ÓRFÃO ATIVO, INVESTIGA A FUNDO
# ================================================
casos_com_base_em_outro_sku = 0
casos_genuinamente_sem_relacao = 0
casos_com_item_relations_proprio = 0

for i, orfao in enumerate(orfaos_ativos[:15], 1):  # amostra de 15 para não poluir demais
    mlb = orfao['mlb']
    anuncio = anuncios_orfaos[mlb]

    print(f'--- Órfão ativo {i}: {mlb} ---')
    print(f'    Título: {anuncio.titulo_anuncio}')
    print(f'    SKU (na árvore, via variação): {orfao["sku_arvore"]}')
    print(f'    catalog_product_id da página: {orfao["catalog_product_id"]}')
    print(f'    item_relations do próprio órfão: {anuncio.item_relations}')

    tem_item_relations_proprio = bool(parsear_item_relations(anuncio.item_relations))
    if tem_item_relations_proprio:
        casos_com_item_relations_proprio += 1

    # Busca ampla: existe ALGUM Base no banco (de qualquer SKU) que referencia este MLB?
    bases_que_referenciam = base_referencia_mlb.get(mlb, [])

    if bases_que_referenciam:
        casos_com_base_em_outro_sku += 1
        print(f'    ✅ ENCONTRADO — {len(bases_que_referenciam)} Base(s) no banco referenciam este MLB:')
        for b in bases_que_referenciam:
            print(f'       → {b.mlb} | SKU vinculado: (verificar produto/variação separadamente)')
    else:
        casos_genuinamente_sem_relacao += 1
        print(f'    ❌ Nenhum Base no banco inteiro referencia este MLB — órfão genuíno (ou Base não importada)')

    # Verifica também se o próprio catalog_product_id da página existe mas com outro nome de SKU
    print()

# ================================================
# 4. RESUMO ESTATÍSTICO COMPLETO (sobre TODOS os 88, não só a amostra)
# ================================================
print('=' * 60)
print('RESUMO ESTATÍSTICO — TODOS OS ÓRFÃOS ATIVOS')
print('=' * 60)

total_com_base_encontrada = 0
total_sem_base_alguma = 0
total_com_item_relations_proprio = 0

for orfao in orfaos_ativos:
    mlb = orfao['mlb']
    anuncio = anuncios_orfaos[mlb]

    if parsear_item_relations(anuncio.item_relations):
        total_com_item_relations_proprio += 1

    if base_referencia_mlb.get(mlb):
        total_com_base_encontrada += 1
    else:
        total_sem_base_alguma += 1

print(f'Total órfãos ativos:                              {len(orfaos_ativos)}')
print(f'  → Base encontrada em algum lugar do banco:       {total_com_base_encontrada}')
print(f'  → Nenhum Base no banco referencia este MLB:      {total_sem_base_alguma}')
print(f'  → O próprio órfão TEM item_relations preenchido: {total_com_item_relations_proprio}')
print()
print('Interpretação:')
print('  - Se "Base encontrada" for alto: nossa busca por SKU está limitada,')
print('    a Base existe mas está sob SKU diferente — corrigir com fecho transitivo.')
print('  - Se "item_relations preenchido" for alto no órfão: a relação está')
print('    declarada NO SENTIDO INVERSO (órfão->base), não Base->órfão como assumimos.')
print('  - Se ambos forem baixos: são órfãos genuínos, o ML não declarou a relação.')