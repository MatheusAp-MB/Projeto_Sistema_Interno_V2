import json

def mapear_estrutura(obj, prefixo='', nivel=0, max_nivel=4):
    if nivel > max_nivel:
        return
    indent = '  ' * nivel
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            tipo = type(valor).__name__
            if isinstance(valor, (dict, list)):
                print(f'{indent}{prefixo}{chave} ({tipo})')
                mapear_estrutura(valor, '', nivel + 1, max_nivel)
            else:
                exemplo = str(valor)[:50]
                print(f'{indent}{prefixo}{chave} ({tipo}) = {exemplo}')
    elif isinstance(obj, list):
        print(f'{indent}[lista com {len(obj)} item(ns)]')
        if obj:
            mapear_estrutura(obj[0], '[0].', nivel + 1, max_nivel)


arquivo = "Arquivos_API\dados_completos_por_sku.json"


with open(arquivo, encoding='utf-8') as f:
    dados = json.load(f)

mapear_estrutura(dados)