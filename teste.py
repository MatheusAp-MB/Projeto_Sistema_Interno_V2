import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from tabulate import tabulate
from produtos.models import Produto
from precificacao.models import (
    GradePrecificacaoML, GradePrecificacaoMagalu, GradePrecificacaoRaia,
    GradePrecificacaoShopee, GradePrecificacaoTiktok,
)

MARGEM = 'padrao'
QUANTIDADE = 20

produtos = list(
    Produto.objects.filter(
        grade_precificacao_ml__isnull=False,
        grade_precificacao_magalu__isnull=False,
        grade_precificacao_raia__isnull=False,
        grade_precificacao_shopee__isnull=False,
        grade_precificacao_tiktok__isnull=False,
    ).distinct().order_by('id')[:QUANTIDADE]
)


def preco(linha):
    return f'R$ {linha.preco:.2f}' if linha and linha.preco else '—'


print(f'\n{"=" * 20} TABELA COMPARATIVA — margem "{MARGEM}" {"=" * 20}\n')

linhas_tabela = []
for produto in produtos:
    linha_ml = GradePrecificacaoML.objects.filter(
        produto=produto, variacao__isnull=True, tipo_anuncio='classico', margem=MARGEM,
    ).first()
    linha_magalu = GradePrecificacaoMagalu.objects.filter(produto=produto, margem=MARGEM).first()
    linha_raia = GradePrecificacaoRaia.objects.filter(produto=produto, margem=MARGEM).first()
    linha_shopee = GradePrecificacaoShopee.objects.filter(produto=produto, margem=MARGEM).first()
    linha_tiktok_sem = GradePrecificacaoTiktok.objects.filter(
        produto=produto, margem=MARGEM, tipo='sem_afiliado',
    ).first()
    linha_tiktok_com = GradePrecificacaoTiktok.objects.filter(
        produto=produto, margem=MARGEM, tipo='com_afiliado',
    ).first()

    linhas_tabela.append([
        produto.sku,
        produto.titulo[:35],
        f'{produto.custo:.2f}',
        preco(linha_ml),
        preco(linha_magalu),
        preco(linha_raia),
        preco(linha_shopee),
        preco(linha_tiktok_sem),
        preco(linha_tiktok_com),
    ])

print(tabulate(
    linhas_tabela,
    headers=['SKU', 'Título', 'Custo', 'ML Clássico', 'Magalu', 'Raia', 'Shopee', 'TikTok S/Afil', 'TikTok C/Afil'],
    tablefmt='simple_outline',
))


print(f'\n{"=" * 20} DETALHE — faixa de comissão usada (Shopee) {"=" * 20}\n')

linhas_shopee = []
for produto in produtos:
    linha_shopee = GradePrecificacaoShopee.objects.filter(produto=produto, margem=MARGEM).first()
    if linha_shopee and linha_shopee.detalhamento:
        i = linha_shopee.detalhamento.get('intermediarios', {})
        linhas_shopee.append([
            produto.sku,
            f'R$ {linha_shopee.preco:.2f}',
            f'R$ {i.get("faixa_comissao_preco_min")}-{i.get("faixa_comissao_preco_max")}',
            f'{i.get("comissao_percentual")}%',
            f'R$ {i.get("adicional_fixo")}',
        ])

print(tabulate(linhas_shopee, headers=['SKU', 'Preço', 'Faixa de preço', 'Comissão', 'Adicional fixo'], tablefmt='simple_outline'))


print(f'\n{"=" * 20} DETALHE — faixa de comissão usada (TikTok, sem afiliado) {"=" * 20}\n')

linhas_tiktok = []
for produto in produtos:
    linha_tiktok = GradePrecificacaoTiktok.objects.filter(
        produto=produto, margem=MARGEM, tipo='sem_afiliado',
    ).first()
    if linha_tiktok and linha_tiktok.detalhamento:
        i = linha_tiktok.detalhamento.get('intermediarios', {})
        linhas_tiktok.append([
            produto.sku,
            f'R$ {linha_tiktok.preco:.2f}',
            f'R$ {i.get("faixa_comissao_preco_min")}-{i.get("faixa_comissao_preco_max")}',
            f'{i.get("comissao_percentual")}%',
            f'R$ {i.get("adicional_fixo")}',
            f'R$ {linha_tiktok.frete_usado}',
        ])

print(tabulate(
    linhas_tiktok,
    headers=['SKU', 'Preço', 'Faixa de preço', 'Comissão', 'Adicional fixo', 'Frete (peso)'],
    tablefmt='simple_outline',
))