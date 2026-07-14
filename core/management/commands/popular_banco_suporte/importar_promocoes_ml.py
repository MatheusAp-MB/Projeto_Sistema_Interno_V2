# * [RESUMO] → Importa promoções do arquivo gerado pelo projeto da API
#              pro banco — nunca mais lido ao vivo por nenhuma tela
#              depois dessa importação existir (regra do projeto: tudo
#              vem do banco, arquivo só serve pra popular). Roda dentro
#              do popular_banco, com a mesma proteção de "arquivo
#              ausente → pula" dos outros importadores.

import json
from datetime import datetime
from pathlib import Path
from django.utils import timezone

from mercado_livre.models import AnuncioMercadoLivre, PromocaoMercadoLivre

CAMINHO_PROMOCOES = Path('Arquivos_API/amostra_promocoes.json')


def _parsear_data(valor):
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    except (ValueError, TypeError):
        return None


def _chave_externa(promo):
    # * [EXPLICAÇÃO] → PRICE_DISCOUNT não tem id nem ref_id na API —
    #                  usa o próprio tipo como fallback (só existe 1
    #                  PRICE_DISCOUNT por variação de qualquer forma).
    return promo.get('id') or promo.get('ref_id') or promo.get('type')


def importar_promocoes_ml(stdout, style, caminho=CAMINHO_PROMOCOES):
    if not caminho.exists():
        stdout.write(style.WARNING(
            f'[PROMOÇÕES ML] Arquivo {caminho} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[PROMOÇÕES ML] Lendo {caminho}...')

    with open(caminho, encoding='utf-8') as f:
        dados = json.load(f)

    mlbs_no_arquivo = []
    for grupo in dados.get('fase2_grupos', []):
        mlbs_no_arquivo.extend(grupo.get('mlbs', []))

    stdout.write(f'    {len(mlbs_no_arquivo)} MLB(s) no arquivo')

    mlbs_texto = [m.get('mlb') for m in mlbs_no_arquivo if m.get('mlb')]
    anuncios_por_mlb = {
        a.mlb: a for a in AnuncioMercadoLivre.objects.filter(mlb__in=mlbs_texto).prefetch_related('variacoes')
    }

    promocoes_existentes = {
        (p.variacao_id, p.chave_externa): p
        for p in PromocaoMercadoLivre.objects.all()
    }

    para_criar = []
    para_atualizar = []
    sem_anuncio = 0
    sem_variacao = 0
    dados_promo = {}

    total_mlbs_promo = len(mlbs_no_arquivo)

    for indice, mlb_dados in enumerate(mlbs_no_arquivo, start=1):
        if indice % 50 == 0 or indice == total_mlbs_promo:
            stdout.write(f'    ... {indice}/{total_mlbs_promo} MLBs processados')

        mlb = mlb_dados.get('mlb')
        anuncio = anuncios_por_mlb.get(mlb)
        if not anuncio:
            sem_anuncio += 1
            continue

        variacao = anuncio.variacoes.first()
        if not variacao:
            sem_variacao += 1
            continue

        resultado = mlb_dados.get('promocoes', {})
        if not resultado.get('chamado') or resultado.get('http') != 200:
            continue

        for promo in resultado.get('dados') or []:
            chave = _chave_externa(promo)
            if not chave:
                continue

            dados_promo = dict(
                tipo=promo.get('type'),
                nome=promo.get('name'),
                status=promo.get('status'),
                preco_original=promo.get('original_price'),
                preco_avaliado=promo.get('price') or promo.get('suggested_discounted_price'),
                meli_percentage=promo.get('meli_percentage'),
                seller_percentage=promo.get('seller_percentage'),
                inicio_vigencia=_parsear_data(promo.get('start_date')),
                fim_vigencia=_parsear_data(promo.get('finish_date')),
            )

            existente = promocoes_existentes.get((variacao.id, chave))
            if existente:
                for campo, valor in dados_promo.items():
                    setattr(existente, campo, valor)
                para_atualizar.append(existente)
            else:
                nova = PromocaoMercadoLivre(variacao=variacao, chave_externa=chave, **dados_promo)
                para_criar.append(nova)
                promocoes_existentes[(variacao.id, chave)] = nova

    campos = list(dados_promo.keys())

    if para_criar:
        PromocaoMercadoLivre.objects.bulk_create(para_criar, batch_size=1000)
    if para_atualizar and campos:
        PromocaoMercadoLivre.objects.bulk_update(para_atualizar, campos, batch_size=1000)

    stdout.write(style.SUCCESS(
        f'[PROMOÇÕES ML] Concluído!\n'
        f'    Promoções criadas: {len(para_criar)}\n'
        f'    Promoções atualizadas: {len(para_atualizar)}\n'
        f'    Sem anúncio correspondente: {sem_anuncio}\n'
        f'    Sem variação: {sem_variacao}'
    ))