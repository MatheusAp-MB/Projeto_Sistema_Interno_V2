import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from decimal import Decimal
from produtos.models import Produto
from precificacao.models import ConfiguracaoOperacional, FaixaArmazenagem, GradePrecificacaoML
from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from precificacao.funcoes_auxiliares.mercado_livre.formula_precificacao import FormulaPrecificacao


def linha(titulo):
    print(f'\n{"=" * 70}\n{titulo}\n{"=" * 70}')


linha('1. CONFIGURAÇÃO OPERACIONAL — existe, singleton, valores esperados')
config_op = ConfiguracaoOperacional.objects.first()
total_config = ConfiguracaoOperacional.objects.count()
print(f'Total de linhas: {total_config} (esperado: 1)')
if config_op:
    print(f'fator_coleta: {config_op.fator_coleta} (esperado: 72)')
    print(f'periodo_armazenagem: {config_op.periodo_armazenagem} (esperado: 30)')
else:
    print('❌ NENHUMA linha encontrada — ConfiguracaoOperacional.obter() vai criar uma na hora, mascarando o problema.')


linha('2. FAIXAS DE ARMAZENAGEM — 4 linhas, valores batendo com o original')
faixas = list(FaixaArmazenagem.objects.all().order_by('ordem'))
print(f'Total de faixas: {len(faixas)} (esperado: 4)')
esperado = [
    ('Faixa 1', Decimal('0.0070'), 12, 15, 25),
    ('Faixa 2', Decimal('0.0150'), 28, 36, 51),
    ('Faixa 3', Decimal('0.0500'), 60, 60, 70),
    ('Faixa 4', Decimal('0.1070'), 9999, 9999, 9999),
]
for i, faixa in enumerate(faixas):
    nome_esp, valor_esp, alt_esp, larg_esp, prof_esp = esperado[i]
    bate = (
        faixa.valor_diario == valor_esp
        and faixa.max_altura == alt_esp
        and faixa.max_largura == larg_esp
        and faixa.max_profundidade == prof_esp
    )
    print(f'  {faixa.nome}: valor={faixa.valor_diario} altura={faixa.max_altura} '
          f'largura={faixa.max_largura} profundidade={faixa.max_profundidade} '
          f'{"✅" if bate else "❌ DIVERGE do esperado"}')


linha('3. RASTRO DE MODELS ANTIGOS — nenhuma tabela órfã no banco')
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SHOW TABLES LIKE '%configuracaomercadolivre%'")
    r1 = cursor.fetchall()
    cursor.execute("SHOW TABLES LIKE '%faixaarmazenagemmercadolivre%'")
    r2 = cursor.fetchall()
print(f'Tabela mercado_livre_configuracaomercadolivre ainda existe? {"SIM ❌" if r1 else "Não ✅ (esperado)"}')
print(f'Tabela mercado_livre_faixaarmazenagemmercadolivre ainda existe? {"SIM ❌" if r2 else "Não ✅ (esperado)"}')


linha('4. RECÁLCULO PONTUAL — mesmo produto testado antes da refatoração')
SKU_TESTE = 'F7899947302710'  # "Meia com gel" — já validado 100% contra a planilha antes
produto = Produto.objects.filter(sku__startswith=SKU_TESTE).first()

if not produto:
    print(f'Produto {SKU_TESTE} não encontrado neste banco (pode ter sido banco recriado sem esse SKU específico).')
else:
    config_tipo = ConfiguracaoTipoAnuncioMercadoLivre.objects.filter(tipo_anuncio='gold_special').first()
    dim = resolver_dimensoes_efetivas(produto, variacao=None)
    from mercado_livre.models import FreteML
    frete_todas = list(FreteML.objects.all())

    formula = FormulaPrecificacao(
        produto=produto, dimensoes_efetivas=dim, config_tipo=config_tipo,
        config_geral=config_op, margem_alvo_percentual=config_tipo.margem_padrao,
        frete_todas=frete_todas, faixas_armazenagem=faixas,
    ).calcular()

    print(f'Produto: {produto.titulo}')
    if formula.resolvida:
        print(f'Preço calculado agora: R$ {formula.saida.preco_final}')
        print(f'Margem obtida agora: {formula.saida.margem_percentual_obtida:.2f}%')
        print('Valor esperado (validado antes da refatoração): R$ 188,90 | margem ~15,01%')
    else:
        print('❌ NÃO resolveu — algo quebrou de verdade.')

    linha_grade = GradePrecificacaoML.objects.filter(
        produto=produto, variacao__isnull=True, tipo_anuncio='classico', margem='padrao',
    ).first()
    if linha_grade:
        print(f'\nValor já persistido na Grade (do popular_banco): R$ {linha_grade.preco} | '
              f'margem {linha_grade.margem_percentual_obtida}%')
        bate = formula.resolvida and abs(formula.saida.preco_final - linha_grade.preco) < Decimal('0.02')
        print(f'Recálculo ao vivo bate com o persistido? {"✅" if bate else "❌ DIVERGE"}')