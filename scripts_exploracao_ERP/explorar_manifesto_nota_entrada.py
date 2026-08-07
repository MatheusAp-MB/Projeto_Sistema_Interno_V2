import json
import os
from datetime import datetime
from api_sysemp import ApiSysemp

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))

DATA_INICIAL = '2026-05-01'
DATA_FINAL = '2026-08-07'

api = ApiSysemp()
resultado = api.impostos_entrada.listar_periodo_completo(DATA_INICIAL, DATA_FINAL)

os.makedirs(os.path.join(_PASTA_ATUAL, 'saidas'), exist_ok=True)
caminho_saida = os.path.join(_PASTA_ATUAL, 'saidas', f'manifesto_nota_entrada_{datetime.now():%Y%m%d_%H%M%S}.json')
with open(caminho_saida, 'w', encoding='utf-8') as arquivo:
    json.dump(resultado, arquivo, ensure_ascii=False, indent=2)

print(f'Resposta salva em: {caminho_saida}')
print(f'Total de registros: {len(resultado["retorno"])}')