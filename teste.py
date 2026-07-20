import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

import sys
import openpyxl
from decimal import Decimal
from precificacao.funcoes_auxiliares.exportacao.config_marketplaces_exportaveis import MARKETPLACES_EXPORTAVEIS_POR_CHAVE

# ==== CONFIGURA AQUI ANTES DE RODAR ====
CAMINHO_ARQUIVO = 'Precificacao_Shopee_20_07_26.xlsx'
MARKETPLACE_CHAVE = 'shopee'   # mercado_livre | magalu | raia | shopee | tiktok | amazon
TIPO = None                     # 'classico'/'premium', 'sem_afiliado'/'com_afiliado', 'dba'/'fba' — None se não tiver
MARGEM = 'padrao'               # minima | padrao | maxima | competicao
# ========================================

marketplace = MARKETPLACES_EXPORTAVEIS_POR_CHAVE.get(MARKETPLACE_CHAVE)
if not marketplace:
    print(f'Marketplace "{MARKETPLACE_CHAVE}" não encontrado no registro.')
    sys.exit(1)

wb = openpyxl.load_workbook(CAMINHO_ARQUIVO, data_only=True)
ws = wb.active
linhas_arquivo = list(ws.iter_rows(min_row=2, values_only=True))
print(f'Arquivo tem {len(linhas_arquivo)} linhas de dado.')

condicoes = {'margem': MARGEM, **marketplace.filtro_extra}
if marketplace.campo_tipo:
    condicoes[marketplace.campo_tipo] = TIPO

linhas_banco = marketplace.model.objects.filter(**condicoes, preco__isnull=False).select_related('produto')
banco_por_ean = {g.produto.ean: g for g in linhas_banco}
print(f'Banco tem {len(banco_por_ean)} linhas com essa combinação (marketplace/tipo/margem).')

erros = []
eans_do_arquivo = set()

for i, (ean, titulo, custo, preco) in enumerate(linhas_arquivo, start=2):
    eans_do_arquivo.add(ean)
    grade = banco_por_ean.get(ean)

    if grade is None:
        erros.append(f'Linha {i}: EAN {ean} está no arquivo mas NÃO tem Grade no banco pra essa combinação.')
        continue

    if grade.produto.titulo != titulo:
        erros.append(f'Linha {i}: EAN {ean} — título diferente. Arquivo="{titulo}" Banco="{grade.produto.titulo}"')

    if Decimal(str(grade.produto.custo)) != Decimal(str(custo)):
        erros.append(f'Linha {i}: EAN {ean} — custo diferente. Arquivo={custo} Banco={grade.produto.custo}')

    if Decimal(str(grade.preco)) != Decimal(str(preco)):
        erros.append(f'Linha {i}: EAN {ean} — preço diferente. Arquivo={preco} Banco={grade.preco}')

eans_faltando_no_arquivo = set(banco_por_ean.keys()) - eans_do_arquivo
if eans_faltando_no_arquivo:
    print(f'\n⚠ {len(eans_faltando_no_arquivo)} produto(s) existem no banco (nessa combinação) mas NÃO aparecem no arquivo.')
    print('  (Esperado se você filtrou por marca na hora de exportar — só estranhe se não filtrou.)')
    for ean in list(eans_faltando_no_arquivo)[:10]:
        print(f'   - {ean}')

print(f'\n{"=" * 60}')
if erros:
    print(f'❌ {len(erros)} inconsistência(s) encontrada(s):\n')
    for erro in erros[:50]:
        print(f'  {erro}')
    if len(erros) > 50:
        print(f'  ... e mais {len(erros) - 50}')
else:
    print('✅ Nenhuma inconsistência — arquivo bate 100% com o banco pra essa combinação.')