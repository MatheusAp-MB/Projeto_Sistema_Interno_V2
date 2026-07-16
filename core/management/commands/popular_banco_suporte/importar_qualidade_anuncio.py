# * [RESUMO] → Importa dados de qualidade/performance do JSON gerado
#              pelo buscar_dados_sku_completo.py (projeto paralelo de
#              API). Para cada MLB: cria/atualiza QualidadeAnuncio
#              (resumo, por VARIAÇÃO) e QualidadeAnuncioCriterio
#              (os 16 critérios). Critérios não catalogados são
#              criados automaticamente (catalogado=False), nunca
#              perdendo dado da API.
#
#              Qualidade é medida por MLB pela API, mas a fonte da
#              verdade no sistema é a Variação (folha) — o mesmo
#              resultado é replicado para todas as variações daquele
#              MLB. Hoje, na prática, é quase sempre 1 variação só.

import json
from datetime import datetime
from mercado_livre.models import AnuncioMercadoLivre, CriterioQualidade, QualidadeAnuncio, QualidadeAnuncioCriterio
from core.funcoes_auxiliares.constantes_performance import BATCH_SIZE_PADRAO


def parsear_data(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except Exception:
        return None


def extrair_regras_do_bucket(buckets):
    resultado = {}
    if not buckets:
        return resultado

    for bucket in buckets:
        for variable in bucket.get('variables', []):
            var_score = variable.get('score')
            var_calculated = variable.get('calculated_at')
            for rule in variable.get('rules', []):
                key = rule.get('key')
                if not key:
                    continue
                wordings = rule.get('wordings', {})
                resultado[key] = {
                    'status': rule.get('status'),
                    'score': var_score,
                    'calculated_at': var_calculated,
                    'link': wordings.get('link'),
                    'api_title': wordings.get('title'),
                }
    return resultado


def importar_qualidade_anuncio(stdout, style, caminho_json):
    if not caminho_json.exists():
        stdout.write(style.WARNING(
            f'[QUALIDADE] Arquivo {caminho_json} não encontrado — pulando essa etapa.'
        ))
        return

    stdout.write(f'[QUALIDADE] Lendo {caminho_json}...')

    with open(caminho_json, encoding='utf-8') as f:
        dados = json.load(f)

    blocos_sku = dados.get('skus', [])
    stdout.write(f'    {len(blocos_sku)} SKU(s) no arquivo')

    criterios_por_key = {c.rule_key: c for c in CriterioQualidade.objects.all()}

    # * [EXPLICAÇÃO] → Pré-carrega tudo de uma vez (2 queries), em vez de
    #                  buscar Anúncio/Variação um por um dentro do loop.
    anuncios_por_mlb = {
        a.mlb: a
        for a in AnuncioMercadoLivre.objects.prefetch_related('variacoes').all()
    }
    qualidades_existentes = {qa.variacao_id: qa for qa in QualidadeAnuncio.objects.all()}

    qualidades_para_criar = []
    qualidades_para_atualizar = []
    # * [EXPLICAÇÃO] → set() de id() dos objetos já enfileirados pra
    #                  atualizar — substitui "not in qualidades_para_
    #                  atualizar" (checagem numa LISTA, O(n) — mesmo
    #                  bug confirmado e corrigido em importar_promocoes_
    #                  ml.py, aqui o volume é menor mas é a mesma classe
    #                  de problema). set() é O(1).
    ids_ja_na_lista_atualizar = set()
    # * [EXPLICAÇÃO] → Guarda as regras (critérios) de cada variação pra
    #                  processar DEPOIS que soubermos o ID de cada
    #                  QualidadeAnuncio (só existe depois do bulk_create).
    regras_por_variacao_id = {}

    sem_anuncio_correspondente = 0
    total_mlbs = 0
    criterios_novos_catalogados_como_desconhecido = 0

    total_mlbs_esperado = sum(len(bloco.get('mlbs', [])) for bloco in blocos_sku)

    for bloco in blocos_sku:
        for mlb_dados in bloco.get('mlbs', []):
            total_mlbs += 1
            if total_mlbs % 500 == 0 or total_mlbs == total_mlbs_esperado:
                stdout.write(f'    ... {total_mlbs}/{total_mlbs_esperado} MLBs processados')

            mlb = mlb_dados.get('mlb')

            anuncio = anuncios_por_mlb.get(mlb)
            if not anuncio:
                sem_anuncio_correspondente += 1
                stdout.write(f'    [SEM ANÚNCIO] {mlb} não encontrado no banco — pulado')
                continue

            variacoes_do_mlb = list(anuncio.variacoes.all())
            if not variacoes_do_mlb:
                sem_anuncio_correspondente += 1
                stdout.write(f'    [SEM VARIAÇÃO] {mlb} não tem nenhuma variação no banco — pulado')
                continue

            performance = mlb_dados.get('performance', {})
            perf_dados = performance.get('dados') if performance.get('chamado') else None
            regras = extrair_regras_do_bucket(perf_dados.get('buckets')) if perf_dados else {}

            for variacao_alvo in variacoes_do_mlb:
                dados_qualidade = dict(
                    score=perf_dados.get('score') if perf_dados else None,
                    nivel=perf_dados.get('level_wording') if perf_dados else None,
                    calculado_em=parsear_data(perf_dados.get('calculated_at')) if perf_dados else None,
                    http_status=performance.get('http'),
                    erro=performance.get('erro'),
                )

                existente = qualidades_existentes.get(variacao_alvo.id)
                if existente:
                    for campo, valor in dados_qualidade.items():
                        setattr(existente, campo, valor)
                    # * [EXPLICAÇÃO] → Se ainda não tem PK, é um objeto
                    #                  NOVO criado nesta mesma rodada (a
                    #                  mesma variação apareceu 2x no
                    #                  arquivo) — já vai ser salvo pelo
                    #                  bulk_create com os valores
                    #                  atualizados, não precisa (e não
                    #                  pode) ir pro bulk_update.
                    if existente.pk and id(existente) not in ids_ja_na_lista_atualizar:
                        qualidades_para_atualizar.append(existente)
                        ids_ja_na_lista_atualizar.add(id(existente))
                else:
                    nova = QualidadeAnuncio(variacao=variacao_alvo, **dados_qualidade)
                    qualidades_para_criar.append(nova)
                    # * evita duplicar se a mesma variação aparecer 2x no arquivo
                    qualidades_existentes[variacao_alvo.id] = nova

                if regras:
                    regras_por_variacao_id[variacao_alvo.id] = regras

    campos_qualidade = ['score', 'nivel', 'calculado_em', 'http_status', 'erro']

    if qualidades_para_criar:
        QualidadeAnuncio.objects.bulk_create(qualidades_para_criar, batch_size=BATCH_SIZE_PADRAO)
    if qualidades_para_atualizar:
        QualidadeAnuncio.objects.bulk_update(qualidades_para_atualizar, campos_qualidade, batch_size=BATCH_SIZE_PADRAO)

    qualidades_criadas = len(qualidades_para_criar)
    qualidades_atualizadas = len(qualidades_para_atualizar)

    # * [EXPLICAÇÃO] → Rebusca os IDs direto do banco (1 query), em vez de
    #                  confiar que bulk_create preencheu .id sozinho —
    #                  mais simples e 100% seguro, independente de
    #                  particularidade do MySQL nesse ponto.
    ids_variacao_com_regras = list(regras_por_variacao_id.keys())
    qualidade_id_por_variacao_id = dict(
        QualidadeAnuncio.objects.filter(variacao_id__in=ids_variacao_com_regras)
        .values_list('variacao_id', 'id')
    )

    criterios_existentes = {
        (qac.qualidade_id, qac.criterio_id): qac
        for qac in QualidadeAnuncioCriterio.objects.filter(
            qualidade_id__in=qualidade_id_por_variacao_id.values()
        )
    }

    criterios_para_criar = []
    criterios_para_atualizar = []

    for variacao_id, regras in regras_por_variacao_id.items():
        qualidade_id = qualidade_id_por_variacao_id.get(variacao_id)
        if not qualidade_id:
            continue

        for rule_key, info in regras.items():
            criterio = criterios_por_key.get(rule_key)

            if not criterio:
                criterio = CriterioQualidade.objects.create(
                    rule_key=rule_key,
                    grupo=CriterioQualidade.Grupo.DESCONHECIDO,
                    nome=info.get('api_title') or rule_key,
                    pergunta=info.get('api_title') or rule_key,
                    catalogado=False,
                )
                criterios_por_key[rule_key] = criterio
                criterios_novos_catalogados_como_desconhecido += 1
                stdout.write(style.WARNING(f'    [CRITÉRIO NOVO] {rule_key} não catalogado — criado como Desconhecido'))

            status_valor = (
                QualidadeAnuncioCriterio.Status.APROVADO
                if info['status'] == 'COMPLETED'
                else QualidadeAnuncioCriterio.Status.NAO_APROVADO
            )
            dados_criterio = dict(
                status=status_valor,
                score=info.get('score'),
                calculado_em=parsear_data(info.get('calculated_at')),
                link_correcao=info.get('link'),
            )

            chave = (qualidade_id, criterio.id)
            existente_crit = criterios_existentes.get(chave)
            if existente_crit:
                for campo, valor in dados_criterio.items():
                    setattr(existente_crit, campo, valor)
                criterios_para_atualizar.append(existente_crit)
            else:
                novo = QualidadeAnuncioCriterio(qualidade_id=qualidade_id, criterio=criterio, **dados_criterio)
                criterios_para_criar.append(novo)
                criterios_existentes[chave] = novo

    campos_criterio = ['status', 'score', 'calculado_em', 'link_correcao']

    if criterios_para_criar:
        QualidadeAnuncioCriterio.objects.bulk_create(criterios_para_criar, batch_size=BATCH_SIZE_PADRAO)
    if criterios_para_atualizar:
        QualidadeAnuncioCriterio.objects.bulk_update(criterios_para_atualizar, campos_criterio, batch_size=BATCH_SIZE_PADRAO)

    stdout.write('')
    stdout.write(style.SUCCESS(
        f'[QUALIDADE] Concluído!\n'
        f'    Total de MLBs processados: {total_mlbs}\n'
        f'    QualidadeAnuncio criados: {qualidades_criadas}\n'
        f'    QualidadeAnuncio atualizados: {qualidades_atualizadas}\n'
        f'    Sem anúncio correspondente: {sem_anuncio_correspondente}\n'
        f'    Critérios novos (desconhecidos): {criterios_novos_catalogados_como_desconhecido}'
    ))