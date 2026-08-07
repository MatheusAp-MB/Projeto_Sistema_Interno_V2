import glob
import json
import os

import pandas as pd

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')
NOME_ARQUIVO_SAIDA = 'dados_filtrados.json'

CFOPS_PARA_MANTER = (
    '1.102', '2.102',  # compra para revenda
    '1.910', '2.910',  # bonificação, doação ou brinde (sem custo real de aquisição)
    '1.916', '2.916',  # retorno de remessa para conserto ou reparo (checar se carrega valor)
)


def _arquivo_json_mais_recente():
    arquivos = glob.glob(os.path.join(PASTA_SAIDAS, '*.json'))
    arquivos = [a for a in arquivos if os.path.basename(a) != NOME_ARQUIVO_SAIDA]
    if not arquivos:
        raise RuntimeError(f'Nenhum arquivo .json de origem encontrado em {PASTA_SAIDAS}')
    return max(arquivos, key=os.path.getmtime)


caminho_json = _arquivo_json_mais_recente()
with open(caminho_json, encoding='utf-8') as arquivo:
    dado_bruto = json.load(arquivo)

df = pd.DataFrame(dado_bruto['retorno'])
df_filtrado = df[df['CFOP'].isin(CFOPS_PARA_MANTER)]

print(f'Lendo: {caminho_json}')
print(f'Total de registros original: {len(df)}')
print(f'Total de registros após filtro de CFOP: {len(df_filtrado)}\n')
print('Registros mantidos por CFOP:')
print(df_filtrado['CFOP'].value_counts())

caminho_saida = os.path.join(PASTA_SAIDAS, NOME_ARQUIVO_SAIDA)
registros_filtrados = df_filtrado.to_dict(orient='records')
with open(caminho_saida, 'w', encoding='utf-8') as arquivo:
    json.dump(registros_filtrados, arquivo, ensure_ascii=False, indent=2)

print(f'\nSalvo em: {caminho_saida}')