# core/management/commands/popular_banco_suporte/importar_produtos_erp_completo.py

# * [RESUMO] → Enriquece Produto com dados do relatório completo do ERP
#              (só produtos ATIVOS, mas mais atual que a planilha
#              enxuta). Roda DEPOIS de importar_produtos_ml — aquele
#              cobre todos os SKUs (ativos e inativos) com poucos
#              campos; este atualiza com dado real e mais completo.
#              Casa por SKU (Codigo Auxiliar), não por EAN.
#              NUNCA sobrescreve: curva (preenchida manualmente pelo
#              usuário) nem os campos fiscais sem fonte confirmada
#              ainda (custo_com_boni, mva, st_valor, icms_entrada,
#              icms_saida_sp, icms_saida_media, ipi, pis_cofins,
#              frete_cif_fob).

import pandas as pd
from django.utils import timezone
from produtos.models import Produto

CAMINHO_ERP_COMPLETO = 'Arquivos_de_Importação/Relatorio_Completo_ERP.xlsx'

COLUNAS_NECESSARIAS = [
    'Codigo Auxiliar', 'Codigo de Barras', 'Codigo do Fabricante',
    'Detalhes do Produto', 'Categoria', 'Estoque', 'Marca',
    'Peso Bruto', 'Altura', 'Largura', 'Comprimento',
    'Custo', 'ncm', 'URL 1', 'Ultima Compra', 'dt_cadastro',
]

# * [EXPLICAÇÃO] → 'cubicagem' foi REMOVIDA das colunas usadas — em
#                  ~60% do catálogo ela guardava o VOLUME em m³ (não
#                  peso cubado em kg), causando faixa de frete errada
#                  no Goal Seek (achado real, validado em 26/07 via
#                  comparação com a planilha oficial). peso_cubado
#                  agora é SEMPRE calculado aqui, nunca mais confiado
#                  do ERP: (altura × largura × profundidade) ÷ 6000.
FATOR_PESO_CUBADO = 6000


def _texto(valor, padrao=None):
    return str(valor).strip() if pd.notna(valor) else padrao


def _numero(valor, padrao=0):
    return valor if pd.notna(valor) else padrao

def _data(valor):
    if pd.isna(valor):
        return None
    # * [EXPLICAÇÃO] → Algumas linhas do ERP têm data "suja" (ex:
    #                  "01-07-2026 ( 0002 )", com número de pedido
    #                  colado). dayfirst=True porque o ERP usa formato
    #                  brasileiro (dia/mês/ano). errors='coerce' faz
    #                  virar "sem data" em vez de travar a importação
    #                  inteira por causa de algumas linhas sujas.
    resultado = pd.to_datetime(valor, dayfirst=True, errors='coerce')
    if pd.isna(resultado):
        return None
    resultado = resultado.to_pydatetime()
    # * [EXPLICAÇÃO] → USE_TZ=True exige datetime "ciente" de fuso —
    #                  sem isso, o Django avisa (e guarda o valor de um
    #                  jeito que pode ficar inconsistente internamente).
    if timezone.is_naive(resultado):
        resultado = timezone.make_aware(resultado)
    return resultado


def importar_produtos_erp_completo(stdout, style, caminho=CAMINHO_ERP_COMPLETO):
    stdout.write(f'[ERP COMPLETO] Lendo {caminho}...')

    df = pd.read_excel(caminho)
    df = df[COLUNAS_NECESSARIAS]
    stdout.write(f'    {len(df)} linhas no relatório')

    produtos_por_sku = {p.sku: p for p in Produto.objects.exclude(sku__isnull=True)}
    produtos_por_ean = {p.ean: p for p in Produto.objects.all()}

    para_criar = []
    para_atualizar = []
    sem_ean_para_criar = 0
    ignorados_ean_duplicado = 0
    eans_ja_enfileirados = set()

    total_linhas = len(df)

    for indice, (_, linha) in enumerate(df.iterrows(), start=1):
        if indice % 300 == 0 or indice == total_linhas:
            stdout.write(f'    ... {indice}/{total_linhas} linhas processadas')

        sku = _texto(linha.get('Codigo Auxiliar'))
        if not sku:
            continue

        altura = _numero(linha.get('Altura'), 0)
        largura = _numero(linha.get('Largura'), 0)
        profundidade = _numero(linha.get('Comprimento'), 0)

        dados = dict(
            titulo=_texto(linha.get('Detalhes do Produto'), sku),
            cod_fabricante=_texto(linha.get('Codigo do Fabricante')),
            categoria=_texto(linha.get('Categoria')),
            marca=_texto(linha.get('Marca')),
            ncm=_texto(linha.get('ncm')),
            estoque=int(_numero(linha.get('Estoque'), 0)),
            custo=_numero(linha.get('Custo'), 0),
            peso=_numero(linha.get('Peso Bruto'), 0),
            altura=altura,
            largura=largura,
            profundidade=profundidade,
            peso_cubado=(altura * largura * profundidade) / FATOR_PESO_CUBADO,
            imagem_url=_texto(linha.get('URL 1')),
            ultima_compra=_data(linha.get('Ultima Compra')),
            cadastrado_erp_em=_data(linha.get('dt_cadastro')),
        )

        ean = _texto(linha.get('Codigo de Barras'))

        # * [EXPLICAÇÃO] → Sku desta planilha (Codigo Auxiliar) nem
        #                  sempre bate com Produto.sku (que vem da API
        #                  do ML, fonte diferente) — por isso, se não
        #                  achar por SKU, tenta achar pelo EAN antes de
        #                  decidir que é um produto novo. Sem isso,
        #                  tentaríamos criar um Produto com EAN que já
        #                  existe em outro registro, e o banco recusa
        #                  (EAN é único).
        existente = produtos_por_sku.get(sku) or (produtos_por_ean.get(ean) if ean else None)

        if existente:
            for campo, valor in dados.items():
                setattr(existente, campo, valor)
            para_atualizar.append(existente)
        else:
            if not ean:
                sem_ean_para_criar += 1
                continue
            if ean in eans_ja_enfileirados:
                ignorados_ean_duplicado += 1
                continue
            eans_ja_enfileirados.add(ean)
            para_criar.append(Produto(sku=sku, ean=ean, **dados))

    if para_criar:
        from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
        Produto.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)

    if para_atualizar:
        campos = list(dados.keys())
        Produto.objects.bulk_update(para_atualizar, campos, batch_size=BATCH_SIZE_PADRAO)

    stdout.write('')
    stdout.write(style.SUCCESS(
        f'[ERP COMPLETO] Concluído!\n'
        f'    Criados:     {len(para_criar)}\n'
        f'    Atualizados: {len(para_atualizar)}\n'
        f'    Sem EAN (não criados): {sem_ean_para_criar}\n'
        f'    Ignorados (EAN duplicado na planilha): {ignorados_ean_duplicado}'
    ))