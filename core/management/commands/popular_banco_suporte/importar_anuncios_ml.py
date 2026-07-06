# core/management/commands/popular_banco_suporte/importar_anuncios_ml.py

import json
from datetime import datetime
from marketplaces.models import Marketplace
from produtos.models import Produto
from mercado_livre.models import (
    TipoDeAnuncioMercadoLivre,
    AnuncioMercadoLivre,
    VariacaoAnuncioMercadoLivre,
)


def classificar_catalogo(registro):
    if not registro.get('catalog_product_id'):
        return TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.SIMPLES
    if registro.get('catalog_listing') is True:
        return TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.CATALOGO
    return TipoDeAnuncioMercadoLivre.ClassificacaoCatalogo.BASE


def parsear_data(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except Exception:
        return None


def importar_anuncios_ml(stdout, style, caminho_json):
    stdout.write(f'[ANUNCIOS ML] Lendo {caminho_json}...')

    with open(caminho_json, encoding='utf-8') as f:
        dados = json.load(f)

    registros = dados.get('registros', [])
    stdout.write(f'    {len(registros)} registros no JSON')

    marketplace_ml = Marketplace.objects.filter(sigla='ML').first()
    if not marketplace_ml:
        stdout.write(style.ERROR('    Marketplace ML não encontrado. Rode iniciar_banco primeiro.'))
        return

    # ================================================
    # 1. CARREGA TUDO QUE JÁ EXISTE EM MEMÓRIA
    # ================================================
    produtos_por_sku = {p.sku: p for p in Produto.objects.exclude(sku__isnull=True)}

    tipos_por_chave = {
        (t.status, t.tipo_anuncio, t.tipo_logistico, t.classificacao_catalogo, t.flex): t
        for t in TipoDeAnuncioMercadoLivre.objects.filter(marketplace=marketplace_ml)
    }

    anuncios_existentes = {a.mlb: a for a in AnuncioMercadoLivre.objects.all()}

    # ================================================
    # 2. AGRUPA OS REGISTROS DO JSON POR MLB
    # ================================================
    # * [EXPLICAÇÃO] → Cada MLB pode ter N linhas (1 por variação).
    #                  Todas compartilham os mesmos dados de agrupador
    #                  (confirmado com dado real) — usamos a primeira
    #                  ocorrência para preencher o AnuncioMercadoLivre.
    por_mlb = {}
    for reg in registros:
        mlb = reg.get('mlb')
        if not mlb:
            continue
        por_mlb.setdefault(mlb, []).append(reg)

    stdout.write(f'    {len(por_mlb)} MLBs únicos encontrados')

    # ================================================
    # 3. DESCOBRE TIPOS NOVOS E CRIA EM LOTE
    # ================================================
    tipos_novos_chaves = set()
    for mlb, linhas in por_mlb.items():
        primeira = linhas[0]
        chave = (
            primeira.get('status') or '',
            primeira.get('listing_type_id') or '',
            primeira.get('logistic_type') or '',
            classificar_catalogo(primeira),
            bool(primeira.get('flex')),
        )
        if chave not in tipos_por_chave:
            tipos_novos_chaves.add(chave)

    novos_tipos = [
        TipoDeAnuncioMercadoLivre(
            marketplace=marketplace_ml,
            status=s, tipo_anuncio=ta, tipo_logistico=tl,
            classificacao_catalogo=cc, flex=fl
        )
        for (s, ta, tl, cc, fl) in tipos_novos_chaves
    ]
    if novos_tipos:
        TipoDeAnuncioMercadoLivre.objects.bulk_create(novos_tipos)

    tipos_por_chave = {
        (t.status, t.tipo_anuncio, t.tipo_logistico, t.classificacao_catalogo, t.flex): t
        for t in TipoDeAnuncioMercadoLivre.objects.filter(marketplace=marketplace_ml)
    }

    # ================================================
    # 4. MONTA OS ANÚNCIOS (AGRUPADOR) EM MEMÓRIA
    # ================================================
    anuncios_para_criar = {}
    anuncios_para_atualizar = {}

    for mlb, linhas in por_mlb.items():
        primeira = linhas[0]

        chave_tipo = (
            primeira.get('status') or '',
            primeira.get('listing_type_id') or '',
            primeira.get('logistic_type') or '',
            classificar_catalogo(primeira),
            bool(primeira.get('flex')),
        )
        tipo = tipos_por_chave.get(chave_tipo)

        dados_anuncio = dict(
            titulo_anuncio=primeira.get('title'),
            tipo_de_anuncio=tipo,
            catalog_product_id=primeira.get('catalog_product_id'),
            catalog_listing=primeira.get('catalog_listing'),
            item_relations=primeira.get('item_relations'),
            permalink=primeira.get('permalink'),
            data_criacao_ml=parsear_data(primeira.get('date_created')),
            ultima_atualizacao_ml=parsear_data(primeira.get('last_updated')),
        )

        existente = anuncios_existentes.get(mlb)
        if existente:
            for campo, valor in dados_anuncio.items():
                setattr(existente, campo, valor)
            anuncios_para_atualizar[mlb] = existente
        else:
            anuncios_para_criar[mlb] = AnuncioMercadoLivre(mlb=mlb, **dados_anuncio)

    if anuncios_para_criar:
        AnuncioMercadoLivre.objects.bulk_create(list(anuncios_para_criar.values()), batch_size=1000)

    if anuncios_para_atualizar:
        campos_anuncio = list(dados_anuncio.keys())
        AnuncioMercadoLivre.objects.bulk_update(
            list(anuncios_para_atualizar.values()), campos_anuncio, batch_size=1000
        )

    # Recarrega todos os anúncios (criados + atualizados) por MLB
    anuncios_por_mlb = {a.mlb: a for a in AnuncioMercadoLivre.objects.filter(mlb__in=por_mlb.keys())}

    # ================================================
    # 5. MONTA AS VARIAÇÕES EM MEMÓRIA
    # ================================================
    variacoes_existentes = {
        (v.anuncio_id, v.variacao_id): v
        for v in VariacaoAnuncioMercadoLivre.objects.filter(anuncio__mlb__in=por_mlb.keys())
    }

    variacoes_para_criar = []
    variacoes_para_atualizar = []
    sem_produto = 0

    for mlb, linhas in por_mlb.items():
        anuncio = anuncios_por_mlb.get(mlb)
        if not anuncio:
            continue

        for linha in linhas:
            # * [EXPLICAÇÃO] → Quando não há variação real, o próprio JSON
            #                  usa o mlb como variacao_id (comportamento do
            #                  buscar_detalhes.py) — mantemos esse valor
            #                  como chave, garantindo que TODO anúncio
            #                  sempre tenha ao menos 1 variação.
            variacao_id = str(linha.get('variacao_id') or mlb)

            sku_ml  = linha.get('sku')
            produto = produtos_por_sku.get(sku_ml)
            if sku_ml and not produto:
                sem_produto += 1

            dados_variacao = dict(
                sku_ml=sku_ml,
                produto=produto,
                estoque=linha.get('available_quantity') or 0,
                qtd_vendas=linha.get('sold_quantity') or 0,
                atributos=linha.get('variacao_atributos'),
                num_fotos=linha.get('variacao_num_fotos') or 0,
                thumbnail_url=linha.get('thumbnail'),
                imagem_principal_url=linha.get('imagem_principal'),
            )

            chave = (anuncio.pk, variacao_id)
            existente = variacoes_existentes.get(chave)
            if existente:
                for campo, valor in dados_variacao.items():
                    setattr(existente, campo, valor)
                variacoes_para_atualizar.append(existente)
            else:
                variacoes_para_criar.append(
                    VariacaoAnuncioMercadoLivre(anuncio=anuncio, variacao_id=variacao_id, **dados_variacao)
                )

    if variacoes_para_criar:
        VariacaoAnuncioMercadoLivre.objects.bulk_create(variacoes_para_criar, batch_size=1000)

    if variacoes_para_atualizar:
        campos_variacao = ['sku_ml', 'produto', 'estoque', 'qtd_vendas', 'atributos', 'num_fotos', 'thumbnail_url', 'imagem_principal_url']
        VariacaoAnuncioMercadoLivre.objects.bulk_update(
            variacoes_para_atualizar, campos_variacao, batch_size=1000
        )

    stdout.write('')
    stdout.write(style.SUCCESS(
        f'[ANUNCIOS ML] Concluído!\n'
        f'    Tipos novos criados:       {len(novos_tipos)}\n'
        f'    Anúncios criados:          {len(anuncios_para_criar)}\n'
        f'    Anúncios atualizados:      {len(anuncios_para_atualizar)}\n'
        f'    Variações criadas:         {len(variacoes_para_criar)}\n'
        f'    Variações atualizadas:     {len(variacoes_para_atualizar)}\n'
        f'    Sem produto correspondente: {sem_produto}'
    ))