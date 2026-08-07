# scripts_exploracao_ERP/calcular_custo_atual_por_produto.py

# Função Objetivo: Pipeline de "custo atual" por produto — decisão do
# superior do usuário (07/08/2026, ver "Custo Atual Escolhido para
# Precificacao dos Produtos Sysemp" no vault): usa a nota de compra/
# bonificação mais recente, não custo médio ponderado. Passos: filtra CFOP
# válido -> agrupa por produto+data (junta notas do mesmo dia) -> pega o
# grupo de data mais recente por produto -> exibe. Ainda 100% isolado
# (nenhuma integração com o resto do sistema).

import glob
import json
import os
from dataclasses import dataclass

import pandas as pd
from rich.console import Console
from rich.table import Table

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')
NOME_ARQUIVO_SAIDA = 'custo_atual_por_produto.json'

# * [ATUALIZAÇÃO 07/08/2026] → mesma lista definitiva usada em
#   filtrar_dados_por_cfop.py — ver "Lista de CFOP Relevantes para
#   Precificacao" no vault pro histórico completo.
CFOPS_VALIDOS = (
    '1.102', '2.102',  # compra para revenda
    '1.403', '2.403',  # compra para revenda sob substituição tributária (ICMS-ST)
    '1.910', '2.910',  # bonificação, doação ou brinde (sem custo real de aquisição)
)


# Função Objetivo: Fonte única entre "o que cada campo significa pra nós"
# e "o nome real do campo na API Sysemp" — se o Sysemp renomear algo um
# dia, muda só aqui. `frozen=True` porque isso é config fixa, nunca deveria
# mudar em tempo de execução.
@dataclass(frozen=True)
class CamposManifestoNotaEntrada:
    ean: str = 'Código Barras'
    nome_produto: str = 'Produto'
    data_entrada: str = 'Entrada'
    numero_nf: str = 'NR NF'
    cfop: str = 'CFOP'
    custo_unitario: str = 'Custo Unitário'
    fornecedor: str = 'Fornecedor'


CAMPOS = CamposManifestoNotaEntrada()

console = Console()


def _arquivo_json_mais_recente():
    arquivos = glob.glob(os.path.join(PASTA_SAIDAS, '*.json'))
    arquivos = [a for a in arquivos if os.path.basename(a) not in ('dados_filtrados.json', NOME_ARQUIVO_SAIDA)]
    if not arquivos:
        raise RuntimeError(f'Nenhum arquivo .json de origem encontrado em {PASTA_SAIDAS}')
    return max(arquivos, key=os.path.getmtime)


caminho_json = _arquivo_json_mais_recente()
with open(caminho_json, encoding='utf-8') as arquivo:
    dado_bruto = json.load(arquivo)

df = pd.DataFrame(dado_bruto['retorno'])
console.print(f'Lendo: [bold]{caminho_json}[/bold]')
console.print(f'Total de registros original: {len(df)}')

# Passo 2: filtra por CFOP válido
df = df[df[CAMPOS.cfop].isin(CFOPS_VALIDOS)].copy()
console.print(f'Após filtro de CFOP válido: {len(df)}')

# * [EXPLICAÇÃO] → "Entrada" já vem em ISO (AAAA-MM-DD) e "Custo Unitário"
#   já usa ponto como separador decimal (confirmado num registro real,
#   07/08/2026) — conversão direta, sem tratamento de formato brasileiro.
#   "NR NF" precisa virar int — comparação como string erra (ex: "9" > "10"
#   por ordem lexicográfica, o que é errado numericamente).
df[CAMPOS.data_entrada] = pd.to_datetime(df[CAMPOS.data_entrada])
df[CAMPOS.custo_unitario] = df[CAMPOS.custo_unitario].astype(float)
df[CAMPOS.numero_nf] = df[CAMPOS.numero_nf].astype(int)

# * [EXPLICAÇÃO] → Ordena por NF decrescente ANTES de agrupar — assim
#   "first" dentro de cada grupo (produto, data) sempre pega a nota de
#   maior número, e todos os campos daquela linha (custo, CFOP, NF) vêm da
#   MESMA nota, nunca misturados entre notas diferentes do mesmo dia.
#   Critério: fornecedor numera notas em sequência, então maior número =
#   emitida depois. SÓ VÁLIDO se as notas empatadas forem do mesmo
#   fornecedor — ver o aviso crítico abaixo pro caso em que não são.
df_ordenado = df.sort_values(CAMPOS.numero_nf, ascending=False)

# Passos 3 e 4: agrupa por produto, DEPOIS por data dentro do produto —
# junta em 1 linha só as notas do mesmo produto no mesmo dia.
agrupado = df_ordenado.groupby([CAMPOS.ean, CAMPOS.data_entrada], as_index=False).agg(
    Produto=(CAMPOS.nome_produto, 'first'),
    NR_NF=(CAMPOS.numero_nf, 'first'),
    CFOP=(CAMPOS.cfop, 'first'),
    Custo_Unitario=(CAMPOS.custo_unitario, 'first'),
    Qtde=('Qtde', 'sum'),
    Quantidade_Notas=(CAMPOS.custo_unitario, 'count'),
    Fornecedores_Distintos=(CAMPOS.fornecedor, 'nunique'),
)

for _, linha in agrupado[agrupado['Quantidade_Notas'] > 1].iterrows():
    if linha['Fornecedores_Distintos'] > 1:
        console.print(
            f'[red][AVISO CRÍTICO][/red] Produto {linha[CAMPOS.ean]} teve '
            f'{int(linha["Quantidade_Notas"])} notas de {int(linha["Fornecedores_Distintos"])} '
            f'fornecedores DIFERENTES na mesma data ({linha[CAMPOS.data_entrada].date()}) — '
            f'"maior NF = mais recente" não é confiável entre fornecedores diferentes. '
            f'Usando NF {linha["NR_NF"]} mesmo assim, mas CONFERIR manualmente.'
        )
    else:
        console.print(
            f'[yellow][AVISO][/yellow] Produto {linha[CAMPOS.ean]} teve '
            f'{int(linha["Quantidade_Notas"])} notas do mesmo fornecedor na mesma data '
            f'({linha[CAMPOS.data_entrada].date()}) — usando a de maior NF ({linha["NR_NF"]}) '
            f'como mais recente.'
        )

# Passo 5: por produto, seleciona só o grupo da data mais recente
resultado = agrupado.sort_values(CAMPOS.data_entrada).groupby(CAMPOS.ean, as_index=False).tail(1)
resultado = resultado.sort_values(CAMPOS.ean)

# Passo 6: exibe (isolado — tabela Rich, nenhuma tela real ainda)
tabela = Table(title=f'Custo Atual por Produto ({len(resultado)} produtos)')
tabela.add_column('#', justify='right', style='cyan')
tabela.add_column('Código Barras', style='green')
tabela.add_column('Produto')

tabela.add_column('Data (Entrada)')
tabela.add_column('Notas no Dia', justify='right')

tabela.add_column('Numero NF')
tabela.add_column('CFOP')

tabela.add_column('Custo Atual', justify='right')

for posicao, (_, linha) in enumerate(resultado.iterrows(), start=1):
    tabela.add_row(
        str(posicao),
        str(linha[CAMPOS.ean]),
        str(linha['Produto']),

        linha[CAMPOS.data_entrada].strftime('%Y-%m-%d'),
        str(int(linha['Quantidade_Notas'])),

        str(linha['NR_NF']),
        str(linha['CFOP']),

        '{:.2f}'.format(linha['Custo_Unitario']),
    )

console.print(tabela)

os.makedirs(PASTA_SAIDAS, exist_ok=True)
caminho_saida = os.path.join(PASTA_SAIDAS, NOME_ARQUIVO_SAIDA)
resultado.to_json(caminho_saida, orient='records', force_ascii=False, indent=2, date_format='iso')
console.print(f'\nSalvo em: [bold]{caminho_saida}[/bold]')