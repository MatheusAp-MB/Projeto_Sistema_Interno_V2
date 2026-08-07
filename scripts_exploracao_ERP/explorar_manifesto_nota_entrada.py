# scripts_exploracao_ERP/explorar_manifesto_nota_entrada.py

# Função Objetivo: Exploração manual do único endpoint documentado da API
# Sysemp — instancia ApiSysemp (autenticação já resolvida por dentro) e usa
# o contexto de impostos de entrada. Ainda sem parsing/formatação da saída
# — não conhecemos o formato real o suficiente pra isso. Roda manualmente,
# direto desta pasta.

import json
import os
from datetime import datetime

from api_sysemp import ApiSysemp

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))

# ==== CONFIGURA AQUI ANTES DE RODAR ====
DATA_INICIAL = '2026-08-01'  # ISO (AAAA-MM-DD) — manual de propósito, nunca calculado
DATA_FINAL = '2026-08-07'    # idem — recusado se estiver mais de 1 dia no futuro
OFFSET = '0'                 # string de inteiro não-negativo — nunca vazia, já quebrou antes
# ========================================

api = ApiSysemp()
resultado = api.impostos_entrada.listar_por_periodo(DATA_INICIAL, DATA_FINAL, OFFSET)

os.makedirs(os.path.join(_PASTA_ATUAL, 'saidas'), exist_ok=True)
caminho_saida = os.path.join(_PASTA_ATUAL, 'saidas', f'manifesto_nota_entrada_{datetime.now():%Y%m%d_%H%M%S}.json')
with open(caminho_saida, 'w', encoding='utf-8') as arquivo:
    json.dump(resultado, arquivo, ensure_ascii=False, indent=2)

print(f'Resposta salva em: {caminho_saida}')
print(f'Tipo do resultado: {type(resultado).__name__}')
if isinstance(resultado, dict):
    print(f'Chaves no nível raiz: {list(resultado.keys())}')