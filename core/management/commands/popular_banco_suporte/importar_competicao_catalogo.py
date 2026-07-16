# * [RESUMO] → Importa dados de competição de catálogo (price_to_win)
#              do mesmo arquivo dados_completos_por_sku.json usado
#              para qualidade. Só processa MLBs com
#              classificacao == 'catalogo' — outros tipos nem têm
#              price_to_win chamado pela API.
#
#              Reescrito em auditoria de otimização: antes fazia
#              AnuncioMercadoLivre.objects.filter(mlb=mlb).first() +
#              CompeticaoCatalogo.objects.update_or_create(...) POR
#              MLB (2-3 consultas individuais cada, nenhum bulk_*) —
#              o arquivo estruturalmente menos otimizado do pipeline.
#              Agora segue o mesmo padrão dos outros: carrega tudo em
#              memória 1 vez, processa, grava em lote no final.

import time
from mercado_livre.models import AnuncioMercadoLivre, CompeticaoCatalogo
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO
from core.funcoes_auxiliares.contador_consultas import contar_consultas


def importar_competicao_catalogo(stdout, style, caminho_json):
    if not caminho_json.exists():
        stdout.write(style.WARNING(
            f'[COMPETIÇÃO] Arquivo {caminho_json} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[COMPETIÇÃO] Lendo {caminho_json}...')

    with contar_consultas() as contador:
        inicio_total = time.perf_counter()

        inicio_leitura = time.perf_counter()
        import json
        with open(caminho_json, encoding='utf-8') as f:
            dados = json.load(f)

        blocos_sku = dados.get('skus', [])
        stdout.write(f'    {len(blocos_sku)} SKU(s) no arquivo')

        # * [EXPLICAÇÃO] → Separa os itens de Catálogo ANTES de tocar no
        #                  banco — só eles precisam de AnuncioMercadoLivre
        #                  carregado, evita carregar anúncios que nunca
        #                  vão ser usados nesta etapa.
        itens_catalogo = []
        nao_catalogo = 0
        for bloco in blocos_sku:
            for mlb_dados in bloco.get('mlbs', []):
                if mlb_dados.get('classificacao') == 'catalogo':
                    itens_catalogo.append(mlb_dados)
                else:
                    nao_catalogo += 1

        tempo_leitura = time.perf_counter() - inicio_leitura
        stdout.write(f'  ⏱ Ler o JSON e separar itens de Catálogo: {tempo_leitura:.1f}s')

        inicio_carga_banco = time.perf_counter()
        mlbs_catalogo = [item.get('mlb') for item in itens_catalogo]
        anuncios_por_mlb = {
            a.mlb: a for a in AnuncioMercadoLivre.objects.filter(mlb__in=mlbs_catalogo)
        }

        competicoes_existentes = {
            c.anuncio_id: c
            for c in CompeticaoCatalogo.objects.filter(anuncio_id__in=[a.id for a in anuncios_por_mlb.values()])
        }
        tempo_carga_banco = time.perf_counter() - inicio_carga_banco
        stdout.write(f'  ⏱ Carregar anúncios/competições existentes do banco: {tempo_carga_banco:.1f}s')

        para_criar = []
        para_atualizar = []
        sem_anuncio = 0

        total_itens = len(itens_catalogo)

        inicio_loop = time.perf_counter()
        for indice, mlb_dados in enumerate(itens_catalogo, start=1):
            if indice % 300 == 0 or indice == total_itens:
                decorrido = time.perf_counter() - inicio_loop
                stdout.write(f'    ... {indice}/{total_itens} MLBs de Catálogo processados ({decorrido:.1f}s)')

            mlb = mlb_dados.get('mlb')
            anuncio = anuncios_por_mlb.get(mlb)
            if not anuncio:
                sem_anuncio += 1
                stdout.write(f'    [SEM ANÚNCIO] {mlb} não encontrado no banco — pulado')
                continue

            ptw = mlb_dados.get('price_to_win', {})
            info = ptw.get('dados') if ptw.get('chamado') else None

            dados_competicao = dict(
                status=info.get('status') if info else None,
                current_price=info.get('current_price') if info else None,
                price_to_win=info.get('price_to_win') if info else None,
                currency_id=info.get('currency_id') if info else None,
                visit_share=info.get('visit_share') if info else None,
                competitors_sharing_first_place=info.get('competitors_sharing_first_place') if info else None,
                consistent=info.get('consistent') if info else None,
                catalog_product_id=info.get('catalog_product_id') if info else None,
                reason=info.get('reason') if info else None,
                boosts=info.get('boosts') if info else None,
                winner=info.get('winner') if info else None,
                http_status=ptw.get('http'),
                erro=ptw.get('erro'),
            )

            existente = competicoes_existentes.get(anuncio.id)
            if existente:
                for campo, valor in dados_competicao.items():
                    setattr(existente, campo, valor)
                # * [EXPLICAÇÃO] → Se ainda não tem PK, é um objeto NOVO
                #                  criado nesta mesma rodada (o mesmo MLB
                #                  apareceu 2x no arquivo) — já vai ser
                #                  salvo pelo bulk_create com os valores
                #                  já atualizados, não pode ir pro
                #                  bulk_update (mesmo bug já corrigido em
                #                  importar_promocoes_ml.py e importar_
                #                  qualidade_anuncio.py, esquecido aqui).
                if existente.pk and existente not in para_atualizar:
                    para_atualizar.append(existente)
            else:
                nova = CompeticaoCatalogo(anuncio=anuncio, **dados_competicao)
                para_criar.append(nova)
                competicoes_existentes[anuncio.id] = nova

        tempo_loop = time.perf_counter() - inicio_loop
        stdout.write(f'  ⏱ Loop de processamento (todos os MLBs de Catálogo): {tempo_loop:.1f}s')

        campos = [
            'status', 'current_price', 'price_to_win', 'currency_id', 'visit_share',
            'competitors_sharing_first_place', 'consistent', 'catalog_product_id',
            'reason', 'boosts', 'winner', 'http_status', 'erro',
        ]

        inicio_salvar = time.perf_counter()
        if para_criar:
            CompeticaoCatalogo.objects.bulk_create(para_criar, batch_size=BATCH_SIZE_PADRAO)
        if para_atualizar:
            CompeticaoCatalogo.objects.bulk_update(para_atualizar, campos, batch_size=BATCH_SIZE_PADRAO)
        tempo_salvar = time.perf_counter() - inicio_salvar
        stdout.write(f'  ⏱ Salvar no banco (bulk_create/bulk_update): {tempo_salvar:.1f}s')

        tempo_total = time.perf_counter() - inicio_total

    stdout.write(f'  📊 Consultas ao banco (SQL) no total: {contador["total"]}')

    stdout.write(style.SUCCESS(
        f'[COMPETIÇÃO] Concluído em {tempo_total:.1f}s!\n'
        f'    Criados: {len(para_criar)}\n'
        f'    Atualizados: {len(para_atualizar)}\n'
        f'    Sem anúncio correspondente: {sem_anuncio}\n'
        f'    Ignorados (não são Catálogo): {nao_catalogo}'
    ))