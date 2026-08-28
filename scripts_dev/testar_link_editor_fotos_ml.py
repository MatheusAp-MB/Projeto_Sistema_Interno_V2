# scripts_dev/testar_link_editor_fotos_ml.py
#
# Ponto 1 do Hub de Fotos ("Editar no ML"): antes de mexer em modelo,
# migração ou importação, só queremos confirmar se o padrão de link real
# (com o MLBU no lugar do MLB) funciona de verdade.
#
# Lê o detalhes_mlbs.json (saída do "buscar_detalhes", ponto 03 da
# integracao_mercado_livre — já tem "user_product_id"/MLBU por registro,
# só não é aproveitado hoje na importação pro banco) e monta o link pros
# N primeiros MLBs distintos que tiverem MLBU preenchido.
#
# Não toca no banco, não faz nenhuma chamada de API — só lê o JSON que já
# existe em disco e imprime os links no console pra você clicar e
# conferir manualmente, 1 por 1.

import json
from pathlib import Path

# ==== CONFIGURA AQUI ANTES DE RODAR ====
EMPRESA = 'Magazine'  # ou 'Samvale'
QUANTIDADE_DE_TESTES = 5
# ========================================

RAIZ_INTEGRACAO = Path(__file__).resolve().parent.parent / 'integracao_mercado_livre'
CAMINHO_JSON = RAIZ_INTEGRACAO / 'Arquivos_API' / EMPRESA / 'detalhes_mlbs.json'


def montar_link(mlbu):
    return (
        f'https://www.mercadolivre.com.br/publicaciones/{mlbu}'
        f'/modificar/omni/variation/dominio/picture-uploader-default'
    )


def main():
    if not CAMINHO_JSON.exists():
        print(f'Não encontrei {CAMINHO_JSON}.')
        print(f'Rode "manage.py buscar_detalhes --empresa {EMPRESA.lower()}" primeiro (ponto 03).')
        return

    with open(CAMINHO_JSON, encoding='utf-8') as f:
        dados = json.load(f)

    registros = dados.get('registros', [])
    print(f'{len(registros)} registros no JSON ({EMPRESA}).\n')

    com_mlbu = [r for r in registros if r.get('user_product_id')]
    print(f'{len(com_mlbu)} registros com user_product_id (MLBU) preenchido.\n')

    if not com_mlbu:
        print('Nenhum registro com MLBU encontrado — nada pra testar.')
        return

    print(f'=== Até {QUANTIDADE_DE_TESTES} links pra testar manualmente ===\n')

    mlbs_ja_mostrados = set()
    total_mostrado = 0

    for registro in com_mlbu:
        mlb = registro.get('mlb')
        # * [EXPLICAÇÃO] → 1 MLB pode ter várias linhas (1 por variação),
        #                  cada uma com seu próprio MLBU — pra esse teste
        #                  queremos produtos DIFERENTES, então pegamos só
        #                  a 1ª variação encontrada de cada MLB.
        if mlb in mlbs_ja_mostrados:
            continue
        mlbs_ja_mostrados.add(mlb)

        mlbu = registro['user_product_id']
        sku = registro.get('sku')
        titulo = registro.get('title')
        link = montar_link(mlbu)

        total_mostrado += 1
        print(f'[{total_mostrado}] MLB={mlb}  SKU={sku}  MLBU={mlbu}')
        print(f'    Título: {titulo}')
        print(f'    Link:   {link}\n')

        if total_mostrado >= QUANTIDADE_DE_TESTES:
            break

    if total_mostrado < QUANTIDADE_DE_TESTES:
        print(f'(só encontrei {total_mostrado} MLBs distintos com MLBU — menos que os {QUANTIDADE_DE_TESTES} pedidos)')


if __name__ == '__main__':
    main()