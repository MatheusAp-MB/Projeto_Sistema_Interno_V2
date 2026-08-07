# scripts_exploracao_ERP/contar_registros_por_cfop.py

# Função Objetivo: Carrega o JSON mais recente de manifesto de nota de
# entrada num DataFrame e conta quantos registros existem por CFOP — base
# pra decidir, com dado real (não hipótese), quais CFOPs representam
# compra de mercadoria pra revenda e quais são ruído (devolução,
# transferência, ativo imobilizado, consumo, etc.). Só leitura/contagem,
# nenhuma limpeza de campo ainda.

import glob
import json
import os

import pandas as pd

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')


def _arquivo_json_mais_recente():
    arquivos = glob.glob(os.path.join(PASTA_SAIDAS, '*.json'))
    if not arquivos:
        raise RuntimeError(f'Nenhum .json encontrado em {PASTA_SAIDAS} — rode um script de exploração antes.')
    return max(arquivos, key=os.path.getmtime)


caminho_json = _arquivo_json_mais_recente()
with open(caminho_json, encoding='utf-8') as arquivo:
    dado_bruto = json.load(arquivo)

df = pd.DataFrame(dado_bruto['retorno'])

print(f'Lendo: {caminho_json}')
print(f'Total de registros: {len(df)}\n')

if df.empty:
    print('Nenhum registro no período — nada pra contar.')
else:
    contagem = df['CFOP'].value_counts()
    percentual = (df['CFOP'].value_counts(normalize=True) * 100).round(1)
    resumo = pd.DataFrame({'quantidade': contagem, 'percentual': percentual})
    print('Registros por CFOP:')
    print(resumo)