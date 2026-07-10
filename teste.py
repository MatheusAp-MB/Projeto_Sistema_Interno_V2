import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from django.db.models import Q
from mercado_livre.models import VariacaoAnuncioMercadoLivre
from mercado_livre.funcoes_auxiliares.classificacao_catalogo import (
    listar_skus_filtrados, carregar_variacoes_por_sku,
)

termo = 'politriz'

# MLBs que o CABEÇALHO considera (bateram a busca de verdade)
qs_busca = VariacaoAnuncioMercadoLivre.objects.exclude(anuncio__eh_fossil_migracao=True).filter(
    Q(produto__sku__icontains=termo) |
    Q(produto__marca__icontains=termo) |
    Q(produto__titulo__icontains=termo) |
    Q(produto__ean__icontains=termo) |
    Q(anuncio__mlb__icontains=termo) |
    Q(anuncio__titulo_anuncio__icontains=termo)
)
mlbs_do_cabecalho = set(qs_busca.values_list('anuncio__mlb', flat=True).distinct())
print('MLBs no cabeçalho:', len(mlbs_do_cabecalho))

# MLBs que aparecem de fato na árvore (todas as variações dos 6 SKUs)
skus, _ = listar_skus_filtrados(busca=termo, filtros={})
variacoes_por_sku = carregar_variacoes_por_sku(skus=skus)
mlbs_da_arvore = set()
for variacoes in variacoes_por_sku.values():
    for v in variacoes:
        mlbs_da_arvore.add(v.anuncio.mlb)
print('MLBs na árvore:', len(mlbs_da_arvore))

print()
print('MLB(s) que estão na árvore mas NÃO bateram a busca:', mlbs_da_arvore - mlbs_do_cabecalho)