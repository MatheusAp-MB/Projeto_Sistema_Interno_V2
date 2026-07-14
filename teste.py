"""
teste.py — Diagnóstico dos 2 casos genuínos de divergência Clássico,
testando TODAS as faixas de frete candidatas (não só a que o sistema
escolheu), pra ver se existe ambiguidade de múltiplas faixas
consistentes, e se a planilha "escolheu" outra.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from decimal import Decimal
from produtos.models import Produto
from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML
from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_fixo
from precificacao.funcoes_auxiliares.goal_seek import arredondar_para_90
from precificacao.models import GradePrecificacaoML

EANS = {
    '7899947304547': 'LOCALIZADOR ACHA VEIA — planilha=420.90 vs sistema=426.90',
    '7898415012137': 'ALMOFADA ORTOPÉDICA LOMBAR — planilha=194.90 vs sistema=195.90',
}

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
TipoLogistico = TipoDeAnuncioMercadoLivre.TipoLogistico
MARGEM_ALVO = Decimal('15.00')
TAXA_ICMS_PIS = Decimal('0')  # ajustado abaixo por produto

for ean, descricao in EANS.items():
    p = Produto.objects.get(ean=ean)
    print('=' * 70)
    print(f'{ean} — {descricao}')
    print('=' * 70)

    print('--- Dados do produto ---')
    for campo in ['custo', 'custo_com_boni', 'peso', 'peso_cubado', 'icms_entrada',
                  'ipi', 'pis_cofins', 'icms_saida_media', 'frete_cif_fob', 'altura', 'largura', 'profundidade']:
        print(f'  {campo} = {getattr(p, campo, None)!r}')

    fixo = calcular_fixo(p)
    print(f'\nFIXO = {fixo}')

    config = ConfiguracaoTipoAnuncioMercadoLivre.objects.get(
        tipo_anuncio=TipoAnuncio.CLASSICO, tipo_logistico=TipoLogistico.COLETA, catalogo=True
    )
    comissao = config.comissao / 100
    icms_pis = (p.icms_saida_media or Decimal('0')) / 100 + (p.pis_cofins or Decimal('0')) / 100
    taxa = comissao + icms_pis
    denominador = 1 - taxa - (MARGEM_ALVO / 100)
    print(f'comissão={config.comissao}% taxa_total={taxa} denominador={denominador}')

    peso = max(p.peso or Decimal('0'), p.peso_cubado or Decimal('0'))
    print(f'peso usado = {peso}')

    faixas = FreteML.objects.filter(peso_min__lte=peso).filter(peso_max__gte=peso).order_by('preco_min')

    print('\n--- Testando TODAS as faixas (não só a primeira que bate) ---')
    custo_produto = p.custo_com_boni or p.custo
    consistentes = []
    for faixa in faixas:
        if faixa.preco_max is not None and faixa.preco_max < custo_produto:
            print(f'  [pulada, abaixo do custo] {faixa.preco_min}-{faixa.preco_max} frete={faixa.valor}')
            continue
        preco_exato = (faixa.valor + fixo) / denominador
        preco_90 = arredondar_para_90(preco_exato)
        cabe = faixa.preco_min <= preco_90 and (faixa.preco_max is None or preco_90 <= faixa.preco_max)
        marca = '✓ CONSISTENTE' if cabe else ''
        print(f'  {faixa.preco_min}-{faixa.preco_max} frete={faixa.valor} → preco_exato={preco_exato:.2f} → RoundUp90={preco_90} {marca}')
        if cabe:
            consistentes.append(preco_90)

    print(f'\nFaixas consistentes encontradas: {consistentes}')

    g = GradePrecificacaoML.objects.get(produto=p, tipo_anuncio=config, margem_alvo='padrao')
    print(f'Preço que o SISTEMA escolheu (primeira consistente): {g.preco_calculado} (margem {g.margem_percentual_obtida}%)')
    print()