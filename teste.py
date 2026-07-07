import json

with open('Arquivos_API/dados_completos_por_sku.json', encoding='utf-8') as f:  # ajusta o nome se for diferente
    dados = json.load(f)

for bloco_sku in dados.get('skus', []):
    for mlb_dados in bloco_sku.get('mlbs', []):
        if mlb_dados.get('classificacao') != 'catalogo':
            continue

        ptw = mlb_dados.get('price_to_win', {})
        info = ptw.get('dados')
        if not info:
            continue

        status = info.get('status')
        tem_winner = 'winner' in info

        print(f"{mlb_dados.get('mlb')}: status={status} | tem_winner={tem_winner}")