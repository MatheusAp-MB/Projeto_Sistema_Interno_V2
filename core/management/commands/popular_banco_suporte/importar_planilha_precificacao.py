# * [RESUMO] → Importa os dados VALIDADOS de precificação (custo, fiscais,
#              dimensões) de uma planilha Excel específica — diferente da
#              Planilha_do_ML_Sysemp (dado geral do ERP) e do Relatório
#              Completo ERP (dado geral também). Essa aqui é a fonte
#              validada especificamente para cálculo de margem/preço —
#              testada e aprovada, mapeamento por índice de coluna
#              (não por nome de cabeçalho, igual ao original).
#              Roda por ÚLTIMO no popular_banco — precisa "vencer" a
#              disputa dos mesmos campos com importar_produtos_erp_completo.
#              Casa por EAN (mesma chave do sistema antigo validado).

import openpyxl
from pathlib import Path
from decimal import Decimal
from produtos.models import Produto

CAMINHO_PLANILHA_PRECIFICACAO = Path('Arquivos_de_Importação/Planilha_Importar_Pos_Macro.xlsm')


def _pct(val):
    # * [EXPLICAÇÃO] → Converte decimal para percentual (0.04 → 4.00) —
    #                  campos fiscais dessa planilha vêm em formato decimal.
    if val is None:
        return Decimal('0')
    return Decimal(str(round(float(val) * 100, 2)))


def _dec(val, default=None):
    if val is None:
        return default
    return Decimal(str(round(float(val), 2)))


def _dec3(val, default='0'):
    if val is None:
        return Decimal(default)
    return Decimal(str(round(float(val), 3)))


def _seguro(val):
    # * [EXPLICAÇÃO] → Retorna None se for erro de fórmula do Excel
    #                  (#N/A, #REF!, etc) — evita quebrar a importação.
    if val is None:
        return None
    if isinstance(val, str) and val.strip().startswith('#'):
        return None
    return val


def importar_planilha_precificacao(stdout, style, caminho=CAMINHO_PLANILHA_PRECIFICACAO):
    if not caminho.exists():
        stdout.write(style.WARNING(
            f'[PRECIFICAÇÃO — PLANILHA VALIDADA] Arquivo {caminho} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[PRECIFICAÇÃO — PLANILHA VALIDADA] Lendo {caminho}...')

    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    ws = wb['Planilha1']

    produtos_por_ean = {p.ean: p for p in Produto.objects.all()}

    para_atualizar = []
    sem_produto_correspondente = 0
    ignorados = 0
    erros = 0
    total_linhas = 0

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
        if not any(v is not None for v in row[:10]):
            ignorados += 1
            continue

        total_linhas += 1

        try:
            ean = str(row[3]).strip() if row[3] else None
            if not ean:
                ignorados += 1
                continue

            produto = produtos_por_ean.get(ean)
            if not produto:
                sem_produto_correspondente += 1
                continue

            produto.custo = _dec(_seguro(row[9]), Decimal('0'))
            produto.custo_com_boni = _dec(_seguro(row[10]))
            produto.frete_cif_fob = _pct(_seguro(row[11]))
            produto.mva = _dec(_seguro(row[7]))
            produto.st_valor = _dec(_seguro(row[8]))
            produto.icms_entrada = _pct(_seguro(row[12]))
            produto.ipi = _pct(_seguro(row[13]))
            produto.pis_cofins = _pct(_seguro(row[14]))
            produto.icms_saida_sp = _pct(_seguro(row[15]))
            produto.icms_saida_media = _pct(_seguro(row[16]))
            produto.peso = _dec3(_seguro(row[19]))
            produto.altura = _dec(_seguro(row[21]), Decimal('0'))
            produto.profundidade = _dec(_seguro(row[22]), Decimal('0'))
            produto.largura = _dec(_seguro(row[23]), Decimal('0'))
            produto.armazenagem_planilha = _dec(_seguro(row[59]))

            para_atualizar.append(produto)

        except Exception as e:
            erros += 1
            stdout.write(style.ERROR(f'  [ERRO] Linha {i + 2}: {e}'))

    campos = [
        'custo', 'custo_com_boni', 'frete_cif_fob', 'mva', 'st_valor',
        'icms_entrada', 'ipi', 'pis_cofins', 'icms_saida_sp', 'icms_saida_media',
        'peso', 'altura', 'profundidade', 'largura', 'armazenagem_planilha',
    ]

    if para_atualizar:
        Produto.objects.bulk_update(para_atualizar, campos, batch_size=1000)

    stdout.write(style.SUCCESS(
        f'[PRECIFICAÇÃO — PLANILHA VALIDADA] Concluído!\n'
        f'    Linhas processadas: {total_linhas}\n'
        f'    Produtos atualizados: {len(para_atualizar)}\n'
        f'    Sem produto correspondente (EAN não achado): {sem_produto_correspondente}\n'
        f'    Ignorados: {ignorados}\n'
        f'    Erros: {erros}'
    ))