# scripts_exploracao_ERP/comparar_impostos_planilha_vs_xml.py

# Função Objetivo: Compara lado a lado os campos fiscais do Produto real
# (preenchidos pela planilha manual, importar_planilha_precificacao.py) com
# os mesmos conceitos vindos do DadosXmlNF (Sysemp) — pra ver o quanto a
# cobertura do XML já bate ou diverge da fonte manual usada hoje. Só
# leitura, nenhuma escrita.

import json
import os
import sys
from dataclasses import dataclass


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

from rich.console import Console
from rich.table import Table

from produtos.models import Produto
from dados_xml_nf import DadosXmlNF

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')
NOME_ARQUIVO_ENTRADA_XML = 'nota_mais_recente_por_produto.json'

EAN_TESTADO = '7908050700174'

console = Console()


def _carregar_registro_xml(ean):
    caminho = os.path.join(PASTA_SAIDAS, NOME_ARQUIVO_ENTRADA_XML)
    with open(caminho, encoding='utf-8') as arquivo:
        produtos_sysemp = json.load(arquivo)

    registro = produtos_sysemp.get(ean)
    if registro is None:
        raise RuntimeError(f'Produto {ean} não encontrado em {caminho}')

    return registro


def _fmt(valor, sufixo=''):
    return 'N/A' if valor is None else f'{valor}{sufixo}'


@dataclass(frozen=True)
class LinhaComparacao:
    imposto: str
    campo_planilha: str
    valor_planilha: str
    valor_xml: str


produto = Produto.objects.get(ean=EAN_TESTADO)
registro_xml = _carregar_registro_xml(EAN_TESTADO)
dados = DadosXmlNF.a_partir_do_registro(registro_xml)

linhas = [
    LinhaComparacao('Custo unitário', 'custo', f'R$ {produto.custo}', f'R$ {dados.custos.unitario:.2f}'),

    LinhaComparacao('ICMS entrada (alíquota)', 'icms_entrada', _fmt(produto.icms_entrada, '%'), f'{dados.icms.aliquota:.2f}%'),
    LinhaComparacao('ICMS entrada (redução)', '— (não existe na planilha)', '—', f'{dados.icms.reducao:.2f}%'),

    LinhaComparacao('IPI (alíquota)', 'ipi', _fmt(produto.ipi, '%'), f'{dados.ipi.aliquota:.2f}%'),

    LinhaComparacao('PIS (alíquota, campo separado)', 'pis_percentual', _fmt(produto.pis_percentual, '%'), f'{dados.pis.aliquota:.2f}%'),
    LinhaComparacao('PIS (redução)', '— (não existe na planilha)', '—', f'{dados.pis.reducao:.2f}%'),

    LinhaComparacao('COFINS (alíquota, campo separado)', 'cofins_percentual', _fmt(produto.cofins_percentual, '%'), f'{dados.cofins.aliquota:.2f}%'),
    LinhaComparacao('COFINS (redução)', '— (não existe na planilha)', '—', f'{dados.cofins.reducao:.2f}%'),

    LinhaComparacao(
        'PIS+COFINS combinado (usado de verdade hoje)', 'pis_cofins', _fmt(produto.pis_cofins, '%'),
        f'{dados.pis.aliquota + dados.cofins.aliquota:.2f}%',
    ),

    LinhaComparacao('ST (valor)', 'st_valor', f'R$ {_fmt(produto.st_valor)}', f'R$ {dados.icms_st.valor:.2f}'),
    LinhaComparacao('ICMS ST (alíquota)', '— (planilha só tem o valor)', '—', f'{dados.icms_st.aliquota:.2f}%'),

    LinhaComparacao('ICMS de saída', 'icms_saida_media', _fmt(produto.icms_saida_media, '%'), '— (não existe no XML de entrada)'),
    LinhaComparacao('MVA', 'mva', _fmt(produto.mva), '— (não existe no XML)'),
]

tabela = Table(title=f'Planilha (banco real) × XML (Sysemp) — Produto {EAN_TESTADO}')
tabela.add_column('Imposto', style='cyan')
tabela.add_column('Campo (planilha/banco)')
tabela.add_column('Valor (planilha/banco)')
tabela.add_column('Valor (XML/Sysemp)')

for linha in linhas:
    tabela.add_row(linha.imposto, linha.campo_planilha, linha.valor_planilha, linha.valor_xml)

console.print(tabela)