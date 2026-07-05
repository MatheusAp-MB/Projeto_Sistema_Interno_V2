import json

with open('Arquivos_API/detalhes_mlbs.json', encoding='utf-8') as f:
    dados = json.load(f)

registros = dados['registros']

# Acha o primeiro MLB com variação
mlbs_com_variacao = {}
for reg in registros:
    if reg.get('tem_variacoes'):
        mlb = reg['mlb']
        mlbs_com_variacao.setdefault(mlb, []).append(reg)

# Pega o primeiro caso e mostra todas as linhas dele, lado a lado
primeiro_mlb = next(iter(mlbs_com_variacao))
linhas = mlbs_com_variacao[primeiro_mlb]

print(f'MLB: {primeiro_mlb} — {len(linhas)} variações\n')

campos_interesse = [
    'mlb', 'variacao_id', 'sku', 'title', 'status',
    'available_quantity', 'sold_quantity',
    'catalog_product_id', 'catalog_listing',
    'date_created', 'last_updated', 'permalink',
    'variacao_atributos', 'variacao_num_fotos',
]

for i, linha in enumerate(linhas, 1):
    print(f'--- Variação {i} ---')
    for campo in campos_interesse:
        print(f'  {campo}: {linha.get(campo)}')
    print()

print(f'\nTotal de MLBs com variação no arquivo: {len(mlbs_com_variacao)}')