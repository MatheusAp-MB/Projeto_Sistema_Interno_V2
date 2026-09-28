"""
teste_teoria_cache_frete_passo1.py — lê o log já gerado e mede o potencial real de
cache, sem chamar a API de novo. Chave de agrupamento = TODOS os parâmetros que a
FreteRealML.simular() manda pra API (dimensions, item_price, verbose, condition,
category_id, listing_type_id, mode, free_shipping) — não confia que nenhum deles é
constante, mesmo que hoje verbose/condition/mode sejam fixos no código; se algum
desses 3 virar variável no futuro, o script (e o cache de produção) já está correto
sem precisar lembrar de atualizar a chave.

Rodar direto (não precisa de Django, só lê texto):
    python teste_teoria_cache_frete_passo1.py integracao_mercado_livre/logs/Magazine/simular_frete_ml.log
"""
import ast
import re
import sys
from collections import Counter
from pathlib import Path

PADRAO_LINHA = re.compile(r'Chamando GET /users/\*\*\*/shipping_options/free \| (\{.*\})\s*$')

# Ordem fixa — define exatamente o que compõe a chave de agrupamento/cache.
CAMPOS_DA_CHAVE = (
    'dimensions', 'item_price', 'verbose', 'condition',
    'category_id', 'listing_type_id', 'mode', 'free_shipping',
)


def extrair_chamadas(caminho_log):
    chamadas = []
    with open(caminho_log, encoding='utf-8') as f:
        for linha in f:
            m = PADRAO_LINHA.search(linha)
            if not m:
                continue
            try:
                info = ast.literal_eval(m.group(1))
            except (ValueError, SyntaxError):
                continue
            params = info.get('params') or {}
            if 'dimensions' not in params:
                continue  # é buscar_frete_real_ml (item_id), não simular_frete
            chave = tuple(params.get(campo) for campo in CAMPOS_DA_CHAVE)
            chamadas.append(chave)
    return chamadas


def main():
    if len(sys.argv) != 2:
        print('Uso: python teste_teoria_cache_frete_passo1.py <caminho_do_log>')
        sys.exit(1)

    chamadas = extrair_chamadas(Path(sys.argv[1]))
    contagem = Counter(chamadas)

    total_chamadas = len(chamadas)
    combinacoes_unicas = len(contagem)
    repetidas = {chave: qtd for chave, qtd in contagem.items() if qtd > 1}
    chamadas_evitaveis = total_chamadas - combinacoes_unicas

    print(f'Total de chamadas feitas nesse log: {total_chamadas}')
    print(f'Combinações únicas ({", ".join(CAMPOS_DA_CHAVE)}): {combinacoes_unicas}')
    if total_chamadas:
        print(f'Chamadas que o cache teria evitado: {chamadas_evitaveis} '
              f'({chamadas_evitaveis / total_chamadas:.1%} do total)')
    print('\nTop 10 combinações que mais se repetiram:')
    for chave, qtd in sorted(repetidas.items(), key=lambda kv: -kv[1])[:10]:
        detalhes = ', '.join(f'{campo}={valor}' for campo, valor in zip(CAMPOS_DA_CHAVE, chave))
        print(f'  {qtd}x — {detalhes}')


if __name__ == '__main__':
    main()