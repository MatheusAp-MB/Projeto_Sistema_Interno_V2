import json

with open("Arquivos_API\\detalhes_mlbs.json", encoding='utf-8') as f:
    dados = json.load(f)

registro = dados['registros'][0]
print(registro.keys())