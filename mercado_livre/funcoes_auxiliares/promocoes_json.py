# * [RESUMO] → Lê o arquivo de amostra de promoções (gerado pelo projeto
#              da API) e busca os dados de 1 MLB específico — usado pela
#              tela de teste de margem/rebate. Não é um importador pro
#              banco (é leitura direta do JSON, sob demanda, só pra essa
#              tela experimental).

import json
from pathlib import Path

CAMINHO_PROMOCOES = Path('Arquivos_API/amostra_promocoes.json')


def buscar_promocoes_do_mlb(mlb, caminho=CAMINHO_PROMOCOES):
    """Busca as promoções de 1 MLB específico no arquivo de amostra.
    Retorna um dict com 'encontrado' (bool) e, se True, 'sku' e
    'promocoes' (lista já validada, vazia se a chamada à API tiver
    falhado do lado da coleta)."""
    if not caminho.exists():
        return {'encontrado': False, 'erro': f'Arquivo {caminho} não encontrado.'}

    with open(caminho, encoding='utf-8') as f:
        dados = json.load(f)

    for grupo in dados.get('fase2_grupos', []):
        for m in grupo.get('mlbs', []):
            if m.get('mlb') == mlb:
                resultado = m.get('promocoes', {})
                if not resultado.get('chamado') or resultado.get('http') != 200:
                    return {
                        'encontrado': True,
                        'sku': m.get('sku'),
                        'promocoes': [],
                        'erro': f'Chamada à API sem sucesso (http={resultado.get("http")}).',
                    }
                return {
                    'encontrado': True,
                    'sku': m.get('sku'),
                    'promocoes': resultado.get('dados') or [],
                    'erro': None,
                }

    return {'encontrado': False, 'erro': f'MLB {mlb} não encontrado no arquivo de amostra.'}