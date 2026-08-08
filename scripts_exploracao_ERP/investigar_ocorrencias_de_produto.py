import glob
import json
import os
from rich.console import Console
from rich.table import Table

# Função Objetivo: Investigar todas as ocorrências de 1 produto no manifesto
# de nota de entrada, pra decisão de custo/CFOP. Atualizado pra estrutura nova
# da API Sysemp (07/08/2026, após chamado aberto sobre o campo "Entrada"):
# "retorno" agora agrupa por NOTA (Chave/NR NF/Emissão/Data Entrada da Nota/
# Fornecedor), com os itens dentro de "itens_nf" (CFOP/Código Barras/Qtde/
# aliquotas/etc.) — não é mais 1 item = 1 registro na raiz. O campo "Entrada"
# (que sempre repetia "Emissão", ver "Campo Entrada do Manifesto Pode Nao Ser
# a Entrada Fisica Real" no vault) foi substituído por "Data Entrada da Nota",
# agora no nível da nota e nulável — ainda não validado se corrige o problema
# de verdade.

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')

CODIGO_PRODUTO_INVESTIGADO = '7908050719121'

CAMPO_ITENS_NF = 'itens_nf'

# Nível da nota
CAMPO_NF = 'NR NF'
CAMPO_EMISSAO = 'Emissão'
CAMPO_DATA_ENTRADA_NOTA = 'Data Entrada da Nota'

# Nível do item
CAMPO_CODIGO_PRODUTO = 'Código Barras'
CAMPO_ID_PRODUTO = 'ID Produto'
CAMPO_QUANTIDADE = 'Qtde'
CAMPO_CFOP = 'CFOP'
CAMPO_NCM = 'NCM'
CAMPO_IPI = 'Aliquota IPI'
CAMPO_ICMS = 'Aliquota ICMS'
CAMPO_PIS = 'Aliquota PIS'
CAMPO_COFINS = 'Aliquota COFINS'


def _arquivo_json_mais_recente():
    arquivos = glob.glob(os.path.join(PASTA_SAIDAS, '*.json'))
    arquivos = [a for a in arquivos if os.path.basename(a) != 'dados_filtrados.json']
    if not arquivos:
        raise RuntimeError(f'Nenhum arquivo .json de origem encontrado em {PASTA_SAIDAS}')
    return max(arquivos, key=os.path.getmtime)


caminho_json = _arquivo_json_mais_recente()
with open(caminho_json, encoding='utf-8') as arquivo:
    dado_bruto = json.load(arquivo)

notas = dado_bruto['retorno']
ocorrencias = [
    (nota, item)
    for nota in notas
    for item in nota.get(CAMPO_ITENS_NF, [])
    if item.get(CAMPO_CODIGO_PRODUTO) == CODIGO_PRODUTO_INVESTIGADO
]

print(f'Lendo: {caminho_json}')
print(f'Produto investigado: {CODIGO_PRODUTO_INVESTIGADO}')
print(f'Número de ocorrências: {len(ocorrencias)}\n')

console = Console()

tabela = Table(title="Ocorrências")

tabela.add_column("#", justify="right", style="cyan")
tabela.add_column("ID", style="green")
tabela.add_column("NF")
tabela.add_column("Emissão")
tabela.add_column("Data Entrada (Nota)")
tabela.add_column("Quantidade", justify="right")
tabela.add_column("CFOP")
tabela.add_column("NCM")
tabela.add_column("IPI", justify="right")
tabela.add_column("ICMS", justify="right")
tabela.add_column("PIS", justify="right")
tabela.add_column("COFINS", justify="right")

for posicao, (nota, item) in enumerate(ocorrencias):
    tabela.add_row(
        str(posicao),
        str(item.get(CAMPO_ID_PRODUTO, "")),
        str(nota.get(CAMPO_NF, "")),
        str(nota.get(CAMPO_EMISSAO, "")),
        str(nota.get(CAMPO_DATA_ENTRADA_NOTA) or ""),
        "{:.2f}".format(float(item.get(CAMPO_QUANTIDADE, ""))),
        str(item.get(CAMPO_CFOP, "")),
        str(item.get(CAMPO_NCM, "")),
        "{:.2f}".format(float(item.get(CAMPO_IPI, ""))),
        "{:.2f}".format(float(item.get(CAMPO_ICMS, ""))),
        "{:.2f}".format(float(item.get(CAMPO_PIS, ""))),
        "{:.2f}".format(float(item.get(CAMPO_COFINS, ""))),
    )

console.print(tabela)