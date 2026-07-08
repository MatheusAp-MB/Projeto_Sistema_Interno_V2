import json

MLB_ALVO = 'MLB3831844768'  # troque pelo MLB que você quer investigar

with open('Arquivos_API/dados_completos_por_sku.json', encoding='utf-8') as f:
    dados = json.load(f)

encontrado = False

for bloco_sku in dados.get('skus', []):
    for mlb_dados in bloco_sku.get('mlbs', []):
        if mlb_dados.get('mlb') != MLB_ALVO:
            continue

        encontrado = True
        ptw = mlb_dados.get('price_to_win', {})
        info = ptw.get('dados')

        print(f"SKU: {bloco_sku.get('sku')}")
        print(f"MLB: {mlb_dados.get('mlb')}")
        print(f"MLBU: {mlb_dados.get('mlbu')}")
        print(f"Classificação: {mlb_dados.get('classificacao')}")
        print(f"catalog_product_id: {mlb_dados.get('catalog_product_id')}")
        print()

        if not ptw.get('chamado'):
            print("price_to_win não foi chamado para este MLB.")
        elif not info:
            print(f"chamado=True mas dados=None (http={ptw.get('http')}, erro={ptw.get('erro')})")
        else:
            print(f"status: {info.get('status')}")
            print(f"current_price: {info.get('current_price')}")
            print(f"price_to_win: {info.get('price_to_win')}")
            print(f"visit_share: {info.get('visit_share')}")
            print(f"competitors_sharing_first_place: {info.get('competitors_sharing_first_place')}")
            print(f"consistent: {info.get('consistent')}")
            print(f"reason: {info.get('reason')}")
            print(f"winner: {json.dumps(info.get('winner'), indent=2, ensure_ascii=False)}")

if not encontrado:
    print(f"MLB {MLB_ALVO} não encontrado no arquivo.")

print(f"\n'gerado_em' do arquivo inteiro: {dados.get('gerado_em')}")