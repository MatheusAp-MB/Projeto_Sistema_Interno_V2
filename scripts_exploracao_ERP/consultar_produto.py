# scripts_exploracao_ERP/consultar_produto.py

# Função Objetivo: Ler nota_mais_recente_por_produto.json (dict indexado por
# Código Barras) e montar o DadosXmlNF de 1 produto específico, pra validar
# visualmente se o mapeamento pra dataclass está correto antes de escrever
# os testes de imposto de verdade.

import json
import os
import sys

from rich.console import Console


def _adicionar_raiz_do_projeto_ao_path():
    caminho_atual = os.path.dirname(os.path.abspath(__file__))
    while caminho_atual != os.path.dirname(caminho_atual):
        if os.path.exists(os.path.join(caminho_atual, 'manage.py')):
            sys.path.insert(0, caminho_atual)
            return
        caminho_atual = os.path.dirname(caminho_atual)
    raise RuntimeError('Não foi possível encontrar manage.py subindo a partir deste script.')


_adicionar_raiz_do_projeto_ao_path()

from integracao_sysemp.servicos.dados_xml_nf import DadosXmlNF

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')
NOME_ARQUIVO_ENTRADA = 'nota_mais_recente_por_produto.json'

# CODIGO_PRODUTO_CONSULTADO = '7908050719121'
CODIGO_PRODUTO_CONSULTADO = '7908050718117'




console = Console()

caminho_entrada = os.path.join(PASTA_SAIDAS, NOME_ARQUIVO_ENTRADA)
with open(caminho_entrada, encoding='utf-8') as arquivo:
    produtos = json.load(arquivo)

registro = produtos.get(CODIGO_PRODUTO_CONSULTADO)
if registro is None:
    raise RuntimeError(f'Produto {CODIGO_PRODUTO_CONSULTADO} não encontrado em {caminho_entrada}')

dados = DadosXmlNF.a_partir_do_registro(registro)

console.print(dados)
console.print(f'\nExemplo de acesso — custo unitário: {dados.custos.unitario}')
console.print(f'Exemplo de acesso — alíquota PIS: {dados.pis.aliquota}')