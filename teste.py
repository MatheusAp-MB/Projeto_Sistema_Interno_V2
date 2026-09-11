# teste.py
#
# Rodar da raiz do projeto, com:
#   python -u "teste.py"
#
# Lista os produtos SEM CALCULO (GradePrecificacaoML.resolvida=False) cuja causa
# é dimensão de embalagem ausente no ERP. Console mostra só o resumo (Rich) + o
# grupo prioritário (COM MLB vinculado, dimensão ainda zerada — produto já
# anunciado, merece olhar primeiro). O detalhe completo, linha por linha, vai
# pra um .xlsx (grande demais pro console).
#
# Correção (11/09/2026): comparação COM MLB vs SEM MLB sempre por SKU —
# VariacaoAnuncioMercadoLivre.produto usa to_field='sku' (ver
# mercado_livre/models/variacao.py), nunca o id numérico do Produto.
#
# "ERRO DE CADASTRO" (dimensão fisicamente absurda) é relido AGORA, direto do
# Excel do ERP, reaproveitando LinhaProdutoERP — a mesma classe que
# importar_produtos_erp.py usa de verdade — em vez de uma lista congelada de um
# run passado (dono único do dado continua sendo aquela classe).
#
# Só leitura no banco — nenhum write. Só leitura no Excel do ERP.

import os
import sys
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'projeto_sistema_interno_mb_sv.settings')

import django
django.setup()

from django.db.models import Q
from rich.console import Console
from rich.table import Table
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from precificacao.models import GradePrecificacaoML
from produtos.models import Produto
from mercado_livre.models import VariacaoAnuncioMercadoLivre
from core.management.commands.popular_banco_suporte.importar_produtos_erp import (
    CAMINHOS_ERP_POR_EMPRESA, LinhaProdutoERP,
)
from core.management.commands.popular_banco_suporte.conversor_celula_excel import ConversorCelulaExcel
from core.management.commands.popular_banco_suporte.parser_data import ParserData
from core.management.commands.popular_banco_suporte.leitor_planilha_erp import ler_linhas_planilha_erp
from core.empresa import EMPRESA_MAGAZINE, EMPRESA_SAMVALE

console = Console()

EMPRESA_POR_ALIAS = {'magazine': EMPRESA_MAGAZINE, 'samvale': EMPRESA_SAMVALE}

CAMPOS = (
    'sku', 'ean', 'titulo', 'ativo_no_erp',
    'altura_produto_apos_embalado', 'largura_produto_apos_embalado',
    'comprimento_produto_apos_embalado', 'peso_produto_apos_embalado',
)


# Função Objetivo: Rele o relatório de Ativos do ERP AGORA e devolve o SKU de toda
# linha que o importador marcaria como "erro de cadastro" — nunca uma foto velha
# de um run passado. Reaproveita LinhaProdutoERP, a MESMA classe que
# importar_produtos_erp.py usa de verdade — dono único do dado continua sendo ela.
def skus_com_erro_cadastro(alias):
    conversor = ConversorCelulaExcel(origem='openpyxl')
    parser_data = ParserData(origem='excel_br')
    caminho_ativos = CAMINHOS_ERP_POR_EMPRESA[EMPRESA_POR_ALIAS[alias]]['ativos']

    skus = set()
    for linha_bruta in ler_linhas_planilha_erp(caminho_ativos):
        linha = LinhaProdutoERP(linha_bruta, conversor, parser_data).transformar_linha_em_produto()
        if linha.erro_dimensao and linha.sku:
            skus.add(linha.sku)
    return skus


# Função Objetivo: Investiga 1 empresa, devolve tudo já organizado (nada impresso aqui).
def investigar(alias):
    sem_calculo = GradePrecificacaoML.objects.using(alias).filter(resolvida=False)
    produtos_ids = set(sem_calculo.values_list('produto_id', flat=True).distinct())

    dimensao_zerada_qs = Produto.objects.using(alias).filter(id__in=produtos_ids).filter(
        Q(altura_ordenada_cm__isnull=True) | Q(altura_ordenada_cm=0)
        | Q(largura_ordenada_cm__isnull=True) | Q(largura_ordenada_cm=0)
        | Q(comprimento_ordenada_cm__isnull=True) | Q(comprimento_ordenada_cm=0)
    )
    dim_ids = set(dimensao_zerada_qs.values_list('id', flat=True))
    dim_skus = set(dimensao_zerada_qs.values_list('sku', flat=True))
    dim_skus.discard(None)

    skus_com_mlb = set(
        VariacaoAnuncioMercadoLivre.objects.using(alias)
        .filter(produto_id__in=dim_skus)
        .values_list('produto_id', flat=True)
        .distinct()
    )

    produtos_com_mlb = Produto.objects.using(alias).filter(id__in=dim_ids, sku__in=skus_com_mlb)
    produtos_sem_mlb = Produto.objects.using(alias).filter(id__in=dim_ids).exclude(sku__in=skus_com_mlb)
    skus_erro_conhecidos = skus_com_erro_cadastro(alias)

    com_mlb = list(produtos_com_mlb.values(*CAMPOS).order_by('sku'))
    erro_cadastro, nunca_cadastrado = [], []
    for p in produtos_sem_mlb.values(*CAMPOS).order_by('sku'):
        (erro_cadastro if p['sku'] in skus_erro_conhecidos else nunca_cadastrado).append(p)

    return {
        'total_sem_calculo': len(produtos_ids),
        'dimensao_zerada': len(dim_ids),
        'com_mlb': com_mlb,
        'erro_cadastro': erro_cadastro,
        'nunca_cadastrado': nunca_cadastrado,
    }


def mostrar_resumo(resultados):
    tabela = Table(title='Resumo — SEM CÁLCULO por dimensão zerada', show_lines=True)
    tabela.add_column('Empresa', style='bold')
    tabela.add_column('SEM CÁLCULO (total)', justify='right')
    tabela.add_column('Dimensão zerada', justify='right')
    tabela.add_column('COM MLB (prioridade)', justify='right', style='red')
    tabela.add_column('SEM MLB · erro cadastro', justify='right', style='yellow')
    tabela.add_column('SEM MLB · nunca cadastrado', justify='right')

    for alias, r in resultados.items():
        tabela.add_row(
            alias.upper(), str(r['total_sem_calculo']), str(r['dimensao_zerada']),
            str(len(r['com_mlb'])), str(len(r['erro_cadastro'])), str(len(r['nunca_cadastrado'])),
        )
    console.print(tabela)


def mostrar_prioridade(resultados):
    for alias, r in resultados.items():
        if not r['com_mlb']:
            continue
        tabela = Table(title=f'{alias.upper()} — COM MLB vinculado, dimensão ainda zerada (investigar primeiro)', show_lines=True)
        for coluna in ('SKU', 'EAN', 'Título', 'Ativo ERP'):
            tabela.add_column(coluna)
        for p in r['com_mlb']:
            tabela.add_row(p['sku'] or '—', p['ean'], p['titulo'], str(p['ativo_no_erp']))
        console.print(tabela)


def exportar_excel(resultados):
    wb = Workbook()

    resumo = wb.active
    resumo.title = 'Resumo'
    cabecalho = ['Empresa', 'SEM CÁLCULO (total)', 'Dimensão zerada', 'COM MLB (prioridade)',
                 'SEM MLB · erro cadastro', 'SEM MLB · nunca cadastrado']
    resumo.append(cabecalho)
    for celula in resumo[1]:
        celula.font = Font(name='Arial', bold=True, color='FFFFFF')
        celula.fill = PatternFill('solid', fgColor='1E3A5F')
    for alias, r in resultados.items():
        resumo.append([
            alias.upper(), r['total_sem_calculo'], r['dimensao_zerada'],
            len(r['com_mlb']), len(r['erro_cadastro']), len(r['nunca_cadastrado']),
        ])
    for coluna in resumo.columns:
        resumo.column_dimensions[coluna[0].column_letter].width = 22

    cabecalho_detalhe = ['Categoria', 'SKU', 'EAN', 'Ativo no ERP', 'Altura (cm)', 'Largura (cm)',
                          'Comprimento (cm)', 'Peso (kg)', 'Título']
    categorias = [
        ('COM MLB — investigar (erro real, já anunciado)', 'com_mlb'),
        ('SEM MLB — erro de cadastro (dimensão absurda)', 'erro_cadastro'),
        ('SEM MLB — nunca cadastrado', 'nunca_cadastrado'),
    ]

    for alias, r in resultados.items():
        aba = wb.create_sheet(alias.upper())
        aba.append(cabecalho_detalhe)
        for celula in aba[1]:
            celula.font = Font(name='Arial', bold=True, color='FFFFFF')
            celula.fill = PatternFill('solid', fgColor='1E3A5F')
        aba.freeze_panes = 'A2'

        for rotulo, chave in categorias:
            for p in r[chave]:
                aba.append([
                    rotulo, p['sku'] or '(sem SKU)', p['ean'], p['ativo_no_erp'],
                    p['altura_produto_apos_embalado'], p['largura_produto_apos_embalado'],
                    p['comprimento_produto_apos_embalado'], p['peso_produto_apos_embalado'],
                    p['titulo'],
                ])

        larguras = [40, 22, 16, 12, 12, 12, 14, 12, 60]
        for i, largura in enumerate(larguras, start=1):
            aba.column_dimensions[aba.cell(row=1, column=i).column_letter].width = largura
        for linha in aba.iter_rows(min_row=1):
            for celula in linha:
                if celula.row > 1:
                    celula.font = Font(name='Arial')
                celula.alignment = Alignment(vertical='top', wrap_text=(celula.column == 9))

    nome_arquivo = f'investigacao_dimensao_ausente_{datetime.now():%Y%m%d_%H%M%S}.xlsx'
    wb.save(nome_arquivo)
    return nome_arquivo


if __name__ == '__main__':
    resultados = {}
    for empresa_alias in ("magazine", "samvale"):
        try:
            resultados[empresa_alias] = investigar(empresa_alias)
        except Exception as exc:
            console.print(f'[bold red]ERRO ao investigar {empresa_alias.upper()}:[/bold red] {exc!r}')

    if resultados:
        mostrar_resumo(resultados)
        mostrar_prioridade(resultados)
        caminho = exportar_excel(resultados)
        console.print(f'\n[bold green]Detalhe completo exportado:[/bold green] {caminho}')