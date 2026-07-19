import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from decimal import Decimal
from collections import Counter
from produtos.models import Produto
from amazon.models import ConfiguracaoAmazon
from precificacao.models import (
    ConfiguracaoOperacional, FaixaArmazenagem, FreteAmazon, TaxaKgAdicionalAmazon,
    GradePrecificacaoAmazon,
)
from precificacao.funcoes_auxiliares.amazon.formula_precificacao_amazon import FormulaPrecificacaoAmazon

config_amazon = ConfiguracaoAmazon.obter()
config_geral = ConfiguracaoOperacional.obter()
faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))
fretes_amazon = list(FreteAmazon.objects.all())
taxas_kg_adicional = list(TaxaKgAdicionalAmazon.objects.all())

MARGENS = [('minima', 10), ('padrao', 15), ('maxima', 20), ('competicao', 5)]
TIPOS = ['dba', 'fba']

produtos = list(Produto.objects.filter(grade_precificacao_ml__isnull=False).distinct())

contador_categorias = Counter()
exemplos_por_categoria = {}

for produto in produtos:
    for tipo in TIPOS:
        for margem_chave, margem_valor in MARGENS:
            ja_resolveu = GradePrecificacaoAmazon.objects.filter(
                produto=produto, tipo=tipo, margem=margem_chave, preco__isnull=False,
            ).exists()
            if ja_resolveu:
                continue

            formula = FormulaPrecificacaoAmazon(
                produto=produto, config_amazon=config_amazon, config_geral=config_geral,
                margem_alvo_percentual=margem_valor, tipo=tipo,
                fretes_amazon=fretes_amazon, taxas_kg_adicional=taxas_kg_adicional,
                faixas_armazenagem=faixas_armazenagem,
            )
            formula.resolver_dimensao()
            formula.calcular_custo_final()
            formula.calcular_coleta()
            formula.calcular_armazenagem()
            formula.calcular_fixo()
            formula.montar_taxa_e_denominador()

            if formula._denominador <= 0:
                categoria = 'DENOMINADOR_NEGATIVO'
            else:
                nenhuma_faixa_teve_frete = True
                zona_morta = False

                for preco_min, preco_max in formula._faixas_preco_candidatas():
                    frete, _, _ = formula._frete_para_faixa(preco_min, preco_max)
                    if frete is None:
                        continue
                    nenhuma_faixa_teve_frete = False

                    from precificacao.funcoes_auxiliares.goal_seek import arredondar_para_90
                    preco_exato = (frete + formula._fixo) / formula._denominador
                    preco_90 = arredondar_para_90(preco_exato)
                    dentro_piso = preco_90 >= preco_min
                    dentro_teto = preco_max is None or preco_90 <= preco_max
                    if not (dentro_piso and dentro_teto):
                        zona_morta = True

                if nenhuma_faixa_teve_frete:
                    categoria = 'NENHUMA_FAIXA_ACHOU_FRETE'
                elif zona_morta:
                    categoria = 'ZONA_MORTA'
                else:
                    categoria = 'OUTRO_NAO_IDENTIFICADO'

            contador_categorias[categoria] += 1
            if categoria not in exemplos_por_categoria:
                exemplos_por_categoria[categoria] = []
            if len(exemplos_por_categoria[categoria]) < 3:
                exemplos_por_categoria[categoria].append(
                    f'{produto.sku} | {tipo} | {margem_chave} | custo={produto.custo} | '
                    f'FIXO={formula._fixo:.2f} | peso={formula._peso} | denom={formula._denominador}'
                )

print(f'\n{"=" * 70}\nRESUMO — {sum(contador_categorias.values())} casos "sem cálculo" analisados\n{"=" * 70}')
for categoria, total in contador_categorias.most_common():
    print(f'\n{categoria}: {total} casos')
    for exemplo in exemplos_por_categoria[categoria]:
        print(f'  - {exemplo}')