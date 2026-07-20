import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

import json
from produtos.models import Produto
from precificacao.models import (
    GradePrecificacaoML, GradePrecificacaoMagalu, GradePrecificacaoRaia,
    GradePrecificacaoShopee, GradePrecificacaoTiktok, GradePrecificacaoAmazon,
)

MARGEM = 'padrao'
LIMITE_CUSTO_SANIDADE = 5000  # exclui erros de cadastro tipo o carro (custo > R$260 mil)

def peso_efetivo(p):
    fisico = p.peso_produto_apos_embalado or 0
    cubico = p.peso_cubado or 0
    return max(fisico, cubico)

print('Buscando todos os candidatos...', flush=True)

# --- Base: produtos com cálculo nos 6 marketplaces, custo sadio ---
ids_ml = set(GradePrecificacaoML.objects.filter(variacao__isnull=True, margem=MARGEM, preco__isnull=False).values_list('produto_id', flat=True))
ids_magalu = set(GradePrecificacaoMagalu.objects.filter(margem=MARGEM, preco__isnull=False).values_list('produto_id', flat=True))
ids_raia = set(GradePrecificacaoRaia.objects.filter(margem=MARGEM, preco__isnull=False).values_list('produto_id', flat=True))
ids_shopee = set(GradePrecificacaoShopee.objects.filter(margem=MARGEM, preco__isnull=False).values_list('produto_id', flat=True))
ids_tiktok = set(GradePrecificacaoTiktok.objects.filter(margem=MARGEM, preco__isnull=False).values_list('produto_id', flat=True))
ids_amazon = set(GradePrecificacaoAmazon.objects.filter(margem=MARGEM, preco__isnull=False).values_list('produto_id', flat=True))
ids_comuns = ids_ml & ids_magalu & ids_raia & ids_shopee & ids_tiktok & ids_amazon

produtos_completos = list(Produto.objects.filter(id__in=ids_comuns, custo__lt=LIMITE_CUSTO_SANIDADE))
print(f'Produtos completos e sadios: {len(produtos_completos)}', flush=True)

# --- 1. Custo zero (complementar — só pra mostrar o efeito puro do frete) ---
custo_zero = min(produtos_completos, key=lambda p: p.custo)

# --- 2. Leve realista (custo > 0, mas baixo, peso baixo) ---
candidatos_realistas = [p for p in produtos_completos if p.custo > 5 and peso_efetivo(p) < 1]
leve_realista = min(candidatos_realistas, key=lambda p: p.custo) if candidatos_realistas else None

# --- 3. Médio ---
custos_ordenados = sorted(produtos_completos, key=lambda p: p.custo)
medio = custos_ordenados[len(custos_ordenados) // 2]

# --- 4. Pesado, perto de 10kg (sem passar) ---
pesado_perto_10kg = min(produtos_completos, key=lambda p: abs(peso_efetivo(p) - 10))

# --- 5. ML dimensão declarada na plataforma ---
ml_dimensao_declarada = None
for linha in GradePrecificacaoML.objects.filter(margem=MARGEM, tipo_anuncio='classico', variacao__isnull=False).select_related('produto'):
    det = linha.detalhamento or {}
    if det.get('entrada', {}).get('origem_dimensao') == 'variacao_ml' and linha.produto.custo < LIMITE_CUSTO_SANIDADE:
        ml_dimensao_declarada = linha.produto
        break

# --- 6. Magalu: peso médio + origens de armazenagem diferentes ---
linhas_magalu = [l for l in GradePrecificacaoMagalu.objects.filter(margem=MARGEM).select_related('produto') if l.produto.custo < LIMITE_CUSTO_SANIDADE]
magalu_ordenado = sorted(linhas_magalu, key=lambda l: peso_efetivo(l.produto))
magalu_peso_medio = magalu_ordenado[len(magalu_ordenado) // 2].produto

magalu_origem_planilha = None
magalu_origem_faixa = None
for linha in linhas_magalu:
    origem = (linha.detalhamento or {}).get('intermediarios', {}).get('armazenagem_origem')
    if origem == 'planilha' and not magalu_origem_planilha:
        magalu_origem_planilha = linha.produto
    if origem == 'faixa_dimensao' and not magalu_origem_faixa:
        magalu_origem_faixa = linha.produto
    if magalu_origem_planilha and magalu_origem_faixa:
        break

# --- 7. Shopee: comissão alta (faixa barata) e comissão baixa (faixa cara), sem lixo ---
shopee_comissao_alta = GradePrecificacaoShopee.objects.filter(
    margem=MARGEM, preco__lt=79.99, produto__custo__lt=LIMITE_CUSTO_SANIDADE
).select_related('produto').order_by('preco').first()
shopee_comissao_baixa = GradePrecificacaoShopee.objects.filter(
    margem=MARGEM, preco__gte=100, produto__custo__lt=LIMITE_CUSTO_SANIDADE
).select_related('produto').order_by('-preco').first()

# --- 8. TikTok: peso alto DENTRO do limite de 30kg (exemplo "limpo") ---
tiktok_peso_alto_dentro_limite = None
linhas_tiktok_validas = [
    l for l in GradePrecificacaoTiktok.objects.filter(margem=MARGEM, tipo='sem_afiliado').select_related('produto')
    if l.produto.custo < LIMITE_CUSTO_SANIDADE and 10 <= peso_efetivo(l.produto) <= 30
]
if linhas_tiktok_validas:
    tiktok_peso_alto_dentro_limite = max(linhas_tiktok_validas, key=lambda l: peso_efetivo(l.produto)).produto

# --- 9. Amazon: faixa fixa 50-78,99 (sem peso) ---
amazon_50_78 = None
for linha in GradePrecificacaoAmazon.objects.filter(margem=MARGEM, tipo='dba', produto__custo__lt=LIMITE_CUSTO_SANIDADE).select_related('produto').order_by('preco'):
    if 50 <= linha.preco <= 78.99:
        amazon_50_78 = linha.produto
        break

# --- 10. Amazon: peso genuinamente acima de 10kg (kg adicional disparando) ---
amazon_acima_10kg = None
maior_peso_achado = 10
for p in Produto.objects.filter(grade_precificacao_amazon__isnull=False, custo__lt=LIMITE_CUSTO_SANIDADE).distinct().iterator():
    peso = peso_efetivo(p)
    if peso > maior_peso_achado:
        if GradePrecificacaoAmazon.objects.filter(produto=p, tipo='dba', margem=MARGEM, preco__isnull=False).exists():
            amazon_acima_10kg = p
            maior_peso_achado = peso

candidatos = {
    'CUSTO_ZERO_COMPLEMENTAR': custo_zero,
    'LEVE_REALISTA': leve_realista,
    'MEDIO': medio,
    'PESADO_PERTO_10KG': pesado_perto_10kg,
    'ML_DIMENSAO_DECLARADA': ml_dimensao_declarada,
    'MAGALU_PESO_MEDIO': magalu_peso_medio,
    'MAGALU_ORIGEM_PLANILHA': magalu_origem_planilha,
    'MAGALU_ORIGEM_FAIXA': magalu_origem_faixa,
    'SHOPEE_COMISSAO_ALTA': shopee_comissao_alta.produto if shopee_comissao_alta else None,
    'SHOPEE_COMISSAO_BAIXA': shopee_comissao_baixa.produto if shopee_comissao_baixa else None,
    'TIKTOK_PESO_ALTO_DENTRO_LIMITE': tiktok_peso_alto_dentro_limite,
    'AMAZON_50_78_FIXO': amazon_50_78,
    'AMAZON_ACIMA_10KG': amazon_acima_10kg,
}

print('\n=== CANDIDATOS FINAIS ===')
for papel, p in candidatos.items():
    if p:
        print(f'{papel}: {p.sku} | custo={p.custo} | peso_efetivo={peso_efetivo(p)}kg | {p.titulo[:50]}')
    else:
        print(f'{papel}: NENHUM CANDIDATO ENCONTRADO')

def linha_ml(produto, tipo_anuncio):
    return GradePrecificacaoML.objects.filter(
        produto=produto, variacao__isnull=True, tipo_anuncio=tipo_anuncio, margem=MARGEM,
    ).first()

def dump_completo(produto):
    dados = {'sku': produto.sku, 'titulo': produto.titulo, 'custo': str(produto.custo),
              'peso_efetivo': str(peso_efetivo(produto))}

    l_classico = linha_ml(produto, 'classico')
    l_premium = linha_ml(produto, 'premium')
    l_magalu = GradePrecificacaoMagalu.objects.filter(produto=produto, margem=MARGEM).first()
    l_raia = GradePrecificacaoRaia.objects.filter(produto=produto, margem=MARGEM).first()
    l_shopee = GradePrecificacaoShopee.objects.filter(produto=produto, margem=MARGEM).first()
    l_tiktok_sem = GradePrecificacaoTiktok.objects.filter(produto=produto, tipo='sem_afiliado', margem=MARGEM).first()
    l_tiktok_com = GradePrecificacaoTiktok.objects.filter(produto=produto, tipo='com_afiliado', margem=MARGEM).first()
    l_amazon_dba = GradePrecificacaoAmazon.objects.filter(produto=produto, tipo='dba', margem=MARGEM).first()
    l_amazon_fba = GradePrecificacaoAmazon.objects.filter(produto=produto, tipo='fba', margem=MARGEM).first()

    for chave, linha in [
        ('ml_classico', l_classico), ('ml_premium', l_premium), ('magalu', l_magalu),
        ('raia', l_raia), ('shopee', l_shopee), ('tiktok_sem_afiliado', l_tiktok_sem),
        ('tiktok_com_afiliado', l_tiktok_com), ('amazon_dba', l_amazon_dba), ('amazon_fba', l_amazon_fba),
    ]:
        dados[chave] = linha.detalhamento if (linha and linha.detalhamento) else None

    return dados

resultado_final = {papel: dump_completo(p) for papel, p in candidatos.items() if p is not None}

with open('dump_documento_formulas_final.json', 'w', encoding='utf-8') as f:
    json.dump(resultado_final, f, indent=2, default=str, ensure_ascii=False)

print(f'\nArquivo final gerado com {len(resultado_final)} produtos — me manda esse arquivo, é o único que preciso agora.')