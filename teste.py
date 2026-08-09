import json
from pathlib import Path

MARCA_FILTRO = ''  # busca por substring em "Fornecedor", sem case sensitivity

with open(Path("scripts_exploracao_ERP/saidas/nota_mais_recente_por_produto.json"), encoding='utf-8') as f:
    dados = json.load(f)

dados_da_marca = {
    ean: r for ean, r in dados.items()
    if MARCA_FILTRO.upper() in (r.get('Fornecedor') or '').upper()
}
print(f'Produtos da marca "{MARCA_FILTRO}": {len(dados_da_marca)} de {len(dados)}\n')

tributado, reducao, st = [], [], []

for ean, r in dados_da_marca.items():
    aliquota_icms = float(r.get('Aliquota ICMS') or 0)
    reducao_icms = float(r.get('Redução ICMS') or 0)
    valor_icms_st = float(r.get('Valor ICMS ST') or 0)

    if valor_icms_st > 0:
        st.append((ean, r.get('Produto'), aliquota_icms, reducao_icms, valor_icms_st))
    elif aliquota_icms != 0 and reducao_icms == 0:
        tributado.append((ean, r.get('Produto'), aliquota_icms, reducao_icms))
    elif aliquota_icms != 0 and 0 < reducao_icms < 100:
        reducao.append((ean, r.get('Produto'), aliquota_icms, reducao_icms))

print(f'--- TRIBUTADO ({len(tributado)} candidatos) ---')
for c in tributado[:5]:
    print(c)

print(f'\n--- REDUÇÃO ({len(reducao)} candidatos) ---')
for c in reducao[:50]:
    print(c)

print(f'\n--- ST ({len(st)} candidatos) ---')
for c in st[:5]:
    print(c)