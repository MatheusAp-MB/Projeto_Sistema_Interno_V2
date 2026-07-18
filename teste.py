import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

from pathlib import Path
from decimal import Decimal
import openpyxl
from produtos.models import Produto
from precificacao.models import GradePrecificacaoML
from mercado_livre.models import FreteML, ConfiguracaoTipoAnuncioMercadoLivre
from precificacao.models import ConfiguracaoOperacional
from mercado_livre.funcoes_auxiliares.dimensoes_efetivas import resolver_dimensoes_efetivas
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel

CAMINHO_PLANILHA = Path('Arquivos_de_Importação/Planilha_Importar_Pos_Macro.xlsm')

EANS_INVESTIGAR = ['7899947304547', '7899947302710']

# * [EXPLICAÇÃO] → Índices zero-based, mesmos de importar_planilha_precificacao.py
COL_EAN = 3
COL_MVA = 7
COL_ST = 8
COL_CUSTO = 9
COL_CUSTO_COM_BONI = 10
COL_FRETE_CIF_FOB = 11
COL_ICMS_ENTRADA = 12
COL_IPI = 13
COL_PIS_COFINS = 14
COL_ICMS_SAIDA_SP = 15
COL_ICMS_SAIDA_MEDIA = 16
COL_PESO_EMBALAGEM = 19
COL_ALTURA_BRUTA = 21
COL_COMPRIMENTO_BRUTO = 22
COL_LARGURA_BRUTA = 23
COL_ARMAZENAGEM = 59
COL_FRETE_PLANILHA = 57
COL_PRECO_PLANILHA = 60
COL_MARGEM_PLANILHA = 71


def linha(titulo):
    print(f'\n{"#" * 78}\n# {titulo}\n{"#" * 78}')


def sub(titulo):
    print(f'\n--- {titulo} ---')


def comparar(campo, valor_planilha, valor_banco, tolerancia=Decimal('0.05')):
    igual = '✅' if valor_planilha is not None and valor_banco is not None and abs(
        Decimal(str(valor_planilha)) - Decimal(str(valor_banco))
    ) <= tolerancia else '❌ DIVERGE'
    print(f'  {campo:35s} | planilha: {str(valor_planilha):>15s} | banco hoje: {str(valor_banco):>15s} | {igual}')


conversor = ConversorCelulaExcel(origem='openpyxl')

wb = openpyxl.load_workbook(CAMINHO_PLANILHA, read_only=True, data_only=True)
ws = wb.active
todas_linhas = list(ws.iter_rows(min_row=2, values_only=True))

planilha_por_ean = {}
for row in todas_linhas:
    ean = str(row[COL_EAN]).strip() if row[COL_EAN] else None
    if ean:
        planilha_por_ean.setdefault(ean, []).append(row)


for ean in EANS_INVESTIGAR:
    linha(f'EAN {ean}')

    produto = Produto.objects.filter(ean=ean).first()
    if not produto:
        print('  PRODUTO NÃO ENCONTRADO NO BANCO.')
        continue

    linhas_planilha = planilha_por_ean.get(ean, [])
    if not linhas_planilha:
        print('  EAN NÃO ENCONTRADO NA PLANILHA.')
        continue

    row_planilha = linhas_planilha[0]  # usa a primeira, se houver duplicata

    grade = GradePrecificacaoML.objects.filter(
        produto=produto, variacao__isnull=True, tipo_anuncio='classico', margem='padrao',
    ).first()

    sub('PRODUTO — dado bruto de HOJE')
    print(f'SKU: {produto.sku} | Título: {produto.titulo}')
    print(f'Custo: {produto.custo} | Custo com bonificação: {produto.custo_com_boni}')
    print(f'IPI: {produto.ipi} | Frete CIF/FOB: {produto.frete_cif_fob} | ST: {produto.st_valor}')
    print(f'ICMS entrada: {produto.icms_entrada} | PIS/COFINS: {produto.pis_cofins} | ICMS saída: {produto.icms_saida_media}')
    print(f'Armazenagem planilha: {produto.armazenagem_planilha}')
    print(f'Embalagem: altura={produto.altura_produto_apos_embalado} largura={produto.largura_produto_apos_embalado} '
          f'comprimento={produto.comprimento_produto_apos_embalado} peso={produto.peso_produto_apos_embalado} '
          f'peso_cubado={produto.peso_cubado}')

    sub(f'PLANILHA — linha bruta ({len(linhas_planilha)} ocorrência(s) encontrada(s))')
    custo_planilha = conversor.para_decimal(row_planilha[COL_CUSTO], casas_decimais=2)
    custo_boni_planilha = conversor.para_decimal(row_planilha[COL_CUSTO_COM_BONI], casas_decimais=2)
    ipi_planilha = conversor.para_decimal(row_planilha[COL_IPI])
    frete_cif_fob_planilha = conversor.para_decimal(row_planilha[COL_FRETE_CIF_FOB])
    st_planilha = conversor.para_decimal(row_planilha[COL_ST], casas_decimais=2)
    icms_entrada_planilha = conversor.para_decimal(row_planilha[COL_ICMS_ENTRADA])
    pis_cofins_planilha = conversor.para_decimal(row_planilha[COL_PIS_COFINS])
    icms_saida_planilha = conversor.para_decimal(row_planilha[COL_ICMS_SAIDA_MEDIA])
    armazenagem_planilha_valor = conversor.para_decimal(row_planilha[COL_ARMAZENAGEM], casas_decimais=2)
    peso_emb_planilha = conversor.para_decimal(row_planilha[COL_PESO_EMBALAGEM], casas_decimais=3)
    altura_bruta = conversor.para_decimal(row_planilha[COL_ALTURA_BRUTA], padrao=Decimal('0'), casas_decimais=2)
    comprimento_bruto = conversor.para_decimal(row_planilha[COL_COMPRIMENTO_BRUTO], padrao=Decimal('0'), casas_decimais=2)
    largura_bruta = conversor.para_decimal(row_planilha[COL_LARGURA_BRUTA], padrao=Decimal('0'), casas_decimais=2)
    altura_ord, comprimento_ord, largura_ord = sorted([altura_bruta, comprimento_bruto, largura_bruta])

    print(f'Custo: {custo_planilha} | Custo com bonificação: {custo_boni_planilha}')
    print(f'IPI (fração): {ipi_planilha} | Frete CIF/FOB (fração): {frete_cif_fob_planilha} | ST: {st_planilha}')
    print(f'ICMS entrada (fração): {icms_entrada_planilha} | PIS/COFINS (fração): {pis_cofins_planilha} | '
          f'ICMS saída (fração): {icms_saida_planilha}')
    print(f'Armazenagem: {armazenagem_planilha_valor}')
    print(f'Embalagem (ordenada menor→maior): altura={altura_ord} largura={largura_ord} '
          f'comprimento={comprimento_ord} peso={peso_emb_planilha}')

    if not grade or not grade.detalhamento:
        print('\n  SEM LINHA/DETALHAMENTO NA GRADE — não dá pra comparar contra FormulaPrecificacao.')
        continue

    e = grade.detalhamento.get('entrada', {})
    i = grade.detalhamento.get('intermediarios', {})
    s = grade.detalhamento.get('saida', {})

    sub('COMPARAÇÃO CAMPO A CAMPO — planilha (na hora que rodou) vs FormulaPrecificacao (persistido hoje)')
    comparar('Custo', custo_planilha, e.get('custo'))
    comparar('Custo com bonificação', custo_boni_planilha, e.get('custo_com_boni'))
    comparar('IPI %', ipi_planilha * 100 if ipi_planilha else None, e.get('ipi_percentual'))
    comparar('Frete CIF/FOB %', frete_cif_fob_planilha * 100 if frete_cif_fob_planilha else None, e.get('frete_cif_fob_percentual'))
    comparar('ST', st_planilha, e.get('st_valor'))
    comparar('ICMS entrada %', icms_entrada_planilha * 100 if icms_entrada_planilha else None, e.get('icms_entrada_percentual'))
    comparar('PIS/COFINS %', pis_cofins_planilha * 100 if pis_cofins_planilha else None, e.get('pis_cofins_percentual'))
    comparar('ICMS saída %', icms_saida_planilha * 100 if icms_saida_planilha else None, e.get('icms_saida_percentual'))
    comparar('Armazenagem (planilha)', armazenagem_planilha_valor, produto.armazenagem_planilha)
    comparar('Altura embalagem', altura_ord, e.get('altura'), tolerancia=Decimal('0.5'))
    comparar('Largura embalagem', largura_ord, e.get('largura'), tolerancia=Decimal('0.5'))
    comparar('Comprimento embalagem', comprimento_ord, e.get('comprimento'), tolerancia=Decimal('0.5'))
    comparar('Peso embalagem', peso_emb_planilha, e.get('peso'), tolerancia=Decimal('0.1'))

    sub('DETALHAMENTO PERSISTIDO — passo a passo completo (FormulaPrecificacao)')
    print(f'  Origem da dimensão: {e.get("origem_dimensao")}')
    print(f'  Custo final: {i.get("custo_final")}')
    print(f'  Metro cúbico: {i.get("metro_cubico")} | Coleta: {i.get("coleta")}')
    print(f'  Armazenagem (origem: {i.get("armazenagem_origem")}): {i.get("armazenagem")}')
    print(f'  FIXO: {i.get("fixo")}')
    print(f'  Taxa: {i.get("taxa_percentual")}% | Denominador: {i.get("denominador")}')
    print(f'  Faixa de frete: R$ {i.get("faixa_frete_preco_min")}-{i.get("faixa_frete_preco_max")} → '
          f'R$ {s.get("frete_usado")}')
    print(f'  Preço exato: {i.get("preco_exato_antes_arredondar")}')

    sub('RESULTADO FINAL')
    preco_planilha = conversor.para_decimal(row_planilha[COL_PRECO_PLANILHA], casas_decimais=2)
    frete_planilha_valor = conversor.para_decimal(row_planilha[COL_FRETE_PLANILHA], casas_decimais=2)
    margem_planilha_valor = conversor.para_decimal(row_planilha[COL_MARGEM_PLANILHA], casas_decimais=2)
    comparar('Preço final', preco_planilha, s.get('preco_final'), tolerancia=Decimal('0.10'))
    comparar('Frete usado', frete_planilha_valor, s.get('frete_usado'), tolerancia=Decimal('0.10'))
    comparar('Margem obtida %', margem_planilha_valor, s.get('margem_percentual_obtida'), tolerancia=Decimal('0.10'))