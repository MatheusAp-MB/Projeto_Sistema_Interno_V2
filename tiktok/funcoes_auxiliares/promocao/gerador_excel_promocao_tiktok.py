# tiktok/funcoes_auxiliares/promocao/gerador_excel_promocao_tiktok.py

# Função Objetivo: Gera os 2 arquivos por marca, no formato "FixedPriceWithSKU" do
# TikTok — Preço da oferta direto (já é o nosso "Por", sem cálculo nenhum).

import io
import openpyxl
from openpyxl.styles import Font

CABECALHO_PROMOCAO = [
    'Product_id (obrigatório)', 'SKU_id (obrigatório)', 'Preço da oferta (obrigatório)',
    'Limite total de compra (opcional)', 'Limite de compra do comprador (opcional)',
    'SKU', 'Produto', 'Tipo', 'Estoque',
]

LABEL_TIPO = {'sem_afiliado': 'Sem Afiliado', 'com_afiliado': 'Com Afiliado'}


def gerar_excel_promocao(resultados):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Promoção'
    ws.append(CABECALHO_PROMOCAO)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    prontos = [r for r in resultados if r.categoria == 'pronto']
    prontos_ordenados = sorted(prontos, key=lambda r: r.estoque_sistema)

    for r in prontos_ordenados:
        la, g = r.linha_arquivo, r.grade
        ws.append([
            la.product_id, la.sku_id, float(g.preco), '', '',
            r.sku, r.titulo, LABEL_TIPO.get(r.tipo, ''), r.estoque_sistema,
        ])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def gerar_excel_detalhes(resultados):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _adicionar_aba_excecao(wb, 'Preço divergente', [r for r in resultados if r.categoria == 'divergente'])
    _adicionar_aba_excecao(wb, 'Novos (sem Grade)', [r for r in resultados if r.categoria == 'novo'])
    _adicionar_aba_excecao(wb, 'Não encontrados', [r for r in resultados if r.categoria == 'nao_encontrado'])
    _adicionar_aba_excecao(wb, 'Estoque inconsistente', [r for r in resultados if r.categoria == 'estoque_inconsistente'])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _adicionar_aba_excecao(wb, nome_aba, resultados):
    ws = wb.create_sheet(nome_aba)
    ws.append(['SKU', 'Título', 'Tipo', 'Estoque (sistema)', 'Preço plataforma', 'Preço "De" (sistema)'])
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for r in resultados:
        preco_plataforma = r.linha_arquivo.preco_atual if r.linha_arquivo else None
        preco_sistema = r.grade.preco_de_exibicao if r.grade else None
        ws.append([
            r.sku, r.titulo, LABEL_TIPO.get(r.tipo, '—'), r.estoque_sistema,
            float(preco_plataforma) if preco_plataforma is not None else None,
            float(preco_sistema) if preco_sistema is not None else None,
        ])