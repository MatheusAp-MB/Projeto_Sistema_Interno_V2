# precificacao/funcoes_auxiliares/exportacao/gerador_excel_exportacao_precos.py

# Função Objetivo: Gera o .xlsx simples de exportação — EAN, Título, Custo, Preço de
# venda — pronto pra importar no ERP. Formato de entrada padronizada (sempre nessa
# ordem de coluna), já que o ERP espera colunas numa ordem fixa.

import io
import openpyxl
from openpyxl.styles import Font

CABECALHO = ['Código de Barras', 'Título do Produto', 'Custo', 'Preço de Venda']


def gerar_excel_exportacao_precos(linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Precificação'
    ws.append(CABECALHO)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for linha in linhas:
        ws.append([linha.ean, linha.titulo, float(linha.custo), float(linha.preco)])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()