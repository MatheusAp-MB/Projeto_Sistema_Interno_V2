# scripts_exploracao_ERP/relatorio_impostos_entrada_xlsx.py

# Função Objetivo: Gera 1 planilha Excel, 1 linha por produto, com os
# impostos de entrada (XML/Sysemp) já sincronizados no banco — uso único
# e pontual, pedido pelo usuário. NÃO adiciona nenhum campo novo ao banco:
# os 4 campos que só existem no XML cru (ID Produto Sysemp, NCM, Origem,
# Origem Descrição — todos de nível de NOTA, podem divergir do cadastro)
# são lidos direto do json já salvo em disco por uma sincronização
# anterior (XML_Manifesto_NF_notas_mais_recentes_por_produto.json).
# Tudo o mais (CST, Alíquota, Redução, Custo Unitário, Custo Final) vem
# do banco, via o mesmo método já usado no modal de produto.

import os
import sys
from datetime import date
from decimal import Decimal


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')
django.setup()

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rich.console import Console

from integracao_sysemp.servicos.arquivos_retorno_api import NOME_ARQUIVO_NOTAS_MAIS_RECENTES, ler_json
from integracao_sysemp.servicos.dados_xml_nf import IdentificacaoProduto, IdentificadorRegra
from produtos.models import Produto

CAMPO_CODIGO_PRODUTO = 'Código Barras'
CAMINHO_SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saidas', 'Relatorio_Impostos_Entrada.xlsx')

# * [EXPLICAÇÃO] → Fonte única desta estrutura — a ordem/nome dos grupos
#                  e colunas aqui é exatamente o que vai pro Excel. Os 6
#                  impostos repetem o mesmo padrão (CST, Alíquota,
#                  Redução) mesmo sabendo que ICMS ST não tem CST, ICMS
#                  Retido não tem nenhum dos 3, e IPI não tem Redução —
#                  ficam "—" nesses casos, mesma convenção já usada no
#                  modal de produto (campo ausente nunca é omitido, só
#                  fica em branco).
GRUPOS_DE_COLUNAS = [
    ('Identificador do Produto', ['ID Produto', 'Marca', 'EAN', 'SKU', 'Título', 'Cód. Fabricante']),
    ('Identificador da Nota Fiscal', ['Nota Fiscal', 'Data Entrada', 'Data Emissão', 'Fornecedor']),
    ('Custos', ['Custo Unitário', 'Custo Final\n(Custo + IPI + ST)']),
    ('Identificadores Tributários', ['NCM', 'Origem', 'Origem Descrição']),
    ('ICMS', ['CST', 'Alíquota', 'Redução']),
    ('ICMS ST', ['CST', 'Alíquota', 'Redução']),
    ('ICMS Retido', ['CST', 'Alíquota', 'Redução']),
    ('IPI', ['CST', 'Alíquota', 'Redução']),
    ('PIS', ['CST', 'Alíquota', 'Redução']),
    ('COFINS', ['CST', 'Alíquota', 'Redução']),
]
TOTAL_DE_COLUNAS = sum(len(colunas) for _, colunas in GRUPOS_DE_COLUNAS)
COLUNAS_DE_DATA = (8, 9)  # Data Entrada, Data Emissão (posição na linha, 1-indexado)


# Função Objetivo: Monta as 2 linhas de cabeçalho (grupo mesclado + coluna) a partir de GRUPOS_DE_COLUNAS.
def _escrever_cabecalho(planilha):
    coluna_atual = 1
    for titulo_grupo, colunas in GRUPOS_DE_COLUNAS:
        inicio = coluna_atual
        fim = coluna_atual + len(colunas) - 1

        celula_grupo = planilha.cell(row=1, column=inicio, value=titulo_grupo)
        celula_grupo.font = Font(bold=True, color='FFFFFF')
        celula_grupo.fill = PatternFill('solid', fgColor='1F4E78')
        celula_grupo.alignment = Alignment(horizontal='center')
        if fim > inicio:
            planilha.merge_cells(start_row=1, start_column=inicio, end_row=1, end_column=fim)

        for indice, nome_coluna in enumerate(colunas):
            celula_coluna = planilha.cell(row=2, column=inicio + indice, value=nome_coluna)
            celula_coluna.font = Font(bold=True)
            celula_coluna.alignment = Alignment(horizontal='center', wrap_text=True)

        coluna_atual = fim + 1

    for indice in range(1, TOTAL_DE_COLUNAS + 1):
        planilha.column_dimensions[get_column_letter(indice)].width = 16
    planilha.freeze_panes = 'A3'


# Função Objetivo: Devolve a linha (LinhaImpostoEntrada) de 1 imposto específico, pelo nome.
def _linha_do_imposto(detalhes, nome_imposto):
    for linha in detalhes.linhas:
        if linha.nome == nome_imposto:
            return linha
    raise ValueError(f'Imposto "{nome_imposto}" não encontrado em detalhes.linhas.')


# Função Objetivo: Custo Final = Custo Unitário + Valor IPI + Valor ICMS ST (todos por unidade).
# Devolve None se qualquer uma das 3 partes ainda não existir (produto pendente de
# reprocessamento) — nunca mascara com 0, isso subestimaria o resultado silenciosamente.
def _calcular_custo_final(detalhes) -> Decimal | None:
    valor_ipi = _linha_do_imposto(detalhes, 'IPI').valor
    valor_icms_st = _linha_do_imposto(detalhes, 'ICMS ST').valor
    if detalhes.custo_unitario is None or valor_ipi is None or valor_icms_st is None:
        return None
    return detalhes.custo_unitario + valor_ipi + valor_icms_st


# Função Objetivo: Monta a linha completa (33 valores, na ordem de GRUPOS_DE_COLUNAS) pra 1 produto.
def _montar_linha(produto, detalhes, registro):
    if registro is not None:
        identificacao_produto = IdentificacaoProduto.a_partir_do_registro(registro)
        identificador_regra = IdentificadorRegra.a_partir_do_registro(registro)
        id_produto_sysemp = identificacao_produto.id_produto
        ncm, origem, origem_descricao = (
            identificador_regra.ncm, identificador_regra.origem, identificador_regra.origem_descricao,
        )
    else:
        id_produto_sysemp = ncm = origem = origem_descricao = '—'

    custo_final = _calcular_custo_final(detalhes)

    valores = [
        id_produto_sysemp, produto.marca, produto.ean, produto.sku, produto.titulo, produto.cod_fabricante,
        detalhes.nr_nf, detalhes.data_entrada_nota, detalhes.emissao, detalhes.fornecedor,
        float(detalhes.custo_unitario) if detalhes.custo_unitario is not None else None,
        float(custo_final) if custo_final is not None else None,
        ncm, origem, origem_descricao,
    ]
    for nome_imposto in ('ICMS', 'ICMS ST', 'ICMS Retido', 'IPI', 'PIS', 'COFINS'):
        linha_imposto = _linha_do_imposto(detalhes, nome_imposto)
        valores += [
            linha_imposto.cst,
            float(linha_imposto.aliquota) if linha_imposto.aliquota is not None else None,
            float(linha_imposto.reducao) if linha_imposto.reducao is not None else None,
        ]
    return valores


def main():
    console = Console()

    console.print('Lendo json já salvo em disco...')
    selecionados = ler_json(NOME_ARQUIVO_NOTAS_MAIS_RECENTES, padrao=[])
    registros_por_ean = {registro[CAMPO_CODIGO_PRODUTO]: registro for registro in selecionados}

    produtos = (
        Produto.objects
        .filter(impostos_entrada__isnull=False)
        .select_related(
            'impostos_entrada', 'impostos_entrada__icms', 'impostos_entrada__icms_st',
            'impostos_entrada__icms_ret', 'impostos_entrada__ipi', 'impostos_entrada__pis',
            'impostos_entrada__cofins',
        )
        .order_by('titulo')
    )

    livro = openpyxl.Workbook()
    planilha = livro.active
    planilha.title = 'Impostos de Entrada'
    _escrever_cabecalho(planilha)

    linha_atual = 3
    produtos_sem_json = 0

    for produto in produtos:
        detalhes = produto.impostos_entrada.obter_detalhes_para_exibicao()
        registro = registros_por_ean.get(produto.ean)
        if registro is None:
            produtos_sem_json += 1

        for indice, valor in enumerate(_montar_linha(produto, detalhes, registro), start=1):
            celula = planilha.cell(row=linha_atual, column=indice, value=valor)
            if indice in COLUNAS_DE_DATA and isinstance(valor, date):
                celula.number_format = 'DD/MM/YYYY'
        linha_atual += 1

    os.makedirs(os.path.dirname(CAMINHO_SAIDA), exist_ok=True)
    livro.save(CAMINHO_SAIDA)

    console.print(f'[bold green]Planilha gerada:[/bold green] {CAMINHO_SAIDA}')
    console.print(f'Produtos exportados: {linha_atual - 3}')
    if produtos_sem_json:
        console.print(
            f'[yellow]{produtos_sem_json} produto(s) sem correspondência no json em disco — '
            f'ID Produto/NCM/Origem ficaram "—" pra eles.[/yellow]'
        )


if __name__ == '__main__':
    main()