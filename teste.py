import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from magalu.models import ConfiguracaoMagalu, FreteMagalu
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem
from precificacao.funcoes_auxiliares.magalu.formula_precificacao_magalu import FormulaPrecificacaoMagalu

SKU_TESTE = 'F7899947302710'  # "Meia com gel" — mesmo produto já validado 100% no ML


def linha(titulo):
    print(f'\n{"=" * 70}\n{titulo}\n{"=" * 70}')


produto = Produto.objects.filter(sku__startswith=SKU_TESTE).first()
if not produto:
    print(f'Produto {SKU_TESTE} não encontrado neste banco.')
    raise SystemExit

config_magalu = ConfiguracaoMagalu.obter()
config_geral = ConfiguracaoOperacional.obter()
frete_todas = list(FreteMagalu.objects.all())
faixas_armazenagem = list(FaixaArmazenagem.objects.filter(ativo=True).order_by('ordem'))

linha('CONFIGURAÇÃO USADA')
print(f'Comissão Magalu: {config_magalu.comissao_percentual}%')
print(f'Faixa de reputação atual: {config_magalu.get_faixa_reputacao_atual_display()}')
print(f'Fator de coleta: {config_geral.fator_coleta} | Período de armazenagem: {config_geral.periodo_armazenagem} dias')
print(f'Faixas de frete carregadas: {len(frete_todas)}')

linha(f'PRODUTO — {produto.titulo}')
print(f'Custo: {produto.custo} | Custo c/ boni: {produto.custo_com_boni}')
print(f'Embalagem: altura={produto.altura_produto_apos_embalado} largura={produto.largura_produto_apos_embalado} '
      f'comprimento={produto.comprimento_produto_apos_embalado} peso={produto.peso_produto_apos_embalado} '
      f'peso_cubado={produto.peso_cubado}')

for margem_chave, label in [('competicao', 'Competição'), ('minima', 'Mínima'), ('padrao', 'Padrão'), ('maxima', 'Máxima')]:
    from precificacao.models import GradePrecificacaoMagalu
    margem_valor = {
        'competicao': 5, 'minima': 10, 'padrao': 15, 'maxima': 20,
    }[margem_chave]

    formula = FormulaPrecificacaoMagalu(
        produto=produto, config_magalu=config_magalu, config_geral=config_geral,
        margem_alvo_percentual=margem_valor, frete_todas=frete_todas,
        faixas_armazenagem=faixas_armazenagem,
    ).calcular()

    linha(f'MARGEM {label.upper()} ({margem_valor}%)')

    if not formula.resolvida:
        print('❌ NÃO resolveu — meta inatingível ou sem faixa de frete pro peso.')
        continue

    print(f'Dimensão resolvida: {formula.entrada.altura}×{formula.entrada.largura}×{formula.entrada.comprimento}cm, '
          f'peso efetivo {formula.entrada.peso}kg')
    print()
    for passo in formula.passos():
        print(f"  {passo['ordem']}. {passo['rotulo']}: {passo['formula']} → {passo['resultado']}")

    print()
    print(f'Preço final: R$ {formula.saida.preco_final} | Margem obtida: {formula.saida.margem_percentual_obtida:.2f}% '
          f'| Margem exata (antes do arredondar): {formula.saida.margem_exata_percentual:.2f}%')

    print('✅ Margem obtida >= margem-alvo — já garantido pelo assert dentro de resolver_preco_com_frete_fixo')