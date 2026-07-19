import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from precificacao.models import GradePrecificacaoML, GradePrecificacaoMagalu, GradePrecificacaoRaia, GradePrecificacaoShopee

MARGEM = 'padrao'
QUANTIDADE = 20

produtos = list(
    Produto.objects.filter(
        grade_precificacao_ml__isnull=False,
        grade_precificacao_magalu__isnull=False,
        grade_precificacao_raia__isnull=False,
        grade_precificacao_shopee__isnull=False,
    ).distinct().order_by('id')[:QUANTIDADE]
)

print(f'{"SKU":18s} {"Custo":>9s} {"ML Clássico":>13s} {"Magalu":>10s} {"Raia":>10s} {"Shopee":>10s}   Título')
print('-' * 110)

for produto in produtos:
    linha_ml = GradePrecificacaoML.objects.filter(
        produto=produto, variacao__isnull=True, tipo_anuncio='classico', margem=MARGEM,
    ).first()
    linha_magalu = GradePrecificacaoMagalu.objects.filter(produto=produto, margem=MARGEM).first()
    linha_raia = GradePrecificacaoRaia.objects.filter(produto=produto, margem=MARGEM).first()
    linha_shopee = GradePrecificacaoShopee.objects.filter(produto=produto, margem=MARGEM).first()

    def preco(linha):
        return f'R$ {linha.preco:.2f}' if linha and linha.preco else '—'

    titulo_curto = produto.titulo[:40]

    print(f'{produto.sku:18s} {produto.custo:>9.2f} {preco(linha_ml):>13s} {preco(linha_magalu):>10s} '
          f'{preco(linha_raia):>10s} {preco(linha_shopee):>10s}   {titulo_curto}')

print()
print('--- Detalhe da Shopee (faixa de comissão usada) pros mesmos 20 ---')
for produto in produtos:
    linha_shopee = GradePrecificacaoShopee.objects.filter(produto=produto, margem=MARGEM).first()
    if linha_shopee and linha_shopee.detalhamento:
        i = linha_shopee.detalhamento.get('intermediarios', {})
        print(f'{produto.sku:18s} preço R$ {linha_shopee.preco:.2f} → faixa comissão '
              f'R$ {i.get("faixa_comissao_preco_min")}-{i.get("faixa_comissao_preco_max")} '
              f'({i.get("comissao_percentual")}% + R$ {i.get("adicional_fixo")})')