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
from decimal import Decimal
from django.utils import timezone
from produtos.models import Produto
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO

CAMINHO_ERP_COMPLETO = 'Arquivos_de_Importação/Relatorio_Completo_ERP.xlsx'

COLUNAS_NECESSARIAS = [
    'Codigo Auxiliar', 'Codigo de Barras', 'Codigo do Fabricante',
    'Detalhes do Produto', 'Categoria', 'Estoque', 'Marca',
    'Peso Bruto', 'Altura', 'Largura', 'Comprimento',
    'Embalagem Altura', 'Embalagem Largura', 'Embalagem Comprimento', 'Emablagem Peso',
    'Custo', 'ncm', 'URL 1', 'Ultima Compra', 'dt_cadastro',
]

# * [EXPLICAÇÃO] → 'cubicagem' foi REMOVIDA das colunas usadas — em
#                  ~60% do catálogo ela guardava o VOLUME em m³ (não
#                  peso cubado em kg), causando faixa de frete errada
#                  no Goal Seek (achado real, validado via comparação
#                  com a planilha oficial). peso_cubado agora é
#                  SEMPRE calculado aqui, nunca mais confiado do ERP.
#
#                  Descoberta real (15/07): o ERP tem 2 conjuntos de
#                  dimensão — "Altura/Largura/Comprimento" (produto
#                  PURO) e "Embalagem Altura/Largura/Comprimento"
#                  ("Emablagem Peso" — erro de digitação real na
#                  planilha) — a CAIXA de fato enviada. Frete/peso
#                  cúbico DEVEM usar embalagem (confirmado com o
#                  usuário) — nunca o produto puro.
#
#                  Os 2 conjuntos são oficialmente em METROS (mesma
#                  regra do ERP inteiro) — convertidos aqui pra
#                  centímetros (padrão único do sistema). Quando o
#                  valor de embalagem, mesmo em metros, resultar em
#                  algo fisicamente absurdo (achado real: dimensões
#                  tipo "47 metros" de embalagem), isso é ERRO DE
#                  CADASTRO NO ERP — não tentamos adivinhar/corrigir
#                  aqui, só listamos pro usuário corrigir na fonte.
FATOR_PESO_CUBADO = 6000
LIMITE_DIMENSAO_CM = Decimal('9999.99')


def _texto(valor, padrao=None):
    return str(valor).strip() if pd.notna(valor) else padrao


def _numero(valor, padrao=0):
    return valor if pd.notna(valor) else padrao


def _numero_opcional(valor):
    """Pros campos de embalagem — None (não 0) quando ausente, pra
    nunca fingir peso_cubado calculado sem dado real."""
    return valor if pd.notna(valor) else None


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
    erros_dimensao_embalagem = []

    total_linhas = len(df)

    for indice, (_, linha) in enumerate(df.iterrows(), start=1):
        if indice % 300 == 0 or indice == total_linhas:
            stdout.write(f'    ... {indice}/{total_linhas} linhas processadas')

        sku = _texto(linha.get('Codigo Auxiliar'))
        if not sku:
            continue

        # * [EXPLICAÇÃO] → O ERP entrega dimensões em METROS (unidade
        #                  oficial confirmada do ERP) — sistema inteiro
        #                  usa CENTÍMETROS como padrão único (fórmula
        #                  de peso cúbico ÷6000 é padrão internacional
        #                  de transportadoras, sempre em cm). Converte
        #                  aqui, na entrada — pros 2 conjuntos.
        altura_sem_embalar = _numero(linha.get('Altura'), 0) * 100
        largura_sem_embalar = _numero(linha.get('Largura'), 0) * 100
        comprimento_sem_embalar = _numero(linha.get('Comprimento'), 0) * 100

        altura_embalagem = _numero_opcional(linha.get('Embalagem Altura'))
        largura_embalagem = _numero_opcional(linha.get('Embalagem Largura'))
        comprimento_embalagem = _numero_opcional(linha.get('Embalagem Comprimento'))
        peso_embalagem = _numero_opcional(linha.get('Emablagem Peso'))

        if altura_embalagem is not None:
            altura_embalagem *= 100
        if largura_embalagem is not None:
            largura_embalagem *= 100
        if comprimento_embalagem is not None:
            comprimento_embalagem *= 100

        # * [EXPLICAÇÃO] → Limite do campo no banco (max_digits=6,
        #                  decimal_places=2 → até 9999,99cm ≈ 100m).
        #                  Qualquer dimensão de embalagem que estoure
        #                  isso é erro de cadastro no ERP (nenhuma
        #                  embalagem real chega nem perto disso) — vira
        #                  None (não salva valor errado) e é LISTADA
        #                  pro usuário corrigir na fonte, nunca
        #                  "adivinhada"/corrigida aqui.
        dimensoes_com_erro = []
        for nome_campo, valor in [
            ('Embalagem Altura', altura_embalagem),
            ('Embalagem Largura', largura_embalagem),
            ('Embalagem Comprimento', comprimento_embalagem),
        ]:
            if valor is not None and valor > LIMITE_DIMENSAO_CM:
                dimensoes_com_erro.append(f'{nome_campo}={valor}')

        if dimensoes_com_erro:
            erros_dimensao_embalagem.append(f'SKU {sku}: {", ".join(dimensoes_com_erro)}')
            altura_embalagem = None
            largura_embalagem = None
            comprimento_embalagem = None

        peso_cubado = None
        if altura_embalagem is not None and largura_embalagem is not None and comprimento_embalagem is not None:
            peso_cubado_calculado = (altura_embalagem * largura_embalagem * comprimento_embalagem) / FATOR_PESO_CUBADO
            # * [EXPLICAÇÃO] → Limite do campo peso_cubado (max_digits=8,
            #                  decimal_places=3 → até 99.999,999kg). Cada
            #                  dimensão individual pode passar no
            #                  LIMITE_DIMENSAO_CM e mesmo assim o
            #                  PRODUTO das 3 estourar esse limite — por
            #                  isso essa checagem é SEPARADA da anterior,
            #                  não substitui ela. Mesmo princípio: nunca
            #                  "corrige" sozinho, só lista pro ERP.
            if peso_cubado_calculado <= Decimal('99999.999'):
                peso_cubado = peso_cubado_calculado
            else:
                erros_dimensao_embalagem.append(
                    f'SKU {sku}: peso_cubado calculado ({peso_cubado_calculado:.0f}kg) '
                    f'a partir de {altura_embalagem}×{largura_embalagem}×{comprimento_embalagem} cm '
                    f'é fisicamente absurdo — verificar embalagem no ERP.'
                )

        dados = dict(
            titulo=_texto(linha.get('Detalhes do Produto'), sku),
            cod_fabricante=_texto(linha.get('Codigo do Fabricante')),
            categoria=_texto(linha.get('Categoria')),
            marca=_texto(linha.get('Marca')),
            ncm=_texto(linha.get('ncm')),
            estoque=int(_numero(linha.get('Estoque'), 0)),
            custo=_numero(linha.get('Custo'), 0),
            peso_produto_sem_embalar=_numero(linha.get('Peso Bruto'), 0),
            altura_produto_sem_embalar=altura_sem_embalar,
            largura_produto_sem_embalar=largura_sem_embalar,
            comprimento_produto_sem_embalar=comprimento_sem_embalar,
            peso_produto_apos_embalado=peso_embalagem,
            altura_produto_apos_embalado=altura_embalagem,
            largura_produto_apos_embalado=largura_embalagem,
            comprimento_produto_apos_embalado=comprimento_embalagem,
            peso_cubado=peso_cubado,
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
        f'    Ignorados (EAN duplicado na planilha): {ignorados_ean_duplicado}\n'
        f'    Dimensão de embalagem com erro de cadastro (ignorada): {len(erros_dimensao_embalagem)}'
    ))

    if erros_dimensao_embalagem:
        stdout.write(style.WARNING(
            '\n[DIMENSÕES DE EMBALAGEM COM ERRO DE CADASTRO NO ERP — CORRIGIR NA FONTE]'
        ))
        for erro in erros_dimensao_embalagem:
            stdout.write(style.WARNING(f'    {erro}'))