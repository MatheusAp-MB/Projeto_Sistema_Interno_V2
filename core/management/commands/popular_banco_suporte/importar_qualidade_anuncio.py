# * [RESUMO] → Importa dados de qualidade/performance do JSON gerado
#              pelo buscar_dados_sku_completo.py (projeto paralelo de
#              API). Para cada MLB: cria/atualiza QualidadeAnuncio
#              (resumo) e QualidadeAnuncioCriterio (os 16 critérios).
#              Critérios não catalogados são criados automaticamente
#              (catalogado=False), nunca perdendo dado da API.

import json
from datetime import datetime
from mercado_livre.models import AnuncioMercadoLivre, CriterioQualidade, QualidadeAnuncio, QualidadeAnuncioCriterio


def parsear_data(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except Exception:
        return None


def extrair_regras_do_bucket(buckets):
    # * [EXPLICAÇÃO] → buckets já vem decodificado (lista de dicts),
    #                  conforme combinado com o script gerador.
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

    qualidades_criadas = 0
    qualidades_atualizadas = 0
    criterios_novos_catalogados_como_desconhecido = 0
    sem_anuncio_correspondente = 0
    total_mlbs = 0

    for bloco in blocos_sku:
        for mlb_dados in bloco.get('mlbs', []):
            total_mlbs += 1
            mlb = mlb_dados.get('mlb')

            anuncio = AnuncioMercadoLivre.objects.filter(mlb=mlb).first()
            if not anuncio:
                sem_anuncio_correspondente += 1
                stdout.write(f'    [SEM ANÚNCIO] {mlb} não encontrado no banco — pulado')
                continue

            performance = mlb_dados.get('performance', {})
            perf_dados = performance.get('dados') if performance.get('chamado') else None

            qualidade, criado = QualidadeAnuncio.objects.update_or_create(
                anuncio=anuncio,
                defaults={
                    'score': perf_dados.get('score') if perf_dados else None,
                    'nivel': perf_dados.get('level_wording') if perf_dados else None,
                    'calculado_em': parsear_data(perf_dados.get('calculated_at')) if perf_dados else None,
                    'http_status': performance.get('http'),
                    'erro': performance.get('erro'),
                }
            )

            if criado:
                qualidades_criadas += 1
            else:
                qualidades_atualizadas += 1

            if not perf_dados:
                continue

            regras = extrair_regras_do_bucket(perf_dados.get('buckets'))

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

                QualidadeAnuncioCriterio.objects.update_or_create(
                    qualidade=qualidade,
                    criterio=criterio,
                    defaults={
                        'status': status_valor,
                        'score': info.get('score'),
                        'calculado_em': parsear_data(info.get('calculated_at')),
                        'link_correcao': info.get('link'),
                    }
                )

    stdout.write('')
    stdout.write(style.SUCCESS(
        f'[QUALIDADE] Concluído!\n'
        f'    Total de MLBs processados: {total_mlbs}\n'
        f'    QualidadeAnuncio criados: {qualidades_criadas}\n'
        f'    QualidadeAnuncio atualizados: {qualidades_atualizadas}\n'
        f'    Sem anúncio correspondente: {sem_anuncio_correspondente}\n'
        f'    Critérios novos (desconhecidos): {criterios_novos_catalogados_como_desconhecido}'
    ))