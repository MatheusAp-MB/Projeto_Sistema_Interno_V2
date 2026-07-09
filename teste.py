import json

with open("Arquivos_API\\detalhes_mlbs.json", encoding='utf-8') as f:
    dados = json.load(f)

registros_do_mlb = [r for r in dados['registros'] if r.get('mlb') == 'MLB6806867734']

for r in registros_do_mlb:
    print('price:', r.get('price'))
    print('original_price:', r.get('original_price'))
    print('base_price:', r.get('base_price'))