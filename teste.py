import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from mercado_livre.models import (
    ConfiguracaoMercadoLivre, ConfiguracaoTipoAnuncioMercadoLivre,
    FaixaArmazenagemMercadoLivre, FreteML, TipoDeAnuncioMercadoLivre,
)
from precificacao.models import GradePrecificacaoML
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas

SKU = 'F7908050719121.001'


def linha(titulo):
    print(f'\n{"=" * 70}\n{titulo}\n{"=" * 70}')


produto = Produto.objects.get(sku=SKU)

linha('PRODUTO — dado bruto')
print(f'SKU: {produto.sku}')
print(f'EAN: {produto.ean}')
print(f'Título: {produto.titulo}')
print(f'Custo: {produto.custo}')
print(f'Custo com bonificação: {produto.custo_com_boni}')
print(f'IPI: {produto.ipi}')
print(f'Frete CIF/FOB: {produto.frete_cif_fob}')
print(f'ST: {produto.st_valor}')
print(f'ICMS entrada: {produto.icms_entrada}')
print(f'PIS/COFINS: {produto.pis_cofins}')
print(f'ICMS saída (média): {produto.icms_saida_media}')
print(f'Armazenagem planilha: {produto.armazenagem_planilha}')
print()
print('--- Dimensão SEM embalar (produto puro) ---')
print(f'Altura: {produto.altura_produto_sem_embalar} | Largura: {produto.largura_produto_sem_embalar} | '
      f'Comprimento: {produto.comprimento_produto_sem_embalar} | Peso: {produto.peso_produto_sem_embalar}')
print()
print('--- Dimensão APÓS embalado (usada na Grade, via fallback ERP) ---')
print(f'Altura: {produto.altura_produto_apos_embalado} | Largura: {produto.largura_produto_apos_embalado} | '
      f'Comprimento: {produto.comprimento_produto_apos_embalado} | Peso: {produto.peso_produto_apos_embalado}')
print(f'Peso cúbico (já calculado): {produto.peso_cubado}')


linha('VARIAÇÕES/MLBs — dado bruto de cada anúncio publicado')
variacoes = list(produto.variacoes_mercado_livre.select_related('anuncio__tipo_de_anuncio').all())
print(f'Total de variações vinculadas a este produto: {len(variacoes)}')

for v in variacoes:
    anuncio = v.anuncio
    tipo = anuncio.tipo_de_anuncio.tipo_anuncio if anuncio.tipo_de_anuncio else 'SEM TIPO'
    print(f'\n  MLB {anuncio.mlb} | tipo: {tipo} | variação: {v.variacao_id}')
    print(f'    sku_ml: {v.sku_ml} | título do anúncio: {anuncio.titulo_anuncio}')
    print(f'    Dimensão declarada: altura={v.altura_declarada_cm} largura={v.largura_declarada_cm} '
          f'comprimento={v.comprimento_declarado_cm} peso={v.peso_declarado_kg}')


linha('DIMENSOES EFETIVAS — o que resolver_dimensoes_efetivas() decide de verdade')
print('--- Fallback do produto (variacao=None) ---')
dim_fallback = resolver_dimensoes_efetivas(produto, variacao=None)
print(f'  origem: {dim_fallback.origem.value}')
print(f'  altura={dim_fallback.altura} largura={dim_fallback.largura} '
      f'comprimento={dim_fallback.comprimento} peso={dim_fallback.peso}')

for v in variacoes:
    dim = resolver_dimensoes_efetivas(produto, variacao=v)
    print(f'\n--- MLB {v.anuncio.mlb} (variação {v.variacao_id}) ---')
    print(f'  origem: {dim.origem.value}')
    print(f'  altura={dim.altura} largura={dim.largura} comprimento={dim.comprimento} peso={dim.peso}')


linha('CONFIGURAÇÃO — comissão e margens por tipo de anúncio')
TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
for tipo_valor, tipo_nome in [(TipoAnuncio.CLASSICO, 'Clássico'), (TipoAnuncio.PREMIUM, 'Premium')]:
    config = ConfiguracaoTipoAnuncioMercadoLivre.objects.filter(tipo_anuncio=tipo_valor).first()
    if config:
        print(f'\n{tipo_nome}:')
        print(f'  Comissão: {config.comissao}%')
        print(f'  Margem mínima: {config.margem_minima}% | padrão: {config.margem_padrao}% | '
              f'máxima: {config.margem_maxima}% | competição: {config.margem_competicao}%')
    else:
        print(f'\n{tipo_nome}: SEM CONFIGURAÇÃO CADASTRADA')

config_geral = ConfiguracaoMercadoLivre.obter()
print(f'\nFator de coleta: {config_geral.fator_coleta}')
print(f'Período de armazenagem: {config_geral.periodo_armazenagem} dias')


linha('FAIXAS DE ARMAZENAGEM')
for f in FaixaArmazenagemMercadoLivre.objects.filter(ativo=True).order_by('ordem'):
    print(f'  {f.nome}: até {f.max_altura}×{f.max_largura}×{f.max_profundidade}cm — R$ {f.valor_diario}/dia')


linha('FAIXAS DE FRETE — só as relevantes pros pesos deste produto')
pesos_relevantes = {dim_fallback.peso} | {resolver_dimensoes_efetivas(produto, v).peso for v in variacoes}
for peso in sorted(pesos_relevantes):
    print(f'\n--- Peso {peso}kg ---')
    faixas = FreteML.objects.filter(peso_min__lte=peso).filter(
        peso_max__gte=peso
    ) | FreteML.objects.filter(peso_min__lte=peso, peso_max__isnull=True)
    for f in faixas.order_by('preco_min'):
        teto = f.preco_max if f.preco_max is not None else 'sem teto'
        print(f'  peso {f.peso_min}-{f.peso_max or "sem teto"} | preço R$ {f.preco_min}-{teto} → R$ {f.valor}')


linha('GRADE DE PRECIFICAÇÃO ML — resultado já persistido')
linhas_grade = GradePrecificacaoML.objects.filter(produto=produto).select_related('variacao__anuncio').order_by(
    'variacao_id', 'tipo_anuncio', 'margem'
)
print(f'Total de linhas: {linhas_grade.count()}')

for g in linhas_grade:
    alvo = f'MLB {g.variacao.anuncio.mlb}' if g.variacao_id else 'FALLBACK (sem MLB)'
    print(f'\n  {alvo} | {g.tipo_anuncio} | margem {g.margem}')
    print(f'    Preço: R$ {g.preco} | Margem obtida: {g.margem_percentual_obtida}% | '
          f'Frete usado: R$ {g.frete_usado} | Origem dimensão: {g.origem_dimensao}')