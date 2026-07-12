import os
import json
from pathlib import Path

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from mercado_livre.models import VariacaoAnuncioMercadoLivre

ARQUIVO_AMOSTRA = Path("Arquivos_API/amostra_promocoes.json")

with open(ARQUIVO_AMOSTRA, encoding="utf-8") as f:
    dados = json.load(f)

mlbs_na_amostra = []
for grupo in dados.get("fase2_grupos", []):
    for m in grupo.get("mlbs", []):
        mlbs_na_amostra.append(m["mlb"])

variacoes = VariacaoAnuncioMercadoLivre.objects.filter(
    anuncio__mlb__in=mlbs_na_amostra,
    produto__marca='ORTHO PAUHER',
    anuncio__competicao__status='competing',
).select_related('anuncio', 'anuncio__competicao', 'produto').distinct()

print(f'Total encontrado: {variacoes.count()}\n')

for v in variacoes:
    comp = v.anuncio.competicao
    print(
        f"SKU: {v.produto.sku} | MLB: {v.anuncio.mlb} | "
        f"Preço atual: R$ {comp.current_price} | Preço p/ ganhar: R$ {comp.price_to_win} | "
        f"Título: {v.anuncio.titulo_anuncio}"
    )