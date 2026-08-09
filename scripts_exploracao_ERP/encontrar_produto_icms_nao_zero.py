import json

with open(r'scripts_exploracao_ERP/saidas/nota_mais_recente_por_produto.json', encoding='utf-8') as f:
    dados = json.load(f)

candidatos = [
    (ean, r.get('Produto'), r.get('Aliquota ICMS'), r.get('Redução ICMS'))
    for ean, r in dados.items()
    if float(r.get('Aliquota ICMS') or 0) != 0 and float(r.get('Redução ICMS') or 0) != 0
]

print(f'{len(candidatos)} produto(s) com Alíquota ICMS E Redução ICMS != 0:')
for c in candidatos:
    print(c)