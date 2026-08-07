import glob
import json
import os

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')

CODIGO_PRODUTO_INVESTIGADO = '7908050719121'

CAMPO_CODIGO_PRODUTO = 'Código Barras'
CAMPO_NF = 'NR NF'
CAMPO_DATA_ENTRADA = 'Entrada'
CAMPO_QUANTIDADE = 'Qtde'

CAMPO_EMISSAO = 'Emissão'
CAMPO_ID_PRODUTO = 'ID Produto'

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

for posicao, registro in enumerate(ocorrencias):
    print(
        f'[{posicao}] ID={registro.get(CAMPO_ID_PRODUTO)} | '
        f'NF={registro.get(CAMPO_NF)} | '
        f'Emissão={registro.get(CAMPO_EMISSAO)} | '
        f'Entrada={registro.get(CAMPO_DATA_ENTRADA)} | '
        f'CFOP={registro.get("CFOP")} | '
        f'Quantidade={registro.get(CAMPO_QUANTIDADE)}'
    )