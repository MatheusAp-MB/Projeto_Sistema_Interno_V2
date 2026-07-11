# * [RESUMO] → Importa a tabela de frete do Mercado Livre de uma planilha
#              Excel. Roda dentro do popular_banco, mas com proteção pra
#              não quebrar a importação inteira caso o arquivo não exista
#              nesse ambiente (mesma proteção já usada em Qualidade/Competição)
#              — é dado de referência raro de mudar, nem todo ambiente
#              precisa ter esse Excel disponível.

import re
from pathlib import Path
from decimal import Decimal
import openpyxl
from mercado_livre.models import FreteML

CAMINHO_TABELA_FRETE = Path('Arquivos_de_Importação/Tabela_Frete_ML.xlsx')


def _parse_faixa_preco(texto):
    # * [EXPLICAÇÃO] → Extrai os números do texto do cabeçalho, funciona
    #                  independente do formato (com/sem "R$", ponto de
    #                  milhar, vírgula decimal, traço solto no final).
    numeros = re.findall(r'[\d]+(?:[.,]\d+)?', texto)

    def to_decimal(s):
        return Decimal(s.replace('.', '').replace(',', '.'))

    preco_min = to_decimal(numeros[0]) if numeros else Decimal('0')
    preco_max = to_decimal(numeros[1]) if len(numeros) > 1 else None
    return preco_min, preco_max


def importar_tabela_frete_ml(stdout, style, caminho=CAMINHO_TABELA_FRETE):
    if not caminho.exists():
        stdout.write(
            f'[FRETE ML] Arquivo {caminho} não encontrado — pulando essa etapa.'
        )
        return

    stdout.write(f'[FRETE ML] Lendo {caminho}...')

    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]

    criados = 0
    atualizados = 0
    erros = 0

    faixas_preco = [_parse_faixa_preco(str(header[col_idx])) for col_idx in range(1, 9)]

    for row in rows[1:]:
        if not any(v is not None for v in row[:9]):
            continue

        try:
            peso_min = Decimal(str(row[9]))
            peso_max_raw = row[10]

            if peso_max_raw is not None and float(peso_max_raw) >= 999999999:
                peso_max = None
            elif peso_max_raw is not None:
                peso_max = Decimal(str(peso_max_raw))
            else:
                peso_max = None

            for col_idx, (preco_min, preco_max) in enumerate(faixas_preco):
                valor = row[col_idx + 1]
                if valor is None:
                    continue

                valor = Decimal(str(round(float(valor), 2)))

                _, criado = FreteML.objects.update_or_create(
                    peso_min=peso_min,
                    preco_min=preco_min,
                    defaults={
                        'peso_max': peso_max,
                        'preco_max': preco_max,
                        'valor': valor,
                    }
                )

                if criado:
                    criados += 1
                else:
                    atualizados += 1

        except Exception as e:
            erros += 1
            stdout.write(style.ERROR(f'  [ERRO] Linha {row[0]}: {e}'))

    stdout.write(style.SUCCESS(
        f'[FRETE ML] Concluído!\n'
        f'    Criados:     {criados}\n'
        f'    Atualizados: {atualizados}\n'
        f'    Erros:       {erros}'
    ))