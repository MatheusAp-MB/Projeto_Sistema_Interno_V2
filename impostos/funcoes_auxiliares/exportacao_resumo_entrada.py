# impostos/funcoes_auxiliares/exportacao_resumo_entrada.py

# Função Objetivo: Gera o .xlsx de Impostos de Entrada (10 grupos, 52
# colunas, 1 cor por grupo do cabeçalho até a última linha de dado) — mesma
# estrutura de scripts_exploracao_ERP/relatorio_impostos_entrada_xlsx.py,
# só que lendo tudo direto do banco (16/08/2026): os 8 campos que antes só
# existiam no json de apoio (ID Produto Sysemp, Código Auxiliar, CFOP,
# Origem, Natureza da Operação, TES de Saída) já são colunas persistidas
# desde a Rodada 2 (15/08/2026) — sem merge de arquivo, sem chamada à API.
# Todo cálculo "por unidade" vem de obter_detalhes_para_exibicao() (mesma
# função que o modal do produto usa) — nunca recalculado aqui de novo.
#
# O script antigo continua existindo, intocado, por decisão do usuário
# (16/08/2026) — mantido só pra rodar local sem precisar do servidor. Isso
# significa que a lista/cor de grupos abaixo existe hoje em 2 lugares; se
# o script antigo for aposentado no futuro, dá pra apontar ele pra cá.

import io
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

LEGENDA = (
    'Base de Cálculo e Valor de qualquer imposto nesta planilha são sempre por unidade do '
    'produto — nunca o total da nota (1 única lógica, sem mistura). Cada grupo de colunas tem '
    'sua própria cor, do cabeçalho até a última linha de dado. Colunas marcadas "—": produto '
    'ainda não reprocessado desde que esses campos passaram a ser persistidos (15/08/2026).'
)

GRUPOS_DE_COLUNAS = [
    ('Identificação da Nota', ['Nota Fiscal', 'Fornecedor', 'Empresa', 'Data de Emissão', 'Data de Entrada'], '1F4E78'),
    ('Identificação do Produto', [
        'ID Produto (Sysemp)', 'Produto', 'Código de Barras', 'Código Auxiliar',
        'Código do Fabricante', 'Quantidade Recebida na Nota',
    ], '0E6655'),
    ('Custos', ['Custo Unitário', 'Custo Total da Nota'], '1B5E20'),
    ('Classificação Fiscal (XML × Cadastro)', [
        'NCM (XML)', 'NCM (Cadastro)', 'CFOP (XML)', 'CFOP (Cadastro)',
        'Origem da Mercadoria (XML)', 'Origem da Mercadoria (Cadastro)',
        'Natureza da Operação (Cadastro)', 'TES de Saída (Cadastro)',
    ], '5B2C6F'),
    ('ICMS', ['CST (XML)', 'CST (Cadastro)', 'Base de Cálculo', 'Alíquota', 'Redução', 'Valor'], '7D5B0A'),
    ('ICMS ST', ['Base de Cálculo', 'Alíquota', 'Redução', 'Valor', '% FCP', 'Valor FCP'], 'A24E0A'),
    ('ICMS Retido', ['Base de Cálculo', 'Valor'], '8B2E12'),
    ('IPI', ['CST (XML)', 'CST (Cadastro)', 'Base de Cálculo', 'Alíquota', 'Valor'], '205E7A'),
    ('PIS', ['CST (XML)', 'CST (Cadastro)', 'Base de Cálculo', 'Alíquota', 'Redução', 'Valor'], '7B241C'),
    ('COFINS', ['CST (XML)', 'CST (Cadastro)', 'Base de Cálculo', 'Alíquota', 'Redução', 'Valor'], '8E2452'),
]
TOTAL_DE_COLUNAS = sum(len(colunas) for _, colunas, _ in GRUPOS_DE_COLUNAS)


def _clarear(cor_hex: str, fator: float) -> str:
    r, g, b = int(cor_hex[0:2], 16), int(cor_hex[2:4], 16), int(cor_hex[4:6], 16)
    r = round(r + (255 - r) * fator)
    g = round(g + (255 - g) * fator)
    b = round(b + (255 - b) * fator)
    return f'{r:02X}{g:02X}{b:02X}'


def _indices_das_colunas(nomes_alvo: set) -> tuple:
    indices = []
    indice_atual = 1
    for _, colunas, _ in GRUPOS_DE_COLUNAS:
        for nome_coluna in colunas:
            if nome_coluna in nomes_alvo:
                indices.append(indice_atual)
            indice_atual += 1
    return tuple(indices)


COLUNAS_DE_DATA = _indices_das_colunas({'Data de Emissão', 'Data de Entrada'})
COLUNAS_QUE_PODEM_FALTAR = _indices_das_colunas({
    'ID Produto (Sysemp)', 'Código Auxiliar', 'CFOP (XML)', 'CFOP (Cadastro)',
    'Origem da Mercadoria (XML)', 'Origem da Mercadoria (Cadastro)',
    'Natureza da Operação (Cadastro)', 'TES de Saída (Cadastro)',
})


def _construir_cores_de_dado_por_coluna() -> list:
    cores = []
    for _, colunas, cor_base in GRUPOS_DE_COLUNAS:
        tom_impar = _clarear(cor_base, 0.90)
        tom_par = _clarear(cor_base, 0.82)
        cores += [(tom_impar, tom_par)] * len(colunas)
    return cores


CORES_DE_DADO_POR_COLUNA = _construir_cores_de_dado_por_coluna()


def _escrever_legenda(planilha):
    celula = planilha.cell(row=1, column=1, value=LEGENDA)
    celula.font = Font(italic=True, size=9, color='555555')
    planilha.merge_cells(start_row=1, start_column=1, end_row=1, end_column=TOTAL_DE_COLUNAS)
    planilha.row_dimensions[1].height = 18


def _escrever_cabecalho(planilha):
    coluna_atual = 1
    for titulo_grupo, colunas, cor_base in GRUPOS_DE_COLUNAS:
        inicio = coluna_atual
        fim = coluna_atual + len(colunas) - 1
        cor_subcabecalho = _clarear(cor_base, 0.75)

        celula_grupo = planilha.cell(row=2, column=inicio, value=titulo_grupo)
        celula_grupo.font = Font(bold=True, color='FFFFFF', size=11)
        celula_grupo.alignment = Alignment(horizontal='center', vertical='center')
        if fim > inicio:
            planilha.merge_cells(start_row=2, start_column=inicio, end_row=2, end_column=fim)
        for coluna in range(inicio, fim + 1):
            planilha.cell(row=2, column=coluna).fill = PatternFill('solid', fgColor=cor_base)

        for indice, nome_coluna in enumerate(colunas):
            celula_coluna = planilha.cell(row=3, column=inicio + indice, value=nome_coluna)
            celula_coluna.font = Font(bold=True, size=10)
            celula_coluna.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            celula_coluna.fill = PatternFill('solid', fgColor=cor_subcabecalho)

        coluna_atual = fim + 1

    for coluna in range(1, TOTAL_DE_COLUNAS + 1):
        planilha.column_dimensions[get_column_letter(coluna)].width = 15
    planilha.row_dimensions[3].height = 32
    planilha.freeze_panes = 'A4'


# Função Objetivo: Monta a linha completa (52 valores, na ordem de
# GRUPOS_DE_COLUNAS) de 1 produto — tudo vindo de obter_detalhes_para_exibicao()
# (mesma conversão "por unidade" que o modal usa) mais os 3 campos que só
# existem no Produto (titulo, ean, cod_fabricante).
def _montar_linha(produto):
    detalhes = produto.impostos_entrada.obter_detalhes_para_exibicao()
    por_imposto = {linha.nome: linha for linha in detalhes.linhas}

    valores = [
        detalhes.nr_nf, detalhes.fornecedor, detalhes.empresa_fantasia,
        detalhes.emissao, detalhes.data_entrada_nota,
    ]
    valores += [
        detalhes.id_produto_sysemp, produto.titulo, produto.ean, detalhes.codigo_auxiliar,
        produto.cod_fabricante, detalhes.quantidade_nota,
    ]
    valores += [detalhes.custo_unitario, detalhes.custo_total]
    valores += [
        detalhes.ncm_xml, detalhes.ncm_cadastro, detalhes.cfop_xml, detalhes.cfop_cadastro,
        detalhes.origem_mercadoria_xml, detalhes.origem_mercadoria_cadastro,
        detalhes.natureza_operacao_cadastro, detalhes.tes_saida_cadastro,
    ]

    icms = por_imposto['ICMS']
    valores += [icms.cst_xml, icms.cst_cadastro, icms.base_calculo, icms.aliquota, icms.reducao, icms.valor]

    icms_st = por_imposto['ICMS ST']
    valores += [
        icms_st.base_calculo, icms_st.aliquota, icms_st.reducao,
        icms_st.valor, icms_st.aliquota_fcp, icms_st.valor_fcp,
    ]

    icms_ret = por_imposto['ICMS Retido']
    valores += [icms_ret.base_calculo, icms_ret.valor]

    ipi = por_imposto['IPI']
    valores += [ipi.cst_xml, ipi.cst_cadastro, ipi.base_calculo, ipi.aliquota, ipi.valor]

    pis = por_imposto['PIS']
    valores += [pis.cst_xml, pis.cst_cadastro, pis.base_calculo, pis.aliquota, pis.reducao, pis.valor]

    cofins = por_imposto['COFINS']
    valores += [cofins.cst_xml, cofins.cst_cadastro, cofins.base_calculo, cofins.aliquota, cofins.reducao, cofins.valor]

    return valores


# Função Objetivo: Gera o .xlsx completo em memória (bytes), pronto pra
# devolver numa HttpResponse de download — sem escrever em disco.
def gerar_excel_resumo_impostos_entrada(produtos) -> bytes:
    livro = openpyxl.Workbook()
    planilha = livro.active
    planilha.title = 'Impostos de Entrada'
    _escrever_legenda(planilha)
    _escrever_cabecalho(planilha)

    linha_atual = 4
    for produto in produtos:
        for indice, valor in enumerate(_montar_linha(produto), start=1):
            eh_campo_ausente = indice in COLUNAS_QUE_PODEM_FALTAR and valor is None
            valor_para_exibir = '—' if eh_campo_ausente else valor
            celula = planilha.cell(row=linha_atual, column=indice, value=valor_para_exibir)

            tom_impar, tom_par = CORES_DE_DADO_POR_COLUNA[indice - 1]
            celula.fill = PatternFill('solid', fgColor=(tom_par if linha_atual % 2 == 0 else tom_impar))

            if indice in COLUNAS_DE_DATA and isinstance(valor, date):
                celula.number_format = 'DD/MM/YYYY'
            if eh_campo_ausente:
                celula.font = Font(italic=True, color='999999')

        linha_atual += 1

    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()