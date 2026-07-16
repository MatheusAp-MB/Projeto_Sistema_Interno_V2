# core/management/commands/popular_banco_suporte/importar_produtos_ml.py

# * [RESUMO] → Popula Produto a partir do cruzamento entre a lista real
#              de SKUs do Mercado Livre (detalhes_mlbs.json — API bruta)
#              e os dados do ERP (Produtos_do_ML_Sysemp.xlsx).
#              SKU vem do ML (fonte da lista de produtos reais);
#              EAN, Cód. Fabricante, Título, Marca, Categoria, Estoque,
#              Imagem vêm do ERP. Preço é ignorado — não interessa a
#              Produto. SKU sem correspondência no ERP não é importado,
#              apenas logado.

import json
import pandas as pd
from produtos.models import Produto
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO

CAMINHO_ERP = 'Arquivos_de_Importação/Produtos_do_ML_Sysemp.xlsx'


def importar_produtos_ml(stdout, style, caminho_json):
    stdout.write(f'[PRODUTOS ML] Lendo {caminho_json}...')

    with open(caminho_json, encoding='utf-8') as f:
        dados = json.load(f)

    registros = dados.get('registros', [])
    skus_unicos = {r.get('sku') for r in registros if r.get('sku')}
    stdout.write(f'    {len(registros)} registros → {len(skus_unicos)} SKUs únicos no ML')

    stdout.write(f'[PRODUTOS ML] Lendo {CAMINHO_ERP}...')
    df_erp = pd.read_excel(CAMINHO_ERP)
    df_erp = df_erp.rename(columns={'SKU na Plataforma': 'SKU'})
    df_erp = df_erp[[
        'SKU', 'Código de Barras', 'Código Fabricante',
        'Descrição do Produto', 'Categoria', 'Estoque', 'Marca', 'Imagem 1',
    ]]
    erp_por_sku = {row['SKU']: row for _, row in df_erp.iterrows()}
    stdout.write(f'    {len(erp_por_sku)} SKUs no arquivo do ERP')

    # ================================================
    # CARREGA PRODUTOS EXISTENTES EM MEMÓRIA
    # ================================================
    produtos_por_ean = {p.ean: p for p in Produto.objects.all()}

    para_criar = {}
    para_atualizar = {}
    sem_ean = 0

    skus_unicos = list(skus_unicos)
    total_skus = len(skus_unicos)

    for indice, sku in enumerate(skus_unicos, start=1):
        if indice % 500 == 0 or indice == total_skus:
            stdout.write(f'    ... {indice}/{total_skus} SKUs processados')
        linha_erp = erp_por_sku.get(sku)

        if linha_erp is None or pd.isna(linha_erp.get('Código de Barras')):
            sem_ean += 1
            continue

        ean = str(linha_erp['Código de Barras']).strip()

        dados_produto = dict(
            sku=sku,
            cod_fabricante=str(linha_erp['Código Fabricante']).strip() if pd.notna(linha_erp.get('Código Fabricante')) else None,
            titulo=str(linha_erp['Descrição do Produto']).strip() if pd.notna(linha_erp.get('Descrição do Produto')) else sku,
            categoria=str(linha_erp['Categoria']).strip() if pd.notna(linha_erp.get('Categoria')) else None,
            estoque=int(linha_erp['Estoque']) if pd.notna(linha_erp.get('Estoque')) else 0,
            marca=str(linha_erp['Marca']).strip() if pd.notna(linha_erp.get('Marca')) else None,
            imagem_url=str(linha_erp['Imagem 1']).strip() if pd.notna(linha_erp.get('Imagem 1')) else None,
        )

        existente = produtos_por_ean.get(ean)
        if existente:
            for campo, valor in dados_produto.items():
                setattr(existente, campo, valor)
            para_atualizar[ean] = existente
        else:
            # * [EXPLICAÇÃO] → custo/peso/altura/largura/profundidade são
            #                  obrigatórios no model e ainda não são
            #                  conhecidos nesta etapa — ficam como
            #                  placeholder até um comando futuro (ERP
            #                  completo) preencher com dado real.
            para_criar[ean] = Produto(
                ean=ean, custo=0, peso=0, altura=0, largura=0, profundidade=0,
                **dados_produto
            )

    if para_criar:
        Produto.objects.bulk_create(list(para_criar.values()), batch_size=BATCH_SIZE_PADRAO)

    if para_atualizar:
        campos = list(dados_produto.keys())
        Produto.objects.bulk_update(list(para_atualizar.values()), campos, batch_size=BATCH_SIZE_PADRAO)

    stdout.write('')
    stdout.write(style.SUCCESS(
        f'[PRODUTOS ML] Concluído!\n'
        f'    Criados:     {len(para_criar)}\n'
        f'    Atualizados: {len(para_atualizar)}\n'
        f'    Sem EAN (não importados): {sem_ean}'
    ))