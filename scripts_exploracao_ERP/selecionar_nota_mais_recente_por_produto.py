# scripts_exploracao_ERP/selecionar_nota_mais_recente_por_produto.py

# Função Objetivo: Ler o manifesto já filtrado por CFOP (dados_filtrados.json)
# e selecionar, por produto (Código Barras), a nota mais recente — usando
# "Data Entrada da Nota" (confiável desde a remodelagem da API pela Sysemp,
# ver "Campo Entrada do Manifesto Pode Nao Ser a Entrada Fisica Real" no
# vault), com desempate por maior número de NF em caso de mesma data (não
# precisa mais separar por fornecedor: confirmado que 1 produto sempre vem de
# 1 fornecedor). Mantém TODOS os campos da nota escolhida — ainda não se sabe
# quais impostos serão usados, então nada é descartado aqui; a redução de
# campos vem depois, quando os testes de imposto definirem o que é necessário.
#
# Exibição pensada pra escala (09/08/2026) — em vez de 1 tabela gigante
# produto a produto e 1 aviso por empate, mostra um resumo da execução
# (contagens, período coberto) e uma amostra pequena — o resto vai só pro
# json de saída, não pra tela.

import json
import os

import pandas as pd
from rich.console import Console
from rich.table import Table

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')
NOME_ARQUIVO_ENTRADA = 'dados_filtrados.json'
NOME_ARQUIVO_SAIDA = 'nota_mais_recente_por_produto.json'

CAMPO_CODIGO_PRODUTO = 'Código Barras'
CAMPO_NF = 'NR NF'
CAMPO_DATA_ENTRADA_NOTA = 'Data Entrada da Nota'

TAMANHO_AMOSTRA = 10

console = Console()

caminho_entrada = os.path.join(PASTA_SAIDAS, NOME_ARQUIVO_ENTRADA)
with open(caminho_entrada, encoding='utf-8') as arquivo:
    registros = json.load(arquivo)

df = pd.DataFrame(registros)
df[CAMPO_DATA_ENTRADA_NOTA] = pd.to_datetime(df[CAMPO_DATA_ENTRADA_NOTA])
df[CAMPO_NF] = df[CAMPO_NF].astype(int)

df_ordenado = df.sort_values([CAMPO_DATA_ENTRADA_NOTA, CAMPO_NF], ascending=False, na_position='last')

# Função Objetivo: Conta empates (mesma data mais recente, >1 nota) sem
# imprimir 1 linha por produto — em escala isso lotava a tela e escondia
# o que importa. Vira 1 número só no resumo, não 1 aviso por produto.
produtos_com_empate = []
for codigo_produto, grupo in df_ordenado.groupby(CAMPO_CODIGO_PRODUTO):
    data_mais_recente = grupo.iloc[0][CAMPO_DATA_ENTRADA_NOTA]
    empatados = grupo[grupo[CAMPO_DATA_ENTRADA_NOTA] == data_mais_recente]
    if len(empatados) > 1:
        produtos_com_empate.append(codigo_produto)

selecionados = df_ordenado.groupby(CAMPO_CODIGO_PRODUTO, as_index=False).head(1)
selecionados = selecionados.sort_values(CAMPO_CODIGO_PRODUTO)

# ========== Resumo da execução ==========

resumo = Table(title='Resumo da Execução', show_header=False)
resumo.add_column('Campo', style='cyan')
resumo.add_column('Valor', style='green')
resumo.add_row('Arquivo lido', caminho_entrada)
resumo.add_row('Total de registros filtrados', str(len(df)))
resumo.add_row('Total de produtos distintos', str(len(selecionados)))
resumo.add_row('Produtos com empate de data (resolvido por maior NF)', str(len(produtos_com_empate)))
resumo.add_row(
    'Período coberto (Data Entrada da Nota)',
    f'{df[CAMPO_DATA_ENTRADA_NOTA].min().date()} a {df[CAMPO_DATA_ENTRADA_NOTA].max().date()}',
)
console.print(resumo)
console.print()

# ========== Amostra ==========

amostra = selecionados.head(TAMANHO_AMOSTRA)
tabela = Table(title=f'Amostra ({len(amostra)} de {len(selecionados)} produtos)')
tabela.add_column('Código Barras', style='green')
tabela.add_column('Produto')
tabela.add_column('NR NF')
tabela.add_column('Emissão')
tabela.add_column('Data Entrada da Nota')
tabela.add_column('CFOP')
tabela.add_column('Custo Unitário', justify='right')

for _, linha in amostra.iterrows():
    tabela.add_row(
        str(linha[CAMPO_CODIGO_PRODUTO]),
        str(linha.get('Produto', '')),
        str(linha[CAMPO_NF]),
        str(linha.get('Emissão', '')),
        linha[CAMPO_DATA_ENTRADA_NOTA].strftime('%Y-%m-%d') if pd.notna(linha[CAMPO_DATA_ENTRADA_NOTA]) else '',
        str(linha.get('CFOP', '')),
        '{:.2f}'.format(float(linha.get('Custo Unitário', 0))),
    )

console.print(tabela)

os.makedirs(PASTA_SAIDAS, exist_ok=True)
caminho_saida = os.path.join(PASTA_SAIDAS, NOME_ARQUIVO_SAIDA)

# Chave de consulta = Código Barras (EAN) — dict, não lista, pra achar o
# produto direto por código sem percorrer a lista inteira.
selecionados_por_produto = selecionados.set_index(CAMPO_CODIGO_PRODUTO, drop=False)
selecionados_por_produto.to_json(caminho_saida, orient='index', force_ascii=False, indent=2, date_format='iso')

console.print(f'\nSalvo em: [bold]{caminho_saida}[/bold]')