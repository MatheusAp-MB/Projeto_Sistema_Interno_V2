# * [RESUMO] → Importa dados de competição de catálogo (price_to_win)
#              do mesmo arquivo dados_completos_por_sku.json usado
#              para qualidade. Só processa MLBs com
#              classificacao == 'catalogo' — outros tipos nem têm
#              price_to_win chamado pela API.

import json
from mercado_livre.models import AnuncioMercadoLivre, CompeticaoCatalogo


def importar_competicao_catalogo(stdout, style, caminho_json):
    if not caminho_json.exists():
        stdout.write(style.WARNING(
            f'[COMPETIÇÃO] Arquivo {caminho_json} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[COMPETIÇÃO] Lendo {caminho_json}...')

    with open(caminho_json, encoding='utf-8') as f:
        dados = json.load(f)

    blocos_sku = dados.get('skus', [])
    stdout.write(f'    {len(blocos_sku)} SKU(s) no arquivo')

    criados = 0
    atualizados = 0
    sem_anuncio = 0
    nao_catalogo = 0

    for bloco in blocos_sku:
        for mlb_dados in bloco.get('mlbs', []):
            if mlb_dados.get('classificacao') != 'catalogo':
                nao_catalogo += 1
                continue

            mlb = mlb_dados.get('mlb')
            anuncio = AnuncioMercadoLivre.objects.filter(mlb=mlb).first()
            if not anuncio:
                sem_anuncio += 1
                stdout.write(f'    [SEM ANÚNCIO] {mlb} não encontrado no banco — pulado')
                continue

            ptw = mlb_dados.get('price_to_win', {})
            info = ptw.get('dados') if ptw.get('chamado') else None

            _, criado = CompeticaoCatalogo.objects.update_or_create(
                anuncio=anuncio,
                defaults={
                    'status': info.get('status') if info else None,
                    'current_price': info.get('current_price') if info else None,
                    'price_to_win': info.get('price_to_win') if info else None,
                    'currency_id': info.get('currency_id') if info else None,
                    'visit_share': info.get('visit_share') if info else None,
                    'competitors_sharing_first_place': info.get('competitors_sharing_first_place') if info else None,
                    'consistent': info.get('consistent') if info else None,
                    'catalog_product_id': info.get('catalog_product_id') if info else None,
                    'reason': info.get('reason') if info else None,
                    'boosts': info.get('boosts') if info else None,
                    'winner': info.get('winner') if info else None,
                    'http_status': ptw.get('http'),
                    'erro': ptw.get('erro'),
                }
            )

            if criado:
                criados += 1
            else:
                atualizados += 1

    stdout.write('')
    stdout.write(style.SUCCESS(
        f'[COMPETIÇÃO] Concluído!\n'
        f'    Criados: {criados}\n'
        f'    Atualizados: {atualizados}\n'
        f'    Sem anúncio correspondente: {sem_anuncio}\n'
        f'    Ignorados (não são Catálogo): {nao_catalogo}'
    ))