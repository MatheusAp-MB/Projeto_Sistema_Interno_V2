# scripts_exploracao_ERP/explorar_manifesto_nota_entrada.py

# Função Objetivo: Primeira exploração real do único endpoint documentado
# da API Sysemp — chama listarManifestoNotaEntrada e salva a resposta bruta
# em JSON, pra estudarmos o formato real do dado (a doc não diz o formato
# de data nem o comportamento do offset). Roda manualmente, direto desta
# pasta — 0 integração com o Django por decisão explícita nesta fase.

import json
import os
from datetime import datetime

from dotenv import load_dotenv

from cliente_sysemp import ClienteApiSysemp

_PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_PASTA_ATUAL, '.env'))

PASTA_SAIDAS = os.path.join(_PASTA_ATUAL, 'saidas')
os.makedirs(PASTA_SAIDAS, exist_ok=True)

token = os.environ.get('SYSEMP_API_TOKEN')
if not token:
    raise RuntimeError(
        'SYSEMP_API_TOKEN não encontrado. Crie scripts_exploracao_ERP/.env '
        'com a linha SYSEMP_API_TOKEN=seu_token_aqui (esse arquivo já é ignorado pelo git).'
    )

cliente = ClienteApiSysemp(token)

# ==== CONFIGURA AQUI ANTES DE RODAR ====
DATA_INICIAL = '2026-07-07'  # ISO (YYYY-MM-DD) — Postgres aceita isso independente de locale
DATA_FINAL = '2026-08-06'    # últimos 30 dias, só pra ver se a API aceita e o que volta
OFFSET = '0'                 # "" quebrou pra data; offset também pode não aceitar vazio
# ========================================

print(f'Chamando listarManifestoNotaEntrada (inicial={DATA_INICIAL!r}, final={DATA_FINAL!r}, offset={OFFSET!r})...')
resultado = cliente.listar_manifesto_nota_entrada(DATA_INICIAL, DATA_FINAL, OFFSET)

carimbo = datetime.now().strftime('%Y%m%d_%H%M%S')
caminho_saida = os.path.join(PASTA_SAIDAS, f'manifesto_nota_entrada_{carimbo}.json')
with open(caminho_saida, 'w', encoding='utf-8') as arquivo:
    json.dump(resultado, arquivo, ensure_ascii=False, indent=2)

print(f'Resposta salva em: {caminho_saida}')
print(f'Tipo do resultado: {type(resultado).__name__}')
if isinstance(resultado, list):
    print(f'Quantidade de itens: {len(resultado)}')
    if resultado:
        print(f'Chaves do 1º item: {list(resultado[0].keys())}')
elif isinstance(resultado, dict):
    print(f'Chaves no nível raiz: {list(resultado.keys())}')