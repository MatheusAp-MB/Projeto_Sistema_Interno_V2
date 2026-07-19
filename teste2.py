import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from decimal import Decimal
from collections import Counter
from produtos.models import Produto
from tiktok.models import ConfiguracaoTiktok, FreteTiktok
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem, TabelaComissaoTiktok, GradePrecificacaoTiktok
from precificacao.funcoes_auxiliares.tiktok.formula_precificacao_tiktok import FormulaPrecificacaoTiktok
from precificacao.funcoes_auxiliares.goal_seek import arredondar_para_90

config_tiktok = ConfiguracaoTiktok.obter()
config_geral = ConfiguracaoOperacional.obter()
faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))
faixas_comissao = list(TabelaComissaoTiktok.objects.all().order_by('preco_min'))
frete_todas = list(FreteTiktok.objects.all())

MARGENS = [('minima', 10), ('padrao', 15), ('maxima', 20), ('competicao', 5)]
TIPOS = ['sem_afiliado', 'com_afiliado']

produtos = list(Produto.objects.filter(grade_precificacao_ml__isnull=False).distinct())

contador_categorias = Counter()
exemplos_por_categoria = {}

for produto in produtos:
    for tipo in TIPOS:
        for margem_chave, margem_valor in MARGENS:
            ja_resolveu = GradePrecificacaoTiktok.objects.filter(
                produto=produto, tipo=tipo, margem=margem_chave, preco__isnull=False,
            ).exists()
            if ja_resolveu:
                continue

            formula = FormulaPrecificacaoTiktok(
                produto=produto, config_tiktok=config_tiktok, config_geral=config_geral,
                margem_alvo_percentual=margem_valor, tipo=tipo,
                faixas_comissao=faixas_comissao, frete_todas=frete_todas,
                faixas_armazenagem=faixas_armazenagem,
            )
            formula.resolver_dimensao()
            formula.calcular_custo_final()
            formula.calcular_coleta()
            formula.calcular_armazenagem()
            formula.calcular_fixo()
            formula.buscar_frete()

            if formula._frete is None:
                categoria = 'SEM_FRETE'
            else:
                icms_saida = produto.icms_saida_media or Decimal('0')
                pis_cofins = produto.pis_cofins or Decimal('0')
                afiliado = config_tiktok.margem_afiliado_percentual if tipo == 'com_afiliado' else Decimal('0')
                taxa_extra = (icms_saida + pis_cofins + afiliado) / 100

                todas_denominador_invalido = True
                zona_morta = False

                for faixa in faixas_comissao:
                    comissao_fracao = faixa.comissao_percentual / 100
                    denominador = Decimal('1') - (comissao_fracao + taxa_extra) - (Decimal(str(margem_valor)) / 100)

                    if denominador <= 0:
                        continue
                    todas_denominador_invalido = False

                    preco_exato = (formula._frete + faixa.adicional_fixo + formula._fixo) / denominador
                    preco_90 = arredondar_para_90(preco_exato)

                    dentro_piso = preco_90 >= faixa.preco_min
                    dentro_teto = faixa.preco_max is None or preco_90 <= faixa.preco_max

                    if not (dentro_piso and dentro_teto):
                        zona_morta = True

                if todas_denominador_invalido:
                    categoria = 'DENOMINADOR_NEGATIVO_TODAS_FAIXAS'
                elif zona_morta:
                    categoria = 'ZONA_MORTA'
                else:
                    categoria = 'OUTRO_NAO_IDENTIFICADO'

            contador_categorias[categoria] += 1
            if categoria not in exemplos_por_categoria:
                exemplos_por_categoria[categoria] = []
            if len(exemplos_por_categoria[categoria]) < 3:
                exemplos_por_categoria[categoria].append(
                    f'{produto.sku} | {tipo} | {margem_chave} | custo={produto.custo} | FIXO={formula._fixo:.2f}'
                    + (f' | frete={formula._frete}' if formula._frete else '')
                )

print(f'\n{"=" * 70}\nRESUMO — {sum(contador_categorias.values())} casos "sem cálculo" analisados\n{"=" * 70}')
for categoria, total in contador_categorias.most_common():
    print(f'\n{categoria}: {total} casos')
    for exemplo in exemplos_por_categoria[categoria]:
        print(f'  - {exemplo}')