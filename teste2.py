"""
teste2.py — Diagnóstico componente por componente de 1 produto
específico, pra achar a origem exata da diferença de preço restante.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from produtos.models import Produto
from mercado_livre.models import ConfiguracaoTipoAnuncioMercadoLivre, TipoDeAnuncioMercadoLivre, FreteML
from mercado_livre.funcoes_auxiliares.calculo_margem import calcular_fixo, calcular_metro_cubico
from precificacao.models import GradePrecificacaoML

p = Produto.objects.get(ean='7899947320752')
print('--- Produto no banco ---')
for campo in ['custo', 'custo_com_boni', 'frete_cif_fob', 'icms_entrada', 'ipi',
              'pis_cofins', 'icms_saida_media', 'peso', 'peso_cubado',
              'altura', 'largura', 'profundidade', 'armazenagem_planilha']:
    print(f'  {campo} = {getattr(p, campo, None)!r}')

print()
print('metro_cubico =', calcular_metro_cubico(p))
print('FIXO calculado =', calcular_fixo(p))

TipoAnuncio = TipoDeAnuncioMercadoLivre.TipoAnuncio
TipoLogistico = TipoDeAnuncioMercadoLivre.TipoLogistico
config = ConfiguracaoTipoAnuncioMercadoLivre.objects.get(
    tipo_anuncio=TipoAnuncio.CLASSICO, tipo_logistico=TipoLogistico.COLETA, catalogo=True
)
print()
print('--- Config Clássico/Coleta/Catálogo ---')
print('comissao =', config.comissao)
print('margem_padrao =', config.margem_padrao)

peso = max(p.peso or 0, p.peso_cubado or 0)
print()
print('peso usado (max peso/cubado) =', peso)
faixas = FreteML.objects.filter(peso_min__lte=peso).filter(peso_max__gte=peso)
for f in faixas:
    print(f'  faixa: peso {f.peso_min}-{f.peso_max} | preco {f.preco_min}-{f.preco_max} | valor={f.valor}')

print()
print('--- Linha da Grade calculada pro sistema ---')
g = GradePrecificacaoML.objects.get(produto=p, tipo_anuncio=config, margem_alvo='padrao')
print('preco_calculado =', g.preco_calculado)
print('margem_percentual_obtida =', g.margem_percentual_obtida)