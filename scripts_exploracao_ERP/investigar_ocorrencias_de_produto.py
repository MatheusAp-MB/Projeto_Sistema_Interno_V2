import glob
import json
import os
from rich.console import Console
from rich.table import Table

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')

CODIGO_PRODUTO_INVESTIGADO = '7908050719121'

CAMPO_CODIGO_PRODUTO = 'Código Barras'
CAMPO_NF = 'NR NF'
CAMPO_DATA_ENTRADA = 'Entrada'
CAMPO_QUANTIDADE = 'Qtde'

CAMPO_EMISSAO = 'Emissão'
CAMPO_ID_PRODUTO = 'ID Produto'

CAMPO_IPI="Aliquota IPI"
CAMPO_ICMS="Aliquota ICMS"
CAMPO_PIS="Aliquota PIS"
CAMPO_COFINS="Aliquota COFINS"

CAMPO_NCM="NCM"



def _arquivo_json_mais_recente():
    arquivos = glob.glob(os.path.join(PASTA_SAIDAS, '*.json'))
    arquivos = [a for a in arquivos if os.path.basename(a) != 'dados_filtrados.json']
    if not arquivos:
        raise RuntimeError(f'Nenhum arquivo .json de origem encontrado em {PASTA_SAIDAS}')
    return max(arquivos, key=os.path.getmtime)


caminho_json = _arquivo_json_mais_recente()
with open(caminho_json, encoding='utf-8') as arquivo:
    dado_bruto = json.load(arquivo)

registros = dado_bruto['retorno']
ocorrencias = [
    registro for registro in registros
    if registro.get(CAMPO_CODIGO_PRODUTO) == CODIGO_PRODUTO_INVESTIGADO
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
tabela.add_column("Entrada")
tabela.add_column("Quantidade", justify="right")
tabela.add_column("CFOP")
tabela.add_column("NCM")
tabela.add_column("IPI", justify="right")
tabela.add_column("ICMS", justify="right")
tabela.add_column("PIS", justify="right")
tabela.add_column("COFINS", justify="right")

for posicao, registro in enumerate(ocorrencias):
    tabela.add_row(
        str(posicao),
        str(registro.get(CAMPO_ID_PRODUTO, "")),
        str(registro.get(CAMPO_NF, "")),
        str(registro.get(CAMPO_EMISSAO, "")),
        str(registro.get(CAMPO_DATA_ENTRADA, "")),
        "{:.2f}".format(float(registro.get(CAMPO_QUANTIDADE, ""))),
        str(registro.get("CFOP", "")),
        str(registro.get(CAMPO_NCM, "")),
        "{:.2f}".format(float(registro.get(CAMPO_IPI, ""))),
        "{:.2f}".format(float(registro.get(CAMPO_ICMS, ""))),
        "{:.2f}".format(float(registro.get(CAMPO_PIS, ""))),
        "{:.2f}".format(float(registro.get(CAMPO_COFINS, ""))),

    )

console.print(tabela)


